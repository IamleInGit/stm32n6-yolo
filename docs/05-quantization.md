# 阶段 2 · int8 量化（本地探路）

> 日期：2026-11-16 · 状态：**流程已打通，精度结论暂不可用**

---

## 0 结论先行

| 指标 | fp32 | int8（最好配置） | 变化 |
| :--- | ---: | ---: | :--- |
| 体积 | 12.04 MB | **3.34 MB** | **27.8%** |
| CPU 单次推理 | 4.37 ms | **2.58 ms** | **1.7× 加速** |
| mAP50 | 0.575 | 0.367 | **−0.208** |
| mAP50-95 | 0.340 | 0.184 | **−0.156** |

**体积和速度都符合预期，精度掉得过多**——正常 QDQ 量化应该只掉 1~3 个点（相对 5% 以内），
这里是相对 **36%**。所以这份精度结论**不能用来判断方案可行性**，只能用来暴露问题。

---

## 1 方法与参数

```powershell
python notebooks/quantize_onnx.py `
  D:\STM32N6\yolo-baseline\runs\person224\weights\best.onnx `
  D:\STM32N6\yolo-baseline\datasets\person128\images `
  --out best_int8.onnx --calib percentile
```

| 参数 | 值 | 理由 |
| :--- | :--- | :--- |
| 量化方式 | `quantize_static` + **QDQ** | 与 ST modelzoo 的 `onnx_quantizer` 同属 QDQ 路线 |
| 权重 | `QInt8`，**per-channel** | 对齐 modelzoo 的 `granularity: per_channel` |
| 激活 | `QUInt8`，per-tensor | ST 的 N6 通常用 uint8 激活 |
| 校准集 | `person128` 全部 61 张 | 目前只有这么多 |
| 预处理 | letterbox 224 + RGB + /255 + NCHW | 与训练一致 |
| opset | 17 | 同 ONNX 导出 |

---

## 2 三种校准方法的对比

| 校准方法 | mAP50 | mAP50-95 | P | R |
| :--- | ---: | ---: | ---: | ---: |
| fp32（基准） | **0.575** | 0.340 | 0.868 | 0.514 |
| MinMax | 0.323 | 0.173 | 0.857 | 0.375 |
| Entropy | 0.323 | 0.173 | 0.857 | 0.375 |
| **Percentile** | **0.367** | 0.184 | 0.818 | 0.422 |

三种方法的结果挤在一起（0.323 / 0.323 / 0.367），**说明"校准被离群值带偏"不是主因**。
如果只是 MinMax 的锅，Percentile 应该追回一大截，实际只追回 4.4 个点。

---

## 3 掉这么多的三个候选原因

### 3.1 训练数据太少（最可能）

训练集只有 **48 张**。这种规模下模型处在"勉强学会"的边缘状态，
大量预测的置信度贴近阈值，量化噪声一扰动就跨过阈值——mAP 直接腰斩。
换句话说：**这可能不是量化的问题，是数据的问题**，只是量化把它放大了。

### 3.2 检测头对量化敏感

量化后图里有 **371 个 DequantizeLinear + 242 个 QuantizeLinear**，
但 `Sigmoid×58`、`Mul×58`、`Concat×17`、`Split×8` 这些检测头算子仍在 float 路径里进进出出。
YOLOv8 的头部（DFL + 分类/回归分支）本来就是量化最脆的地方，
头部误差还会被 NMS 二次放大（框位置差一点就被判成不同目标）。

### 3.3 校准集与训练集重叠

校准用的是训练+验证的全部 61 张，与训练集高度重叠。
重叠本身不致命（校准只需要"代表性"），但 61 张的分布太窄，
覆盖不到真实摄像头场景的光照/尺度变化。

---

## 4 这份结论的边界（必须说清）

- 验证集只有 **13 张 / 64 个实例**，mAP 本身就有 ±0.1 量级的抖动
- 这是 **onnxruntime 的 QDQ**，不是 ST 的 `onnx_quantizer`，两者不会完全等价
- 因此：**不能**据此断言"到板子上也会掉 0.2"，也**不能**据此否定 int8 方案

目前能确定的只有两件事：**体积压到 27.8%**、**CPU 上快 1.7 倍**。这两条是硬的。

---

## 5 下一步（按性价比排序）

1. **换数据集**：COCO val2017 的 person 子集（约 2500 张）重训、重校。
   这一步能同时解决 3.1 和 3.3，是唯一能把"数据问题"和"量化问题"分开的办法。
2. **试 `QInt8` 激活**（现在是 `QUInt8`），看头部是否更稳。
3. **排除检测头**：用 `nodes_to_exclude` 把最后几层留在 float，
   换精度、代价是那部分跑在 CPU 上——板上要权衡。
4. **等 STEdgeAI 到位**，用它的 `onnx_quantizer` 复现一遍，对比本地结果。
   ST 工具会针对 Neural-ART 的硬件约束做适配，这是最终要用的那套。

---

## 6 复现命令

```powershell
$py = "D:\STM32N6\py\yolo312\Scripts\python.exe"
$yolo = "D:\STM32N6\py\yolo312\Scripts\yolo.exe"
$w = "D:\STM32N6\yolo-baseline\runs\person224\weights"
$ds = "D:\STM32N6\yolo-baseline\datasets\person128\person128.yaml"

# 量化（三种校准方法任选）
& $py D:\MyGit\stm32n6-yolo\notebooks\quantize_onnx.py "$w\best.onnx" `
      D:\STM32N6\yolo-baseline\datasets\person128\images `
      --out "$w\best_int8.onnx" --calib percentile

# 体检
& $py D:\MyGit\stm32n6-yolo\tools\onnx_info.py "$w\best_int8.onnx"

# 精度
& $yolo val model="$w\best_int8.onnx" data=$ds imgsz=224 device=cpu workers=0
```

产物：`best_int8.onnx`、`best_int8_percentile.onnx`、`best_int8_entropy.onnx`（各 3.34 MB）。
