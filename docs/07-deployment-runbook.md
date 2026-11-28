# 部署手册（工具与硬件到位后按此执行）

> 这份文档把前 6 份文档的结论收敛成**可执行动作**。
> 标注体系：
> - ✅ **已验证**：本项目实测过
> - ⚠️ **推断**：有依据但没跑过，第一次执行时要留出排错时间
> - ❓ **未知**：必须现场确认

---

## 0 开始前的检查

| 项 | 要求 | 验证命令 | 依据 |
| :--- | :--- | :--- | :--- |
| STM32CubeIDE | 1.17.0 | `Test-Path "D:\ST\STM32CubeIDE_1.17.0\STM32CubeIDE\stm32cubeide.exe"` | ✅ 版本依据：`.ioc` 是 CubeMX 6.13.0 生成 |
| STM32CubeProgrammer | ≥ 2.18.0 | `STM32_Programmer_CLI --version` | ⚠️ |
| 外部 Flash 加载器 | 3 个 `.stldr` 已放入 `ExternalLoader\` | 见 `02-env-setup.md` §3 | ✅ |
| **外部 Flash 型号** | BY25FQ128EL / DUAL / MX25UM25645G | 见 `03-n6-deploy-notes.md` §1.3 | ❓ **必须先确认** |
| ST Edge AI Core | 2.0.0 | `D:\ST\STEdgeAI\2.0\Utilities\windows\stedgeai.exe --version` | ⚠️ 必须与包内 `ll_aton` 配套 |
| 摄像头 | IMX335 | — | ❓ |

**没有 Flash 型号就别往下走**——选错 FSBL 会导致上电不启动。

---

## 1 阶段 0b：硬件自检（`352_IMX335`）

**目的**：把"板子好、屏好、摄像头好、工具链好"四件事一次钉死。这一步不碰 AI。

1. BOOT 开关拨到 **Development（从 RAM 启动）**
2. CubeIDE 打开 `Projects\35_Sensor\352_IMX335\STM32CubeIDE\Appli`
3. 构建配置选 **Debug**（`STM32N647X0HXQ_LRUN_RAMxspi1.ld`）
4. Build → Debug → Run
5. 预期：屏上出现 IMX335 实时画面 + `IMX335 TEST / ATOM@ALIENTEK`

| 现象 | 判据 | 下一步 |
| :--- | :--- | :--- |
| 编译报 `undefined reference to HAL_*` | 工程被拷出过 `SoftwarePackage` | 见 `02-env-setup.md` §5.1 |
| 屏全黑但串口有输出 | LTDC 时序或屏型号不对 | 对照正点原子教程的屏参数 |
| 花屏 / 抖动 | 摄像头排线或 PCLK 过高 | 降 XSPI 时钟试 |
| 串口报 I2C 错误 | IMX335 未识别 | 查模块接口与供电 |

**通过后，硬件层面的怀疑可以全部排除。**

---

## 2 阶段 0c：跑通 991 预编译（验证 NPU）

**目的**：确认 NPU、权重加载、后处理、显示四者全通。用现成二进制，不需要 STEdgeAI。

### 2.1 烧录（顺序不能错）

```powershell
$bin = "D:\ST\STM32CubeProgrammer\bin"
$el  = "$bin\ExternalLoader\<你的型号>_ATK-CNN647B_ExtMemLoader.stldr"
$src = "D:\STM32N6\SoftwarePackage\Projects\99_Applications\991_AI_People_Detection\Binary"

# 1) FSBL（有 STM2 签名头，✅ 已验证）
& "$bin\STM32_Programmer_CLI.exe" -c port=SWD mode=HOTPLUG -el $el -hardRst -w "$src\fsbl-<型号>_w958d8nbya5i.hex"

# 2) 权重 → 0x70200000（30 MB，慢，只需一次；✅ 地址已从 hex 实测）
& "$bin\STM32_Programmer_CLI.exe" -c port=SWD mode=HOTPLUG -el $el -hardRst -w "$src\network-data.hex"

