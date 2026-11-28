# 复刻清单：从训练到板端出框

> 这是 2026-11-28 实际跑通的那条路的完整记录，每一步都有实测数据。
> 换模型、换类别、换板子时照着走即可。
>
> 板子：正点原子 ATK-CNN647B（STM32N647X0HxQ，外部 NOR `BY25FQ128EL` 16 MB）

---

## 0 工具版本（必须对齐）

| 工具 | 版本 | 说明 |
| :--- | :--- | :--- |
| STM32CubeIDE | **1.17.0** | 与工程 `.ioc`（CubeMX 6.13.0）配套 |
| STM32CubeProgrammer | **2.22.0** | ≥2.18 才支持 N6；≥2.21 签名要加 `--align` |
| ST Edge AI Core | **4.1.0** | 自带 N6 的 Neural-ART 后端，**不需要**额外的 Neural-ART 包 |
| Python | 3.12 | ultralytics 8.4.215 / onnx 1.23.2 / onnxruntime 1.32.0 |

> 2.0 那条线（ll_aton 1.0.0）需要单独的 `stedgeai-stneuralart-10.0.0.zip`，
> 被 ST 登录墙卡住，所以走 4.1 + 升级 runtime。

---

## 1 训练

```powershell
# 从 coco128 过滤出单类 person（61 张 / 254 框 / 48:13 切分）
python notebooks\make_person_dataset.py

# 训练
yolo train model=yolov8n.pt data=D:\STM32N6\yolo-baseline\datasets\person128\person128.yaml `
           imgsz=224 epochs=40 batch=8 device=cpu workers=0 plots=False
```

| 产物 | 指标 |
| :--- | :--- |
| `best.pt` | mAP50 **0.575** / mAP50-95 0.340（13 张验证图，只能做相对比较） |

---

## 2 导出 ONNX

```powershell
yolo export model=runs\person224\weights\best.pt format=onnx `
             imgsz=224 opset=17 simplify=True end2end=False
```

三条硬要求：**opset 17**、**无 NMS**（`end2end=False`）、**simplify**（要装 `onnxslim`）。

---

## 3 量化（int8，有符号！）

```powershell
python notebooks\quantize_onnx.py <best.onnx> <图片目录> `
    --out best_int8_signed.onnx `
    --exclude-head nonconv --calib percentile --act qint8
```

| 参数 | 值 | 为什么 |
| :--- | :--- | :--- |
| `--act qint8` | **有符号 int8** | STEdgeAI 拒绝 `QUInt8`：`NOT IMPLEMENTED: Onnx ... unsigned integer format` |
| `--exclude-head nonconv` | 排除 24 个**无权重**解码节点 | 这些节点量化后精度崩，排除它们不增加任何体积 |
| `--calib percentile` | 校准方法 | MinMax/Entropy 差别很小 |

| 产物 | 结果 |
| :--- | :--- |
| `best_int8_signed.onnx` | 3.34 MB，mAP50 **0.551** |

---

## 4 STEdgeAI 生成

```powershell
stedgeai generate --no-inputs-allocation --no-outputs-allocation `
    --model best_int8_signed.onnx --target stm32n6 `
    --st-neural-art default@user_neuralart.json `
    --input-data-type uint8 --output-data-type float32
```

`user_neuralart.json` + `my_mpools\stm32n6.mpool` 从 991 工程拷过来（**原样不改**）。

| 产物 | 大小 | 用途 |
| :--- | :--- | :--- |
| `network.c` / `network.h` | 0.47 MB | 编译进固件 |
| `network_ecblobs.h` | 0.45 MB | 编译进固件 |
| `network_atonbuf.xSPI2.raw` | **3.00 MB** | 烧到 `0x70200000` |
| `stai_network.c/h` | — | 可选（用的是 ll_aton 原生 API，没用上） |
| `network_c_info.json` | 1.31 MB | **布局的权威来源，见第 7 节** |

---

## 5 运行时升级（1.0.0 → 1.1.5）

三处都要换，少一处就编不过：

```
Middlewares\AI\Npu\ll_aton\                  ← 覆盖（49 个文件）
Middlewares\AI\Npu\Devices\STM32N6XX\        ← 也要覆盖（新版 platform.h 依赖新 ATON.h）
Middlewares\AI\Lib\GCC\ARMCortexM55\
    NetworkRuntime1000_CM55_GCC.a            ← 用 NetworkRuntime1210 覆盖，保持文件名不变
