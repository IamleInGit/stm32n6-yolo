# DNN647 + YOLO 三周开工清单

> **目标**：D+12 看到 YOLO 在板子上跑，D+19 看到自己训练的模型，D+30 能拿给别人看。
> **时间预算**：工作日每晚 2 h（有效 ≈1.5 h）+ 周末每天 4 h（有效 ≈3 h）≈ **13 h/周**。
> 用法：每天做完打勾；没做完不要顺延全部，只把当天的任务降级到周末。

---

## 0. 三条铁律

1. **周末只做"必须连续"的事**（烧录、联调、排错）；**工作日只做"可中断"的事**（装环境、标注、训练、写配置）。把调试塞进 2 h 的晚上，你会花 40 分钟重新进入状态，然后就得停了。
2. **每晚开始前 5 分钟**：确认板子能连上、确认昨天改了哪些文件。这 5 分钟能省掉半小时的"我刚才在干嘛"。
3. **一个坑超过 2 h 就执行止损**（见第 7 节）。业余项目翻车，几乎都是在同一个坑里待了三个晚上。

---

## 1. 物料与软件

### 1.1 硬件

| 状态 | 物料 | 说明 |
|---|---|---|
| ☐ | **正点原子 MCIMX335 摄像头模块** | 关键件。没有它，整套 AI 例程跑不起来（所有 AI 例程写死只支持这个型号） |
| ☐ | FPC 延长线 + 转接板 | 若模块自带则跳过 |
| ☐ | TF 卡（≥8 GB，FAT32） | 照相机/录像例程要用，不插会卡住 |
| ☐ | USB-C 数据线 | 必须是数据线；纯充电线会出现"找不到目标" |
| ☐ | 5V/3A DC 电源（可选） | USB 供电不稳、摄像头花屏时换它 |
| ☑ | RGB 屏 800×480 | 已有。**只能用正点原子 4.3"/7" 模块**，第三方屏会花屏 |
| ☑ | OV5640 模块 | 已有。第 6 周才动，不进首版排期 |

### 1.2 软件（版本必须对齐，混版会报 `Possible mismatch in ll_aton library`）

| 软件 | 版本 | 备注 |
|---|---|---|
| STM32CubeProgrammer | ≥ 2.18 | 必须支持 N6 的外部 Flash loader |
| STM32CubeIDE | **1.17.x 或 1.18.x** | 必须 ≥1.17（N6 器件支持起点）；GCC 需为 `12.3.rel1`，装完用 `arm-none-eabi-gcc --version` 核对 |
| ST Edge AI Core | **2.0.0** | 正点原子文档验证版本（STM32CubeAI 10.0.0），可执行文件在 `<安装路径>/2.0/Utilities/windows`；版本错会报 `ll_aton` 不匹配 |
| Python | 3.9 | `tflite_support` 只支持到 3.9 |
| ultralytics | 8.3.x（ST 验证过 8.3.157） | |
| tensorflow / tf_keras | 2.15.1 / 2.15.1 | 高了会挂 |
| onnx / onnxruntime | 1.15.0 / 1.18.1 | |

---

## 2. 速查卡（建议打印贴桌边）

### 2.1 跳线与接口

- **BOOT（P6 跳线）**
  - `Flash boot`：B0、B1 **都接 GND** ← 正常运行时
  - `Development boot`：B1 接 3V3 ← 调试/烧录时
- **摄像头**：MIPI(IMX335) → 底板 `J2`；DVP(OV5640) → 底板 `P7`
- **屏**：核心板 `RGBLCD` 接口（FPC），仅 800×480
- **电源**：USB-C 或 DC，`K1` 自锁开关拨到开

### 2.2 关键路径

```
<STM32N647 开发板软件包>/
├── Projects/99_Applications/991_AI_People_Detection/   ← P1/P2 就在这
│   ├── Binary/fsbl.hex
│   ├── Binary/appli.hex
│   ├── Binary/network-data.hex     ← 换模型必须单独重烧这个
│   └── Model/generate-n6-model.sh  ← 模型转换脚本
└── Projects/35_Sensor/             ← 摄像头单独验证用
```

### 2.3 烧录命令（三条，顺序无关）