# 3) 应用（⚠️ 未签名，二进制实测无 STM2 头）
& "$bin\STM32_Programmer_CLI.exe" -c port=SWD mode=HOTPLUG -el $el -hardRst -w "$src\appli.hex"
```

> **权重先于应用**不是讲究：`network.c` 里的权重池是绝对地址 `0x70200000`，
> 与 Debug/Release 无关。哪怕只在 RAM 里调试，权重也必须先在 Flash 里。

### 2.2 启动

BOOT 拨到 **Boot from Flash** → 上电 → 人站到镜头前。

| 现象 | 判据 | 下一步 |
| :--- | :--- | :--- |
| 屏亮但无框 | 权重没烧进去，或读到空白 Flash | 重烧 `network-data.hex`，核对结束地址 `0x70C8D411` |
| 完全不启动 | FSBL 型号不对 | 换另一个 `fsbl-*.hex` 重试 |
| 启动但 HardFault | 应用未签名/被校验 | 自己签一次（见 `03-n6-deploy-notes.md` §1.1） |
| 有框但位置错乱 | 后处理常数与模型不匹配 | 见阶段 4 的常数清单 |

**这一步过了，NPU 通路就证明了。** 之后所有问题都只可能在"模型"或"后处理常数"上。

---

## 3 阶段 4：换成自己的模型

现在有个**必须先回答的问题**：ST 的 `od_yolov8_pp_if.h` 吃原始头还是已解码输出？

- 打开 `Middlewares\STM32_VISION_MODELS_PP\od_yolov8_pp_if.h` 和 `app_postprocess.c`，
  看它读取的输出张量形状——**这一步会直接决定走 A 还是 B**。

### 3.1 路线 A：保留解码（推荐先试）

用 `best_int8_nonconv.onnx`：体积 3.34 MB、mAP50 0.547（✅ 已验证）、
输出 `[1, 5, 1029]`、**输出 buffer 仅 20,580 字节**。

```bash
# 在 Model 目录下（路径参照 generate-n6-model.sh）
stedgeai generate --no-inputs-allocation --no-outputs-allocation \
    --model best_int8_nonconv.onnx --target stm32n6 \
    --st-neural-art default@user_neuralart.json
cp st_ai_output/network_ecblobs.h .
cp st_ai_output/network.c .
cp st_ai_output/network_atonbuf.xSPI2.raw network_data.xSPI2.bin
arm-none-eabi-objcopy -I binary network_data.xSPI2.bin \
    --change-addresses 0x70200000 -O ihex ../Binary/network-data.hex
```

> `--model` 换成 ONNX 是 ⚠️ 推断：ALIENTEK 脚本用的是 `.tflite`，
> 但 ST 的 ModelZoo 流程确实把 `_quant_qdq_pc.onnx` 直接喂给 `stedgeai`。
> 如果报格式不支持，就用 ModelZoo 先转成 TFLite。

### 3.2 路线 B：截断到卷积头

用 `best_head_int8.onnx`：体积 3.31 MB、全 int8 无 float 例外（✅ 已验证，框偏移 0.43 px）。
**但输出 buffer 是 267,540 字节**（`[1,64,1029]` + `[1,1,1029]`），
在 2 MB SRAM / 1.75 MB NPU 池的板子上要先算清楚放不放得下。

解码由 `src/yolo_v8_post.c` 负责（✅ 已与 ultralytics 逐位对齐）。

### 3.3 必须同步修改的常数（漏一个框就歪）

| # | 文件 | 宏 | 现值 | 改成 |
| :-- | :--- | :--- | :--- | :--- |
| 1 | `Model\network.c` 等 | — | 整个替换 | `stedgeai` 新生成 |
| 2 | `Binary\network-data.hex` | — | 旧权重 | 重新 objcopy |
| 3 | `Appli\Core\Inc\app_config.h` | `NN_WIDTH/HEIGHT` | 224 | 224（一致，可不动） |
| 4 | 同上 | `NN_CLASSES` | 2 | **1** |
| 5 | 同上 | `NN_CLASSES_TABLE` | `{"person","not_person"}` | `{"person"}` |
| 6 | 同上 | `NN_BUFFER_OUT_SIZE` | 5880 | 路线 A：**20580**；路线 B：267540 |
| 7 | 同上 | `POSTPROCESS_TYPE` | `OD_YOLO_V2_UF` | YOLOv8 对应类型（见 PP 库头文件） |
| 8 | `Appli\Core\Inc\postprocess_conf.h` | `AI_OBJDETECT_YOLOV2_PP_*` | 7×7 / 5 / 1 | YOLOv8 的宏（`AI_OBJDETECT_YOLOV8_PP_*`） |
| 9 | `Model\user_neuralart.json` | `memory_pool` / `options` | — | **保持原样**（见 `03` 文档 §4） |

关键换算（`03-n6-deploy-notes.md` §3）：
`NN_BUFFER_OUT_SIZE = 网格² × 5 × (5 + 类数) × 4`，224 / 1 类 = `1029 × 5 × 4 = 20580`。

### 3.4 路线 B 的接线

```c
/* app.c 里，NPU 推理完成后 */
extern int yolo_v8_postprocess(...);
static yolo_det_t cand[512], dets[64];
int n = yolo_v8_postprocess(box_logits, cls_logits, 224, 1,
                            0.25f, 0.45f, 64, cand, 512, dets, 64);
