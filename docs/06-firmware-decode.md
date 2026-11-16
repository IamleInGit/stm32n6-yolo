# 固件侧解码（`src/yolo_v8_decode.c`）

> 日期：2026-11-16 · 状态：**已实现并在主机上逐值验证通过**

---

## 0 为什么写这段代码

阶段 2 的结论是：YOLOv8 的**解码路径**（anchor 还原 + DFL Softmax）对量化极其敏感，
全量量化会把 mAP50 从 0.575 打到 0.367。

同时 ST 的参考实现本来就把解码和 NMS 放在 C 代码里（`app_postprocess.c`），
模型只输出原始头。所以正确做法是：

```
NPU：跑到卷积头为止（全 int8）
CPU：用 float 做 DFL + anchor 还原 + NMS
```

这段代码就是"CPU 那部分"里最需要精确的一环：**把原始头解码成框**。

---

## 1 接口

```c
#include "yolo_v8_decode.h"

/* box_logits: [4 * 16, n_anchors]  —— 每条边 16 个 DFL logit
 * cls_logits: [n_classes,   n_anchors]
 * out:        [4 + n_classes, n_anchors] —— (cx, cy, w, h, 概率...)，单位=像素 */
int yolo_v8_decode(const float *box_logits, const float *cls_logits,
                   int img_size, int n_classes, int n_anchors, float *out);

int yolo_v8_anchor_count(int img_size);          /* 224 → 1029 */
int yolo_v8_anchor_stride(int img_size, int i);  /* → 8 / 16 / 32 */
```

特性：

- **纯 C99**，只依赖 `<math.h>`，无动态内存、无全局状态
- 栈占用 64 字节（DFL 的 16 个 exp 中间值）
- 不传 anchor 表，按 `img_size` 现场算（省 8 KB 常量）
- `n_anchors` 与 `img_size` 不匹配时返回 `-1`，避免静默越界

文件：

| 文件 | 作用 |
| :--- | :--- |
| `src/yolo_v8_decode.h` | 接口声明 |
| `src/yolo_v8_decode.c` | 实现 |
| `src/test_decode.c` | 主机端单元测试（`main` 入口，不参与固件编译） |

---

## 2 验证方法：和 numpy 参考实现逐值比对

流程：onnxruntime 跑"原始头"模型 → 导出 box/cls 二进制 → C 解码 → 与 numpy 解码结果比差。

```powershell
# 编译（zig，见 02-env-setup.md §10）
& $py -m ziglang cc -O2 -Wall -Wextra -std=c99 `
    -o build\test_decode.exe src\test_decode.c src\yolo_v8_decode.c

# 比对
& $py notebooks\check_c_decode.py runs\person224\weights\best_head.onnx `
    datasets\person128\images\val build\test_decode.exe 224
```

**结果**：

| 数据 | 最大差异 |
| :--- | ---: |
| 合成随机张量 | 1.2e-4（float32 舍入） |
| 真实张量，13 张验证图 | **6.1e-5 px** |
| 类别概率 | 0.000000（完全一致） |

在 224 px 的图上，6.1e-5 px 等于零。

---

## 3 单元测试抓到的 bug（值得记）

第一版 `dfl_expect()` **漏传了锚点索引**：

```c
/* 错的：所有锚点都读第 0 个位置 */
const float *p = logits + c * YOLO_REG_MAX * n_anchors;
sum += expf(p[k * n_anchors] - m);        /* 少了 + n */

/* 对的： */
const float *p = logits + c * YOLO_REG_MAX * n_anchors + n;
```

现象很有迷惑性：**类别概率完全正确**，只有框坐标错到 200+ px。
因为分类分支单独索引，没问题；而 DFL 分支在同一 stride 块内**所有锚点算出完全相同的宽高**。

交叉验证抓到的证据：n=0 和 n=1 的 w/h 一模一样，
而 n=784（下一尺度）的 w 恰好是 n=0 的 **2 倍**——正是 stride 从 8 跳到 16 的结果。