```bash
# <loader> 用软件包里自带的 .stldr（CubeProgrammer 的 ExternalLoader 目录里也能选到）
STM32_Programmer_CLI -c port=SWD mode=HOTPLUG -el "<loader>.stldr" -hardRst -w fsbl.hex
STM32_Programmer_CLI -c port=SWD mode=HOTPLUG -el "<loader>.stldr" -hardRst -w appli.hex
STM32_Programmer_CLI -c port=SWD mode=HOTPLUG -el "<loader>.stldr" -hardRst -w network-data.hex
```

> FSBL 只要不换，烧一次就够。换模型时只需重烧 `network-data.hex` + `appli.hex`。

### 2.4 现象对照表

| 现象 | 最可能的原因 | 处理 |
|---|---|---|
| 找不到目标 / 连不上 | BOOT 跳线在 Flash boot；线是充电线 | 改 Development boot，加 `-hardRst`，换线 |
| 烧录成功但重启黑屏 | 没烧 `network-data.hex`；跳线没拨回 Flash boot | 三条全烧，B0/B1 接地 |
| 屏花屏 / 条纹 | 非原厂屏 / FPC 没插到位 | 换正点原子屏，重插并锁紧 |
| 有画面但没有框 | 后处理类型选错 / 类别数不对 | 改 `app_config.h` 的 `POSTPROCESS_TYPE`、`NB_CLASSES` |
| 框全乱、置信度离谱 | 量化用了 per-tensor；校准集和实际场景不符 | 改 per-channel；校准集换成自己拍的 100 张 |
| 编译报 `ll_aton` 不匹配 | ST Edge AI 版本与工程不一致 | 统一版本，或按官方 FAQ 升级工程 |

---

## 3. 第 1 周：环境 + P1（屏上出框）

### ☐ 周一（2h）环境落地

- [ ] 装 STM32CubeProgrammer、STM32CubeIDE（需要 ST 账号）
- [ ] 下载正点原子 DNN647 资料包，**整个拷到本地磁盘**（不要放 U 盘里直接编译）
- [ ] 找到软件包里的 FSBL、991 工程、`generate-n6-model.sh` 三处位置，记在备忘录

**验收**：CubeProgrammer 能打开，资料包路径清楚。

### ☐ 周二（2h）打通烧录

- [ ] 装 ST-LINK 驱动，USB-C 连板，CubeProgrammer 读出芯片 ID
- [ ] P6 跳线设 **Development boot**（B1→3V3）
- [ ] 烧 `fsbl.hex`

**验收**：能读出 IDCODE，FSBL 烧录成功无报错。
**坑**：连不上先换线、再换 USB 口、最后才怀疑板子。

### ☐ 周三（2h）第一次出图

- [ ] 接 IMX335 到 `J2`（注意排线方向，别硬插）
- [ ] 屏经 FPC 接核心板 `RGBLCD`
- [ ] 烧 `991` 的 `network-data.hex` + `appli.hex`
- [ ] 跳线拨回 **Flash boot**（B0、B1 接地），重新上电

**验收**：屏亮、能看到摄像头画面。
**如果黑屏**：先只跑 `35_Sensor` 例程验证摄像头和屏，把"图像通路"和"AI 通路"分开排查。

### ☐ 周四（2h）排错 + 出框

- [ ] 画面有了但没有框 → 检查 `network-data.hex` 是否烧进去了
- [ ] 记录 LCD 上显示的推理耗时和帧率

**验收**：**P1 完成**——屏上实时出现人体检测框。

### ☐ 周五（2h）固化流程

- [ ] 把三条烧录命令写成 `.bat`，下次双击即可
- [ ] 记录：跳线位置、loader 文件名、工程路径

**验收**：从零到出框，全程不用查文档。

### ☐ 周六（4h）模型转换（不需要板子）

- [ ] 建 Python 3.9 环境，装齐 1.2 表里的版本
- [ ] 下载 `yolov8n.pt`，改 `exporter.py`：`quant_type="per-channel"`
- [ ] 导出：

```bash
yolo export model=yolov8n.pt format=tflite imgsz=256 int8=True
```

- [ ] 确认生成 `yolov8n_saved_model/yolov8n_integer_quant.tflite`
- [ ] 打开 `Model/generate-n6-model.sh`，把模型路径换成这个 tflite，保持 `--target stm32n6`、`--input-data-type uint8`
- [ ] 运行脚本，生成 `network.c`、`network_ecblobs.h`、`network_data.hex`