/* 然后用 app_lcd.c 的画框接口把 dets[] 画到 L1 层 */
```

把 `src\yolo_v8_post.c`、`src\yolo_v8_decode.c`、`src\yolo_v8_nms.c` 加入工程源目录
（CubeIDE：右键工程 → Properties → C/C++ General → Paths and Symbols → Source Location 添加）。

---

## 4 编译与烧录（阶段 4 完成动作）

1. CubeIDE 构建配置选 **Release**（`STM32N647X0HXQ_ROMxspi2_RAMxspi1.ld`，XIP 于 0x70100000）
2. Build → 生成 `Project.bin`
3. 签名（⚠️ CubeProgrammer ≥ 2.21 需要 `--align`）：

```powershell
& "$bin\STM32_SigningTool_CLI.exe" -bin Project.bin -nk -t ssbl -hv 2.3 --align -o Project_sign.bin
```

4. 烧到 `0x70100000`：

```powershell
& "$bin\STM32_Programmer_CLI.exe" -c port=SWD mode=HOTPLUG -el $el -hardRst -w Project_sign.bin 0x70100000
```

5. BOOT 拨到 **Boot from Flash** → 上电

**应用区只有 1 MB**（`0x70100000` ~ `0x70200000`），当前 179.5 KB，空间充裕。

---

## 5 实测（阶段 5 的输入）

| 指标 | 怎么测 | 现状 |
| :--- | :--- | :--- |
| 帧率 | 串口打印每帧时间戳；或数 1 分钟内的框更新次数 | 待测 |
| NPU 单帧耗时 | `stedgeai` report 的推断值 + 串口实测对照 | 待测 |
| CPU 占用 | 991 自带 `app_cpuload.c`，直接看 | 现成 |
| 后处理耗时 | 用 `test_post.exe` 的主机值 × M55/x86 倍率粗估，最终以板上为准 | 主机 0.013 ms @224 |
| SRAM 峰值 | 链接脚本的 `.map` 里看最紧的段 | 待测 |
| 功耗 | 万用表串在供电；对比空闲/推理 | 待测 |

**已知的板端预算**（`03-n6-deploy-notes.md` §2）：

- 片内 SRAM 约 2 MB，其中 NPU 激活池 1.75 MB（AXISRAM3-6）
- 权重池 11 MB 占外部 Flash 65.9%，我们的模型只要 3.3 MB，空间充足

---

## 6 回滚

任何一步失败，回到已知可用状态：

```powershell
# 恢复官方 demo
& "$bin\STM32_Programmer_CLI.exe" -c port=SWD mode=HOTPLUG -el $el -hardRst -w "$src\fsbl-<型号>.hex"
& "$bin\STM32_Programmer_CLI.exe" -c port=SWD mode=HOTPLUG -el $el -hardRst -w "$src\network-data.hex"
& "$bin\STM32_Programmer_CLI.exe" -c port=SWD mode=HOTPLUG -el $el -hardRst -w "$src\appli.hex"
```

模型文件全部在 `D:\STM32N6\yolo-baseline\runs\person224\weights\`，仓库里没有大文件。

---

## 7 一页变更清单（改了什么，出问题回哪里）

| 文件 | 来源 | 回退方式 |
| :--- | :--- | :--- |
| `Model\network.c`、`network_ecblobs.h` | `stedgeai` 生成 | 用软件包原文件覆盖 |
| `Model\network_data.xSPI2.bin` | `stedgeai` 生成 | 同上 |
| `Binary\network-data.hex` | objcopy | 同上 |
| `Appli\Core\Inc\app_config.h` | 手工改 | git diff / 原件备份 |
| `Appli\Core\Inc\postprocess_conf.h` | 手工改 | 同上 |
| `Appli\Core\Src\*.c` | 接入后处理 | 同上 |
| `src\yolo_v8_*.c` | 本仓库 | 无需回退，纯新增 |

> **动手前先备份 `991_AI_People_Detection` 整个目录**。
> 软件包可以重新下载，但正点原子那份包不一定还拿得到同一个版本。

---

## 8 4.1 路线实际执行记录（2026-11-28）

STEdgeAI 2.0 的下载被登录墙卡死后，改走 4.1 + 升级 runtime。以下是实际踩到的点，按遇到顺序。

### 8.1 生成命令（与 2.0 的差别）

```powershell
stedgeai generate --no-inputs-allocation --no-outputs-allocation `
    --model best_int8_signed.onnx --target stm32n6 `
    --st-neural-art default@user_neuralart.json `
    --input-data-type uint8 --output-data-type float32
```