> 如果只跑"能出框"的冒烟测试，这个 bug 会被当成"模型精度不好"而长期潜伏。
> **数值级单测（6e-5 这种精度）不是洁癖，是唯一能发现这类错误的手段。**

---

## 4 一处优化：exp 只算一遍

原实现对每个元素算两次 `expf`（一次求和、一次加权），
1029 锚点 × 4 边 × 16 档 = **131,712 次 `expf`/帧**。

改成先存进栈数组后减半到 **65,856 次/帧**，结果不变。

MCU 上的开销估算（**待实测**）：M55 上 `expf` 若按几十个周期算，
6.6 万次大约在 **1~3 ms** 量级——对 30 ms 一帧的目标来说不能忽略。

后续优化方向：

1. 用多项式或位技巧近似 `exp`（精度损失可接受，因为 softmax 本身对误差不敏感）
2. 查表：`reg_max=16` 只有 16 档，可以预计算
3. 只对 `conf > 阈值` 的锚点做 DFL——先用 `cls_logits` 粗筛，能省掉 90% 以上的计算

第 3 条最有效：1029 个锚点里通常只有几十个是目标。

---

## 5 怎么接进 `991` 工程

等 STEdgeAI 到位、模型格式确定后：

1. 把 `src/yolo_v8_decode.c/.h` 拷进 `991_AI_People_Detection\Appli\Core\Src`（或作为独立源目录加入）
2. 在 `app.c` 里，NPU 推理完拿到 `network.c` 的输出 buffer 后调用 `yolo_v8_decode()`
3. 把 `app_config.h` 的 `POSTPROCESS_TYPE` 从 `OD_YOLO_V2_UF` 换成 YOLOv8 对应类型，
   或直接用这段代码替换 ST 的 PP 调用
4. `NN_BUFFER_OUT_SIZE` 要按原始头算：`(4*16 + nc) * n_anchors * 4` 字节
   —— 1 类 224 输入 = `(64+1)*1029*4 = 267,540` 字节（见 05 文档 §8.4 的代价讨论）

---

## 6 未决问题

**ST 的 `od_yolov8_pp_if.h` 到底期望原始头还是已解码输出？**

- 如果它要原始头 → 直接用这段 C，ST 库只做 NMS
- 如果它要已解码 → 这段代码仍要做，只是把结果喂给它，或者用 05 文档里的 `nonconv` 方案让模型自己解码

这个答案决定输出 buffer 是 20 KB 还是 267 KB，是阶段 4 的第一个待办。

---

## 7 NMS 实现与验证（`src/yolo_v8_nms.c`）

后处理的第二块：把解码后的 `[4+nc, N]` 变成最终检测框。

### 7.1 接口

```c
typedef struct { float x1, y1, x2, y2, score; int cls; } yolo_det_t;

int yolo_v8_nms(const float *dec, int n_classes, int n_anchors,
                float conf_thres, float iou_thres, int max_det,
                yolo_det_t *cand, int cand_cap,     /* 调用方提供的 scratch */
                yolo_det_t *out,  int out_cap);
```

设计取舍：

| 决定 | 理由 |
| :--- | :--- |
| 不 malloc，候选数组由调用方给 | MCU 上避免堆碎片和不确定性 |
| 按类分别 NMS | 与 ultralytics 的类内 NMS 语义一致 |
| 插入排序保留 top-K，不做全表快排 | 候选数通常只有几十个 |
| 已保留的框直接放在 `out[]`，拿它当"保留集合" | 省掉一块额外索引内存 |

### 7.2 验证：与 ultralytics 逐框比对

```powershell
& $py notebooks\check_c_nms.py runs\person224\weights\best.onnx `
    datasets\person128\images\val build\test_nms.exe 224 0.25 0.45 30