**验收**：`stedgeai` 正常结束，报告里没有大量"CPU fallback"的层。

### ☐ 周日（4h）P2 上板

- [ ] 把新生成的 `network.c` / `network_ecblobs.h` 覆盖进工程
- [ ] `app_config.h` 改 `NB_CLASSES 80`（COCO 类别数），类别表按需
- [ ] `POSTPROCESS_TYPE`：输出 float 用 `..._UF`，int8 用 `..._UI`（以 `Middlewares/ai-postprocessing-wrapper/README.md` 为准）
- [ ] 编译 → 烧 `appli.hex` + `network-data.hex` → 上电

**验收**：屏上跑的是 YOLOv8n（不是 tiny_yolo_v2），能检出人。

---

## 4. 第 2 周：P2 收尾 + 数据准备

### ☐ 周一（2h）P2 排错 A

- [ ] 没框 → 后处理类型 / 类别数
- [ ] 框错位 → 预处理 `aspect_ratio`（crop / fit）和训练时不一致

### ☐ 周二（2h）P2 排错 B

- [ ] 编译报 `ll_aton` → 统一 ST Edge AI 版本，或按官方 FAQ 升级
- [ ] 仍不通 → 直接换 ST 仓库里已量化好的 yolov8n tflite，先跑通

### ☐ 周三（2h）测性能

- [ ] 记录 256×256 和 320×320 的推理耗时、帧率
- [ ] 填表：`256 → __ ms / __ fps`，`320 → __ ms / __ fps`

**验收**：**P2 完成**。

### ☐ 周四（2h）定检测内容

- [ ] 写清楚：检测什么、几个类别、目标在画面里占多大、距离多远
- [ ] 过一遍筛子：目标 ≥1/6 画面宽、类别 2~5 个、背景可控、光照稳定

**验收**：一句话能说清"这个模型输入什么、输出什么"。

### ☐ 周五（2h）拍数据

- [ ] 拍 100 张（不同角度/距离/光照，别只拍一个姿势）
- [ ] 按 8:2 分 `images/train`、`images/val`

### ☐ 周六（4h）标注

- [ ] labelImg / labelme / Roboflow 标 100 张
- [ ] 导出 YOLO 格式（`labels/*.txt`）

**验收**：`dataset/` 目录结构完整，能画出框。

### ☐ 周日（4h）训练

```bash
yolo detect train model=yolov8n.pt data=my_dataset.yaml imgsz=256 epochs=100 batch=16 patience=30
```

```yaml
# my_dataset.yaml
path: ./dataset
train: images/train
val: images/val
names:
  0: cat
  1: dog
```

**验收**：有 `best.pt`，验证集 mAP 看着合理，`runs/detect/val/` 里预测图能看。

---

## 5. 第 3 周：P3（自己的类别出框）

### ☐ 周一（2h）量化 + 转换

- [ ] 用 ST 的 `tflite_quant.py` 量化（uint8 输入、per-channel）：

```yaml
model:
    name: yolov8n_256
    uc: od_coco
    model_path: ./yolov8n_saved_model
    input_shape: [256, 256, 3]
quantization:
    quantization_type: per_channel
    quantization_input_type: uint8
    quantization_output_type: float
    calib_dataset_path: ./dataset/images/val   # ← 换自己的图，别用 coco8
    export_path: ./quantized_models
pre_processing:
    rescaling: {scale: 255, offset: 0}
```

- [ ] 跑 `generate-n6-model.sh` 生成新的 `network.c` + `network_data.hex`

### ☐ 周二（2h）首次部署

- [ ] 覆盖 `network.c`，改 `NB_CLASSES` 和类别表
- [ ] 烧 `appli.hex` + `network-data.hex`

**验收**：屏上跑的是自己的模型。

### ☐ 周三（2h）排错

- [ ] 全错检 → 十有八九是量化校准集不匹配，换自己场景的 100 张重量化
- [ ] 一个框都没有 → 置信度阈值太高，降到 0.25 试

### ☐ 周四（2h）调阈值 + 复测