```

---

## 6 工程改动（991 为底）

| 文件 | 改什么 |
| :--- | :--- |
| `Appli\Core\Inc\app_config.h` | `NN_CLASSES` 2→**1**；类别表 `{"person"}`；`NN_BUFFER_OUT_SIZE` 5880→**20580**；`POSTPROCESS_TYPE` 换成自定义值；新增 5 个 `AI_OBJDETECT_CUSTOM_PP_*` 常量 |
| `Appli\Core\Inc\app_postprocess.h` | 新增 `#define POSTPROCESS_OD_YOLO_V8_CUSTOM (99)` |
| `Appli\Core\Src\app_postprocess.c` | 加 `#include "yolo_v8_nms.c"`；三条 `#elif` 链里各插一个自定义分支 |
| `Appli\Core\Src\app.c` | 6 处 `_Default`→`_network`；加 `nn_input_chw` 缓冲 + **HWC→CHW 转置** |
| `Appli\Core\Src\main.c` | `npu_cache_init()` → `npu_cache_enable_clocks_and_reset()` |
| `Npu\Devices\STM32N6XX\npu_cache.c` | 两个 `HAL_CACHEAXI_Msp*` 加 `__attribute__((weak))` |

---

## 7 ★ 两个布局陷阱

从 `network_c_info.json` 的 `buffers` 里读出的**权威**布局（不要信 report 的 `oshape`）：

| buffer | 形状 | `channel_first` | 影响 |
| :--- | :--- | :--- | :--- |
| 输入 `Input_2_out_0` | `[1,3,224,224]` | **true** | 必须把交错 RGB 转成**平面 RRR…GGG…BBB** |
| 输出 `Concat_815_out_0` | `[1,5,1029]` | **true** | 读 `raw[c*1029 + i]`，不是 `raw[i*5 + c]` |

**症状对照**（这两个坑花的时间最多）：

| 如果搞错 | 屏幕现象 |
| :--- | :--- |
| 输入不转置 | 满屏假框，但框位置"看着合理"——因为噪声喂进去也会出结构化输出 |
| 输出按错 stride | 框上显示的"置信度"是坐标值：**38.70、145.88、218.43** |

DCMIPP 没有平面 RGB 输出格式（只有 `RGB888_YUV444_1` 交错），所以只能在软件里转，代价 **约 14 ms/帧**（82→96）。

---

## 8 生成权重镜像并烧录

```powershell
# .raw 要改名成 .bin，CubeProgrammer 不认 .raw
Copy-Item network_atonbuf.xSPI2.raw network_data.bin

# 板子必须先切到 Development boot（B1→3V3），否则 app 占着 XSPI 会擦除失败
$cp = "D:\ST\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe"
$el = "D:\ST\STM32CubeProgrammer\bin\ExternalLoader\BY25FQ128EL_ATK-CNN647B_ExtMemLoader.stldr"

& $cp -c port=SWD mode=UR -el $el -hardRst -w network_data.bin 0x70200000
& $cp -c port=SWD mode=UR -el $el -hardRst -w Project.bin     0x70100400
```

| 区域 | 地址 | 来源 |
| :--- | :--- | :--- |
| FSBL | `0x70000000` | 不换（出厂自带，有 `STM2` 头） |
| 应用 | **`0x70100400`** | Release 配置的 `.bin` |
| 权重 | **`0x70200000`** | `network_atonbuf.xSPI2.raw` |

**烧完切回 Flash boot（B0、B1 都接地）上电。**

---

## 9 验收

| 观察项 | 正常值 | 本次实测 |
| :--- | :--- | :--- |
| 画面 | 摄像头实时图像 | ✅ |
| 框 | 贴在人体轮廓上，框上显示 `person 0.xx` | ✅ |
| `Inference` | 90~100 ms | **96 ms** |
| `FPS` | 9~10 | **10.00** |
| `Peoples` | 无人时 0，有人时 1~2 | 0~5 |
| `CPU load` | 26~28% | 26.6% |

对比出厂 TinyYOLOv2 demo：**225 ms → 96 ms，FPS 4.29 → 10.00**。

---

## 10 已知问题

| 问题 | 原因 | 解决方向 |
| :--- | :--- | :--- |
| 手会被误判成 person | 训练集只有 48 张，COCO 里手部常算进 person | 扩数据集 + 把手部特写当负样本 |
| 框不够准（会横跨几个目标） | 小数据集导致定位能力弱 | 同上，或提高输入分辨率 |
| 每次烧录都要切跳线 | app 跑起来会占住 XSPI | 板子固有流程；或买外置 ST-LINK V3 走 RAM 调试 |

---

## 回滚

```powershell
# 恢复出厂固件（16 MB 整片，Development boot 下执行）
& $cp -c port=SWD mode=UR -el $el -w "D:\STM32N6\backup\atk-factory-16MB.bin" 0x70000000
```

备份文件：`D:\STM32N6\backup\atk-factory-16MB.bin`
SHA256 `1242B6AA15B6AF1A5BAD4DA7AEF2462F8DDDC66BFE8E4CF4015C4D83684AE8A2`