```

| 阈值组合 | ultralytics | C 实现 | 匹配 | 最小 IoU |
| :--- | ---: | ---: | ---: | ---: |
| conf 0.25 / iou 0.45 / max_det 30 | 60 | 60 | **60** | **1.00000** |
| conf 0.001 / iou 0.7 / max_det 100 | 861 | 861 | **861** | **1.00000** |

最大分数差 1e-6（float32 打印精度）。**逐位等价**，不是"差不多"。

低阈值那组是有意加的压测：mAP 计算就是用 conf=0.001，候选框数量多一个数量级，
最容易暴露 top-K 截断或排序稳定性的问题。

### 7.3 过程中修掉的一个逻辑错误

第一版用 `score = -1` 标记"已保留"，结果比较循环的判断写反了
（变成了跳过已保留的、只跟被抑制的比较）。改成"`out[]` 即保留集合"后逻辑自明，也不易再写错。

> 这类错误编译器不会提醒，跑起来也能出框，只有逐框比对才能发现。

### 7.4 现在的完整后处理栈

```
NPU 输出（原始头）
  └─ yolo_v8_decode()  → [4+nc, N]  (cx,cy,w,h,score)   ✅ 已验证 6.1e-5
       └─ yolo_v8_nms() → yolo_det_t[]                   ✅ 已验证 逐位一致
            └─ 画框（复用 991 的 app_lcd.c / stm32_lcd_ex.c）
```

两块都通过了数值级验证，等 STEdgeAI 生成 `network.c` 后就能接线。

---

## 8 端到端验证（`src/test_pipeline.c`）

把两块串起来，对比 ultralytics 的**完整流程**（完整 ONNX → NMS），而不是只比单个函数。

```powershell
& $py -m ziglang cc -O2 -Wall -Wextra -std=c99 -o build\test_pipeline.exe `
    src\test_pipeline.c src\yolo_v8_decode.c src\yolo_v8_nms.c

& $py notebooks\check_c_pipeline.py best_head.onnx best.onnx `
    datasets\person128\images\val build\test_pipeline.exe 224 0.25 0.45 30
```

### 8.1 fp32：完全一致

| 项 | 结果 |
| :--- | :--- |
| 参考（ultralytics 全流程） | 60 框 |
| C 链路（原始头 → decode → NMS） | 60 框 |
| 匹配 | **60 / 60** |
| 最小 IoU | **1.00000** |
| 最大分数差 | 1e-6 |

### 8.2 int8：位置几乎不变，置信度会挪

用 `best_head_int8.onnx`（全 int8、无 float 例外）跑同一条 C 链路，对比 fp32 全流程：

| 项 | 结果 |
| :--- | :--- |
| 参考 / C 链路（conf 0.25） | 60 / **50** 框 |
| IoU > 0.5 的匹配 | **49 / 50** |
| IoU > 0.99 的匹配 | 6 / 50 |
| 最大分数差 | **0.037** |

**怎么读这组数**：

1. **位置基本没漂**：49/50 个框的 IoU 都大于 0.5。
2. **掉的是置信度**：最大分数差 0.037，正好够让边缘框跌破 0.25 的门限，
   所以 60 → 50。这些框在 mAP 计算（conf=0.001）里仍然存在，只是排序变了。
   这和阶段 2 的结果一致：`nonconv` 方案 mAP50 只掉 0.028。
3. **IoU>0.99 只有 6 个不代表框歪了**：这是个数学问题——
   一个 20×40 的框偏 1 px，IoU 就已经是 `19×39/(20×40) ≈ 0.93`。
   小目标的 IoU 对亚像素偏移极其敏感，**用 0.99 当框准不准的判据是错的**。

### 8.3 主机端耗时

```
主机端 decode+NMS: 0.708 ms/帧（1029 锚点，500 次平均，i5-12400F）
```

**不能直接外推到 M55**（时钟低 ~5 倍、libm 的 `expf` 更慢、没有向量化），
保守估计板端会到 **几毫秒** 量级——对 30 ms 一帧的目标不能忽略。

优化方向（下一轮）：**先按 cls 置信度剪枝，只对通过的锚点算 DFL**。
1029 个锚点里通常只有几十个过阈值，能省掉 90%+ 的 `expf`。
实现上要把 decode 和 NMS 融合成一个 `yolo_v8_postprocess()`，避免为每个锚点都做完整解码。
