# 阶段 1 · PC 基线

> 日期：2026-11-16 · 状态：**单类基线已成立**（数据集偏小，指标会抖）

---

## 0 现在有什么

| | 实验 A：工具链冒烟 | 实验 B：单类基线（**部署目标形态**） |
| :--- | :--- | :--- |
| 数据集 | `coco8`（8 张） | `person128`（61 张，自 coco128 过滤） |
| 类别 | 80 | **1（person）** |
| 分辨率 | 224 | 224 |
| 用途 | 证明 torch/ultralytics/ONNX 通路 | 产出可进量化的模型 |
| 指标意义 | **无** | 弱（验证集只有 13 张） |

A 是过程，B 是产物。下面重点记 B，A 的数据留在 §6 备查。

---

## 1 环境（实测版本）

| 组件 | 版本 | 备注 |
| :--- | :--- | :--- |
| Python | 3.12.16 | uv 管理，venv 在 `D:\STM32N6\py\yolo312` |
| torch | **2.15.0+cpu** | Windows 上 PyPI 的 torch 就是 CPU 版，不会拉 CUDA |
| torchvision | 0.29.2+cpu | |
| ultralytics | **8.4.215** | |
| onnx / onnxruntime | 1.23.2 / 1.32.0 | ⚠️ 量化阶段要降到 1.16.1 / 1.20.1 |
| onnxslim | 0.1.99 | 不加它 `simplify=True` 会静默失败 |
| 硬件 | i5-12400F / 6 线程 / 无 CUDA | 纯 CPU |

---

## 2 数据集：`person128`

脚本：[`notebooks/make_person_dataset.py`](../notebooks/make_person_dataset.py)

做的事：拿 ultralytics 自带 `coco128`（128 张真图 + 真标注）→ 只保留 `class 0`（person）
→ 丢掉 79 类别的框 → 丢掉没有 person 的整张图 → 80/20 切分 → 生成 `person128.yaml`。

实测：

| 项 | 值 |
| :--- | :--- |
| coco128 原始 | 128 张 |
| 含 person | **61 张** |
| person 框总数 | **254** |
| 无 person 丢弃 | 65 张 |
| train / val | **48 / 13** |

> **必须承认的局限**：48 张训练、13 张验证，统计意义很弱。
> 这里的 mAP 只能用来做**相对比较**（量化前后、224 vs 256），
> 不能对外声称"人检测精度 0.575"。
> 真正的基线要把数据集换到 COCO val2017 的 person 子集（约 2500 张）。

---

## 3 训练结果

```powershell
& $yolo train model=yolov8n.pt data=D:\STM32N6\yolo-baseline\datasets\person128\person128.yaml `
            imgsz=224 epochs=40 batch=8 device=cpu workers=0 plots=False
```

| 项 | 值 |
| :--- | :--- |
| 40 epoch 耗时 | **54 秒**（0.015 h） |
| 参数量 | 3,132,707（3.13 M） |
| 计算量 | 8.6 GFLOPs @ 224 |
| Precision | 0.868 |
| Recall | 0.514 |
| **mAP50** | **0.575** |
| **mAP50-95** | **0.340** |

Recall 只有 0.514 是数据太少的直接后果（模型没见过足够多姿态/遮挡），不是模型结构问题。

---

## 4 导出的 ONNX（部署输入）

```powershell
& $yolo export model=runs\person224\weights\best.pt format=onnx imgsz=224 opset=17 simplify=True end2end=False
```

| 项 | 值 |
| :--- | :--- |
| opset / IR | **17** / 8 |
| 输入 | `images` `[1, 3, 224, 224]` FLOAT32 |
| 输出 | `output0` `[1, 5, 1029]` FLOAT32 = 5,145 元素 = **20,580 字节** |
| NMS | **无** ✅ |
| 节点数 | 233（简化前 263） |
| 体积 | 12.0 MB（fp32）→ int8 预计 **≈ 3.1 MB** |

`1029 = 28² + 14² + 7²`（stride 8/16/32 三个头），`5 = 4 box + 1 class`。

**和 80 类的对比**（这就是为什么要单类）：

| | 输出形状 | 字节 |
| :--- | :--- | ---: |
| 80 类 | `[1, 84, 1029]` | 345,744 |
| **1 类** | `[1, 5, 1029]` | **20,580** |

省下 325 KB —— 在 2 MB SRAM / 1.75 MB NPU 池的板子上，这不是小数目。

---

## 5 与板端的落差：现在还剩两条

### 5.1 布局 NCHW → NHWC（**结论待验证**）

现状：ONNX 是 `[1, 3, H, W]` NCHW float32；板上现成模型是 `[1, 224, 224, 3]` NHWC uint8。

但**谁来转**这一点，我目前没有 STEdgeAI，无法确认，两种可能：

| 可能 | 判据 |
| :--- | :--- |
| A. 量化/转换阶段自动插入 `Transpose`，最终 C 模型输入仍是 NHWC | `stedgeai` 的 report 里输入 layout 写 `NHWC`，且 `network.c` 的 input buffer 尺寸 = H×W×3 |
| B. 转换保留 NCHW，应用侧要自己转 | report 写 `NCHW`，则 `app.c` 里喂数据前必须转置或改 DCMIPP 输出格式 |

**不要现在就去手改 ONNX 加 Transpose**——很可能多余，还会让量化校准失效。
等 STEdgeAI 到位，看 report 的 layout 字段再决定。

### 5.2 输入 dtype：float32 → uint8

ONNX 吃归一化后的 float；DCMIPP 直接吐 uint8 RGB888。
量化时要把输入类型设为 **uint8**，否则板上每次推理都要多一遍 float 转换，白烧 CPU。

输出端保持 float（对应 `user_neuralart.json` 的 `--native-float`），后处理逻辑不用改。

### 5.3 体积（好消息）

12.0 MB fp32 → int8 **≈ 3.1 MB**，远小于现有权重池的 11 MB，空间完全不紧张。

---

## 6 附：实验 A（80 类冒烟）的数据备查

`coco8`、3 epoch、80 类：mAP50 0.435（`.pt`）/ 0.519（ONNX 复测），
ONNX 单次推理 4.5 ms、Ultralytics 全流程 6.5 ms。
输出 `[1, 84, 1029]`、体积 12.1 MB。
这组数只说明"通路通"，不说明任何精度。

---

## 7 下一轮：阶段 2 量化

- [ ] 试产一版 int8 QDQ ONNX（`onnxruntime.quantization.quantize_static`，per-channel，opset 17），
      验证体积 → 约 3.1 MB，且能正常推理
- [ ] 校准集用 `person128` 的验证图（真实场景分布）
- [ ] 量掉点：int8 vs fp32 的 mAP50 差多少
- [ ] 等 STEdgeAI 到位后，用它的 `onnx_quantizer` 重做一版，对比差异
- [ ] 复核 `tools/onnx_info.py`：输入 `[1,3,H,W]`、输出 `[1,5,N]`、无 NMS

真正的量化大概率走 ST 的 `stm32ai-modelzoo-services`（`chain_eqe` / `chain_qd`），
本地的 onnxruntime 量化只是**提前探路**，用来判断"掉点大概什么量级"。
