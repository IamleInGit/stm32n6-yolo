# 阶段 2 · int8 量化

> 日期：2026-11-16 · 状态：**根因已定位到检测头**

---

## 0 结论

| 配置 | mAP50 | mAP50-95 | 体积 |
| :--- | ---: | ---: | ---: |
| fp32（基准） | 0.575 | 0.340 | 12.04 MB |
| int8 全量量化 | 0.367 | 0.184 | **3.34 MB** |
| **int8 + 检测头留 float** | **0.540** | **0.334** | 5.79 MB |

**掉点不是数据量的问题，是检测头（`/model.22`，66 个节点）经不起 per-tensor 量化。**
把头排除后，精度基本回到 fp32——代价是体积从 27.8% 涨到 48.1%。

---

## 1 方法

```powershell
python notebooks/quantize_onnx.py <model.onnx> <图片目录> `
  --out out.onnx --calib percentile [--exclude-head] [--act qint8]
```

| 参数 | 值 |
| :--- | :--- |
| 方式 | `quantize_static` + **QDQ** |
| 权重 | `QInt8`，**per-channel** |
| 激活 | `QUInt8`，per-tensor（可切 `QInt8`） |
| 校准 | MinMax / Percentile / Entropy 可选 |
| 预处理 | letterbox 224 + RGB + /255 + NCHW |
| 检测头 | 可用 `--exclude-head` 按 `/model.22` 前缀排除 |

---

## 2 完整实验数据

### 2.1 对照模型：COCO 预训练 `yolov8n`（80 类，数据充足）

| 配置 | mAP50 | mAP50-95 | 体积 |
| :--- | ---: | ---: | ---: |
| fp32 | **0.393** | 0.284 | 12.12 MB |
| int8 全量（percentile） | 0.192 | 0.149 | 3.37 MB |
| int8 全量（`QInt8` 激活） | 0.188 | 0.148 | 3.37 MB |
| **int8 + 排除检测头** | **0.392** | **0.283** | 5.87 MB |

### 2.2 自训练 person 模型（1 类）

| 配置 | mAP50 | mAP50-95 | 体积 |
| :--- | ---: | ---: | ---: |
| fp32 | **0.575** | 0.340 | 12.04 MB |
| int8 全量 MinMax | 0.323 | 0.173 | 3.34 MB |
| int8 全量 Entropy | 0.323 | 0.173 | 3.34 MB |
| int8 全量 Percentile | 0.367 | 0.184 | 3.34 MB |
| **int8 + 排除检测头** | **0.540** | **0.334** | 5.79 MB |

两个模型、两种数据规模，结论一致：**排除检测头后精度回到 fp32 水平**。

---

## 3 怎么一步步定位到检测头的（方法比结论更值得记）

1. **先看现象**：person 模型全量量化掉了 0.208 mAP50（相对 −36%），远超正常的 1~3 个点。
2. **第一个假设：校准被离群值带偏**。加 `--calib` 开关做 MinMax/Percentile/Entropy 对比
   → 三种挤在 0.32~0.37，**否定了这个假设**（Percentile 只追回 4.4 个点）。
3. **第二个假设：训练数据太少**（只有 48 张）。要验证它，最干净的办法是换一个
   **数据充足、训练充分**的模型做同样的事。
   COCO 预训练 `yolov8n` 正好符合，而且不需要任何新下载。
4. **结果否定了数据假设**：预训练模型全量量化掉 **51%**，比小模型还惨。
   → 说明是**量化配方**的问题，与模型好坏无关。
5. **第三个假设：激活类型**。换 `QInt8` 激活 → 0.188，无改善。
   → 不是数据类型的问题。
6. **最后一个假设：检测头**。按 `/model.22` 前缀排除 66 个节点 → 精度回到 0.392。
   **定位成功。**

> 这一步的价值在于：如果没有第 3 步的对照模型，我会一直往"补数据"的方向走，
> 而那是错的。**遇到"量化掉点"，先找一个训练充分的同类模型做对照，
> 这一步能把"模型问题"和"量化问题"直接切开。**

---

## 4 修正：我上一轮判断错了

上一轮本文档写的是"训练数据太少是最可能原因"。第 3 节的对照实验**证伪了这个判断**。
已改成现在的结论。留这段是为了记住：**没有对照实验的归因，基本都是猜。**

---

## 5 代价与板端含义（重要，尚未解决）

把头留 float 换来精度，但代价不小：

| | 全量 int8 | 头留 float |
| :--- | ---: | ---: |
| 体积 | 3.34 MB（27.8%） | 5.79 MB（48.1%） |
| 精度 | 0.367 | **0.540** |

更麻烦的是**硬件层面**：Neural-ART 是 int8 计算单元，float 的检测头意味着

- 要么这些层回落到 Cortex-M55 上用 float 跑（66 个节点，慢）
- 要么工具在头前后插反量化/重量化，精度和速度都要重新评估

**但 ST 官方的 `st_yolo_x_nano` 是全 int8 的，而且跑得通。**
说明 ST 的 `onnx_quantizer` 有办法把 YOLO 头量化好，可能靠：

- 激活也用 per-channel（ORT 只支持 per-tensor 激活）
- 不同的校准策略（ST 可能有专门的 YOLO 校准）
- 或者头部的算子被映射到更宽容的硬件路径

**这一条必须等 STEdgeAI 到位才能验证，也是阶段 2 真正的悬念。**

---

## 6 下一步

1. **等 STEdgeAI**：用它的 `onnx_quantizer` 重做一遍，看全 int8 能不能也保住精度。
   这是决定"能不能上板"的关键实验。
2. 细化排除范围：现在排了整个头（66 节点），试只排最后的 `Conv`（`/model.22/cv3`、`cv2`），
   看能否在精度的几乎不掉的前提下缩回体积。
3. 换更大数据集重训（COCO val2017 person 子集），把基线本身做扎实。
   —— 注意：**这不是为了修量化**，是为了让 mAP 数字可信。
   COCO 官方源实测只有 46 KB/s（HTTPS 被证书劫持、HTTP 太慢），需要另找镜像。

---

## 7 复现命令

```powershell
$py  = "D:\STM32N6\py\yolo312\Scripts\python.exe"
$yolo= "D:\STM32N6\py\yolo312\Scripts\yolo.exe"
$w   = "D:\STM32N6\yolo-baseline\runs\person224\weights"

# 全量量化
& $py D:\MyGit\stm32n6-yolo\notebooks\quantize_onnx.py "$w\best.onnx" `
      D:\STM32N6\yolo-baseline\datasets\person128\images `
      --out "$w\best_int8.onnx" --calib percentile

# 排除检测头（推荐配置）
& $py D:\MyGit\stm32n6-yolo\notebooks\quantize_onnx.py "$w\best.onnx" `
      D:\STM32N6\yolo-baseline\datasets\person128\images `
      --out "$w\best_int8_nohead.onnx" --exclude-head --calib percentile

# 精度
& $yolo val model="$w\best_int8_nohead.onnx" `
      data=D:\STM32N6\yolo-baseline\datasets\person128\person128.yaml imgsz=224 device=cpu workers=0
```