- [ ] 调 `confidence_thresh`、`NMS_thresh`
- [ ] 记录漏检/误检的典型场景

### ☐ 周五（2h）基线

- [ ] 记录：fps、耗时、漏检率、误检率、典型失败场景

### ☐ 周六（4h）扩数据

- [ ] 补到 300 张（重点补失败场景）
- [ ] 重训

### ☐ 周日（4h）验收

- [ ] 重新量化 → 转换 → 部署
- [ ] 复测

**验收**：**P3 完成**——自己的类别在板上实时检出。

---

## 6. 第 4 周：缓冲（别提前排满）

这一周**故意留白**：

- 顺利 → 提前进 P4（连续跑 1 小时看稳定性、断电重启、固定机位、调帧率）
- 卡住 → 就用这周补 P3 的坑

> 业余项目唯一能守住进度的办法不是压缩任务，是**留白**。

---

## 7. 止损规则（写在便签上）

| 卡住的事 | 超过 | 立刻改成 |
|---|---|---|
| 烧录 | 2 h | 烧官方 prebuilt 整包 hex，先证明硬件是好的，别纠结自己编译 |
| 模型转换 | 3 h | 用 ST 仓库里已量化好的 yolov8n，先跑通再回头自己转 |
| P2 出框 | 2 个周末 | 回到 P1 的 tiny_yolo_v2，确认板子没问题，再单独查模型链路 |
| OV5640 出图 | 2 个周末 | **放弃**，改用 IMX335。它是优化项，不是必须项 |

---

## 8. 附录

### A. 从源码构建并烧到外部 Flash（P3 之后才需要）

```bash
STM32_SigningTool_CLI -bin Project.bin -nk -t ssbl -hv 2.3 --align -o Project_sign.bin
STM32_Programmer_CLI -c port=SWD mode=HOTPLUG -el "<loader>.stldr" -hardRst -w Project_sign.bin 0x70100000
```

### B. 常见验收记录表（打印出来手填）

| 日期 | 版本 | 分辨率 | 耗时 | fps | 备注 |
|---|---|---|---|---|---|
| | tiny_yolo_v2 | 224 | | | P1 |
| | yolov8n | 256 | | | P2 |
| | yolov8n | 320 | | | P2 |
| | 自训 v1 | 256 | | | P3 |

### C. OV5640 后续（第 6 周起，可选）

- 硬件：DVP 接 `P7`，必须用 FPC 转接板，**FPC ≤15 cm**
- 难点：AI 工程只有 CSI-2 通路，要自己加"DVP → DCMIPP Pipe0 RGB565 → RGB888 → NPU"
- 参考：AN6211 里有 OV5640 + DCMIPP 并口的 CubeMX 示例（H7S78-DK，思路可借）
- 心理预期：12~25 h，且有 40% 概率卡在"能出图但推理全错"

### D. 参考链接

- 正点原子 DNN647 文档：<https://wiki.alientek.com/docs/Boards/STM32/DNN647/>
- 人体检测实验：<https://wiki.alientek.com/docs/Boards/STM32/DNN647/advanced-examples/ai-people-detection>
- 摄像头实验（IMX335/OV5640 都支持）：<https://wiki.alientek.com/docs/Boards/STM32/DNN647/basic-examples/sensor/>
- ST YOLOv8 量化部署教程：<https://github.com/STMicroelectronics/stm32ai-modelzoo-services/blob/main/object_detection/docs/tuto/How_to_deploy_yolov8_yolov5_object_detection.md>
- ST N6 部署 README：<https://github.com/STMicroelectronics/stm32ai-modelzoo-services/blob/main/object_detection/docs/README_DEPLOYMENT_STM32N6.md>
- ST 官方目标检测工程：<https://github.com/STMicroelectronics/STM32N6-GettingStarted-ObjectDetection>
- AN6211（DCMIPP 并口/CSI-2 说明）：<https://www.st.com/resource/en/application_note/an6211-introduction-to-digital-camera-interface-pixel-pipeline-for-stm32-mcus-stmicroelectronics.pdf>

### E. 许可证提醒

Ultralytics 开源版是 AGPL-3.0。自己和朋友玩没问题；**一旦做成产品对外销售，必须向 Ultralytics 买商业授权**。ST 的教程里有明确声明，别做到最后一步才发现。