两个新增参数很关键：`--input-data-type uint8` 让输入直接对齐 DCMIPP 的 RGB888。

### 8.2 量化必须用有符号 int8

```
NOT IMPLEMENTED: Onnx exporting model with quantized unsigned integer format is not supported
```

ST 的转换器**只接受 int8（有符号）**的量化 ONNX。用 `QUInt8` 激活会被拒。
重新用 `QInt8` 量化后精度反而略好（mAP50 0.551 vs 0.547）。

### 8.3 runtime 升级不是"覆盖一个文件夹"

| 改动 | 说明 |
| :--- | :--- |
| `Middlewares\AI\Npu\ll_aton\` | 用 4.1 的覆盖（`v1.0.0-rc0-16` → `v1.1.5-11`） |
| `Middlewares\AI\Npu\Devices\STM32N6XX\` | **也要覆盖**，新版 `ll_aton_platform.h` 依赖新的 `ATON.h` |
| `NetworkRuntime1000_CM55_GCC.a` | 用 `NetworkRuntime1210_CM55_GCC.a` 覆盖，**保持文件名不变**，工程无需改 |

### 8.4 三处 API 不兼容

| 现象 | 修法 |
| :--- | :--- |
| `LL_ATON_*_Default` 找不到 | 生成时默认名是 `network`，把 `app.c` 里 6 处 `_Default` 改成 `_network`（`--name Default` 生成的是小写 `_default`，仍不匹配） |
| `npu_cache_init` undefined | 新版改成 `npu_cache_enable_clocks_and_reset()` |
| `HAL_CACHEAXI_MspInit` 重复定义 | 把 `npu_cache.c` 里那两个函数改成 `__attribute__((weak))` |

### 8.5 ★ 两个布局陷阱（最花时间的地方）

从 `st_ai_output\network_c_info.json` 的 `buffers` 里读出的权威布局：

| buffer | 形状 | 布局 | 影响 |
| :--- | :--- | :--- | :--- |
| 输入 `Input_2_out_0` | `[1,3,224,224]` | **channel_first** | 必须把 DCMIPP 的**交错 RGB** 转成**平面 RRR…GGG…BBB** 再喂 |
| 输出 `Concat_815_out_0` | `[1,5,1029]` | **channel_first** | `raw[c*1029 + i]`，不是 `raw[i*5 + c]` |

**报错现象很有迷惑性**：

- 输入不转：模型看到噪声，满屏假框，但框的位置"看着合理"
- 输出索引错：读到的"置信度"是坐标值，框上显示 **38.70、218.43** 这种大于 1 的数

> **教训**：报告里的 `oshape` 写的是 `[b:1,h:224,w:224,c:3]`（NHWC 风格），
> 但运行时真正用的是 `network_c_info.json` 里的 `channel_first` 字段。
> **以 c_info.json 为准，不要信 report 的 oshape。**

### 8.6 实测结果

```
Inference  96 ms      （YOLOv8n 224 int8，含 150 KB 输入转置）
FPS        10.00
Peoples    0~5（视场景）
置信度      0.64~0.77
```

对比出厂 demo（TinyYOLOv2）：**225 ms → 96 ms**，快 2.3 倍，且模型换成了 YOLOv8n。
