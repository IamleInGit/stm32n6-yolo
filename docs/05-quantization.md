# 阶段 2 · int8 量化

> 日期：2026-11-16 · 状态：**已找到零体积代价的配方**

---

## 0 结论

| 配置 | 排除节点 | mAP50 | mAP50-95 | 体积 |
| :--- | ---: | ---: | ---: | ---: |
| fp32（基准） | — | 0.575 | 0.340 | 12.04 MB |
| int8 全量 | 0 | 0.367 | 0.184 | **3.34 MB** |
| int8 排整个头 | 66 | 0.540 | 0.334 | 5.79 MB |
| **int8 只排解码节点** | **24** | **0.547** | **0.334** | **3.34 MB** |

**推荐配置：`--exclude-head nonconv`。** 用 27.7% 的体积拿到接近 fp32 的精度。

预训练模型交叉验证（80 类，数据充足）：

| 配置 | mAP50 | mAP50-95 | 体积 |
| :--- | ---: | ---: | ---: |
| fp32 | 0.393 | 0.284 | 12.12 MB |
| 全量 int8 | 0.192 | 0.149 | 3.37 MB |
| **只排解码节点** | **0.390** | **0.280** | **3.36 MB** |

两套模型结论一致，这**不是**针对某个模型的巧合。

---

## 1 方法

```powershell
python notebooks/quantize_onnx.py <model.onnx> <图片目录> `
  --out out.onnx --calib percentile --exclude-head nonconv
```

| 参数 | 值 |
| :--- | :--- |
| 方式 | `quantize_static` + **QDQ** |
| 权重 | `QInt8`，per-channel |
| 激活 | `QUInt8`，per-tensor |
| 校准 | Percentile（MinMax/Entropy 差别很小） |
| 排除 | `--exclude-head nonconv`（24 个无权重解码节点） |

---

## 2 排除粒度对比（本轮关键实验）

`/model.22` 检测头共 **66 个节点、882,780 参数**（fp32 占 3.37 MB）。
按不同粒度排除，结果差别很大：

| 粒度 | 节点数 | 体积 | mAP50 | 解读 |
| :--- | ---: | ---: | ---: | :--- |
| `none` 全量 | 0 | 3.34 MB | 0.367 | 精度崩 |
| `cls` 只排分类分支 | 21 | **4.73 MB** | 0.393 | 又大又差 |
| `all` 整个头 | 66 | 5.79 MB | 0.540 | 精度回来了，但代价 2.45 MB |
| **`nonconv` 只排解码节点** | **24** | **3.34 MB** | **0.547** | **最优** |

**反直觉的地方**：`cls`（只排分类分支）比 `all` 差得多，而且更占体积。
说明问题**不在**分类卷积权重，而在**解码路径**。

### 2.1 那 24 个节点是什么

全部**零参数**：

```
/model.22/Sigmoid, /model.22/Concat_2, /model.22/Concat_3,
/model.22/Sub, /model.22/Add_1, /model.22/Div_1, /model.22/Mul_2,
/model.22/dfl/Softmax, /model.22/dfl/Transpose, /model.22/dfl/Reshape_1,
/model.22/Slice, /model.22/Slice_1, /model.22/Reshape ×6, /model.22/Concat ×2 ...
```

它们是 **anchor 解码 + DFL 的坐标变换**：
`Sigmoid(置信度) → 乘 anchor → Sub/Add 网格偏移 → Div 归一化 → DFL Softmax → Concat`。

这些算子量化后误差会被**逐级放大**，最后直接体现在框坐标上。
卷积权重反而很耐量化——这解释了为什么"排卷积"没用、"排解码"立竿见影。

---

## 3 定位过程（方法比结论更值得记）

```
现象：全量量化 mAP50 掉 36%
 ├─ 假设1 校准被离群值带偏 → MinMax/Percentile/Entropy 挤在 0.32~0.37 → 否定
 ├─ 假设2 训练数据太少     → 用 COCO 预训练模型做对照（数据充足）→ 掉 51% → 否定
 ├─ 假设3 激活类型不合适   → 换 QInt8 → 0.188 → 否定
 ├─ 假设4 整个检测头       → 排 /model.22 全部 66 节点 → 0.540 → 部分命中
 └─ 假设5 只需排解码节点   → 排 24 个零参数节点 → 0.547 / 3.34MB → 命中且免费
```

两条可复用的经验：

1. **有对照模型，归因才有意义。** 一个训练充分的同类模型能立刻把"模型问题"和"量化问题"切开。
2. **先试零成本的排除。** 排除无权重节点不增加任何体积，应该优先于"整块留在 float"。

---

## 4 修正记录

第一版本文档把掉点归因为"训练数据太少"，第二版改为"整个检测头"，
现在收敛到"检测头的解码路径"。每次都是被实验推翻的，留在这里提醒自己：
**没有对照实验的归因，基本都是猜。**

---

## 5 板端含义（尚未验证）

`nonconv` 方案把那 24 个节点留在 float，在板子上意味着：

- 这些层**回落到 Cortex-M55** 用 float 跑（都是逐元素/小张量运算，CPU 尚可承受）
- 但会在 NPU ↔ CPU 之间来回搬数据，可能吃掉不少时间

**不过有个更值得注意的点**：ST 的参考实现本来就把解码和 NMS 放在 **C 代码**里
（`app_postprocess.c` + `od_yolov2_pp_if.h`），模型只输出**原始头**。
也就是说：

> 我们的 ONNX 之所以带这一堆解码节点，是因为 ultralytics 默认导出"已解码"的输出。
> 如果导出/转换时**在卷积头处截断**，让 MCU 的 C 代码做解码，
> 图会更小、更干净，这类量化问题也根本不存在。

这条路要等 STEdgeAI 到位后验证是否可行（它能不能吃"三个原始头"的输出格式）。

---

## 6 下一步

1. **等 STEdgeAI**：用它的 `onnx_quantizer` 对比本地方案；并验证能否在卷积头处截断。
2. 换更大数据集重训，把 mAP 基线做扎实（COCO 官方源实测 46 KB/s，需另找镜像）。
3. 尝试用 `--Omax-ca-pipe` 等 ST 选项时，重新确认 nonconv 方案是否仍成立。

---

## 7 复现命令

```powershell
$py  = "D:\STM32N6\py\yolo312\Scripts\python.exe"
$yolo= "D:\STM32N6\py\yolo312\Scripts\yolo.exe"
$w   = "D:\STM32N6\yolo-baseline\runs\person224\weights"

# 推荐配置
& $py D:\MyGit\stm32n6-yolo\notebooks\quantize_onnx.py "$w\best.onnx" `
      D:\STM32N6\yolo-baseline\datasets\person128\images `
      --out "$w\best_int8_nonconv.onnx" --exclude-head nonconv --calib percentile

# 精度
& $yolo val model="$w\best_int8_nonconv.onnx" `
      data=D:\STM32N6\yolo-baseline\datasets\person128\person128.yaml imgsz=224 device=cpu workers=0
```
