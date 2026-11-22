# 资产盘点

> 盘点时间：2026-11-16 · 对象：`D:\STM32N6\SoftwarePackage`（正点原子 N647 官方包）

**一句话结论**：硬件和固件底座基本齐了，缺的只是 PC 侧工具链。
而且板级 AI 例程**已经存在**（`991_AI_People_Detection`），不需要从 ST 官方 N6570-DK 工程硬改。

---

## 1 硬件

| 项目 | 状态 | 事实 |
| :--- | :--- | :--- |
| 开发板 | ✅ 已有 | 正点原子 **ATK-CNN647B** |
| MCU | ✅ | **STM32N647X0HxQ**，Cortex-M55 + Neural-ART NPU |
| 片内 Flash | ⚠️ **没有** | N6 系列无片内 Flash，代码必须放外部 NOR 或加载进 RAM |
| 外部 NOR Flash | ❓ 待确认 | 三选一，见 §5，**选错就起不来** |
| IMX335 摄像头 | ✅ **已到货**（2026-11-22） | 包内两套驱动都已就绪，见 §4 |
| 800×480 RGB LCD | ❓ 待确认 | LTDC 双层：L0 视频层 + L1 叠加层（框/字画在 L1） |
| 调试器 | ❓ 待确认 | 板载还是外置 ST-LINK，决定驱动安装方式 |
| HyperRAM | ✅ 板上 | 映射在 `0x91000000`，16 MB，可当大 buffer 用 |

链接脚本实测值（`STM32N647X0HXQ_LRUN_RAMxspi1.ld`）：

```
RAM    (xrw) : ORIGIN = 0x34000400, LENGTH = 2047K     # 片内 SRAM，约 2 MB
EXTRAM (rw)  : ORIGIN = 0x91000000, LENGTH = 16M       # 外部 HyperRAM
```

> ⚠️ 这 2 MB 是整个项目最硬的约束。文章里 34 FPS / 29 ms 是 **STM32N6570-DK** 的成绩，
> 不能直接套到 N647 上。任何"能不能跑 256×256"的问题，都要看 `stedgeai` 的 report，不要靠猜。

---

## 2 软件包地图

```
D:\STM32N6\SoftwarePackage\
├─ STM32Cube_FW_N6_V1.0.0\          # ST HAL 库。工程用 PARENT-x 相对路径引用，整个包不能拆开挪
├─ Drivers\BSP\                      # 正点原子板级驱动
│    LED UART RGBLCD IMX335 HyperRAM SYS BUS LCD ...
├─ Middlewares\
│  ├─ AI\                            # ★ 推理运行时
│  │   ├─ Lib\GCC\ARMCortexM55\NetworkRuntime1000_CM55_GCC.a   962 KB
│  │   ├─ Npu\ll_aton\               # NPU 驱动 + cache 维护（ll_aton_n64.c）
│  │   └─ Inc\stai.h stai_events.h ...
│  ├─ STM32_MW_CAMERA\               # ★ ST 摄像头中间件；sensors\ = imx335 / vd55g1 / vd6g
│  ├─ STM32_MW_ISP\                  # ISP 管线（evision）
│  ├─ STM32_VISION_MODELS_PP\        # ★ 后处理库：od_yolov2 / od_yolov5 / od_yolov8 /
│  │                                 #   od_ssd / od_st_yolox / iseg_yolov8 / mpe / spe
│  ├─ STM32_IMAGE_PROCESSING_LIBRARY\
│  └─ THREADX\ NETXDUO\ USBX\ FATFS\ MALLOC\ ...
├─ FSBL\                             # 3 种外部 Flash 的 FSBL 工程（+ 预编译 hex）
├─ External_Loader\                  # ★ ATK 专用 .stldr（已预编译好，直接拷进 CubeProgrammer）
└─ Projects\                         # 01~63 例程 + 99_Applications
```

---

## 3 要用的四个例程

| 路径 | 内容 | 用途 |
| :--- | :--- | :--- |
| `Projects\35_Sensor\352_IMX335` | 裸机：IMX335 → RGBLCD 显示 | **阶段 0b 的靶子**：验证工具链 + 板 + 屏 + 摄像头，不含 AI |
| `Projects\99_Applications\991_AI_People_Detection` | ThreadX + 双 DCMIPP + NPU + LCD | **核心参考，见 §4** |
| `Projects\43_Camera` | 拍照存 SD（FATFS） | 后续存检测结果图 |
| `Projects\14_TFTLCD` / `15_RGBLCD` | 显示基础 | 画框/画字 API 来源 |

其余 63 个例程是外设教材，本阶段用不到，但 `13_MPU`、`19_DMA`、`36_Memory_Management` 在调内存时值得回看。

---

## 4 核心发现：`991` 是移植好的答案

`991_AI_People_Detection` 是 ST 官方
[GettingStarted_ObjectDetection](https://github.com/STMicroelectronics/STM32N6-GettingStarted-ObjectDetection)
的 ATK 板移植版，文件名与 ST 工程一一对应：

| 文件 | 职责 |
| :--- | :--- |
| `Appli\Core\Src\app.c` | 主编排：ThreadX 任务、buffer 轮转、NPU 推理、绘制 |
| `Appli\Core\Src\app_camera.c` | 双 DCMIPP 管线配置 |
| `Appli\Core\Src\app_postprocess.c` | YOLOv2 解码 + NMS + 框坐标映射 |
| `Appli\Core\Src\app_lcd.c` | LTDC 双层合成 |
| `Appli\Core\Src\app_bqueue.c` | 双缓冲队列 |
| `Appli\Core\Src\app_cpuload.c` | CPU 占用统计 |

### 4.1 数据流

```
IMX335 ──► DCMIPP PIPE1 ──► LTDC L0（实时画面，800×480）
              │
              └► PIPE2 ──► 裁剪/缩放 224×224 RGB888 ──► Neural-ART NPU
                                                            │
                                            YOLOv2 后处理 ◄─┘
                                                  │
                                            LTDC L1（画框 + 类别 + 置信度）
```

### 4.2 已确认参数（`Appli\Core\Inc\app_config.h`）

| 宏 | 值 |
| :--- | :--- |
| `NN_WIDTH` / `NN_HEIGHT` | 224 / 224 |
| `NN_FORMAT` | `DCMIPP_PIXEL_PACKER_FORMAT_RGB888_YUV444_1` |
| `NN_CLASSES` | 2：`{"person", "not_person"}` |
| `POSTPROCESS_TYPE` | `POSTPROCESS_OD_YOLO_V2_UF` |
| 置信度 / IoU / 最大框数 | 0.6f / 0.3f / 10 |
| `LCD_BG_WIDTH` × `HEIGHT` | 800 × 480 |
| `BQUEUE_MAX_BUFFERS` | 2 |
| 摄像头 sensor 选择 | `cmw_camera_conf.h` 里 `#define USE_IMX335_SENSOR` ✅ |

### 4.3 模型与权重

- 模型文件：`Model\tiny_yolo_v2_224_int8.tflite`（10.8 MB）
- **权重存放位置：外部 Flash `XSPI2` 映射地址 `0x70200000`**（片内只有 2 MB，放不下）
- 预编译产物已经齐全，**不装任何 AI 工具链也能先跑通**：

  | 文件 | 大小 | 用途 |
  | :--- | :--- | :--- |
  | `Binary\appli.hex` | 505 KB | 应用程序 |
  | `Binary\network-data.hex` | 30.4 MB | 权重（一次性烧录） |
  | `Binary\fsbl-*.hex` | 79 KB ×3 | 三种 Flash 变体的 FSBL |

- 模型生成命令（`Model\generate-n6-model.sh`，阶段 3 直接复用）：

  ```bash
  stedgeai generate --no-inputs-allocation --no-outputs-allocation \
      --model tiny_yolo_v2_224_int8.tflite --target stm32n6 \
      --st-neural-art default@user_neuralart.json
  cp st_ai_output/network_ecblobs.h .
  cp st_ai_output/network.c .
  cp st_ai_output/network_atonbuf.xSPI2.raw network_data.xSPI2.bin
  arm-none-eabi-objcopy -I binary network_data.xSPI2.bin \
      --change-addresses 0x70200000 -O ihex ../Binary/network-data.hex
  ```

> 这段脚本把"模型 → C 代码 + 外部 Flash 权重镜像"的完整动作写死了，
> 包括 `--no-inputs-allocation --no-outputs-allocation` 和 `user_neuralart.json` 这两个容易漏的开关。

---

## 5 外部 Flash 三选一（**必须先确认**）

`FSBL\` 和 `External_Loader\` 各有三套，必须与板上实际芯片对应：

| Flash 型号 | 容量 | FSBL | 加载器 |
| :--- | :--- | :--- | :--- |
| `BY25FQ128EL` | 16 MB | `fsbl-by25fq128el_w958d8nbya5i.hex` | `BY25FQ128EL_ATK-CNN647B_ExtMemLoader.stldr` |
| `DUAL_BY25FQ128EL` | 2×16 MB | `fsbl-dual_by25fq128el_w958d8nbya5i.hex` | `DUAL_BY25FQ128EL_ATK-CNN647B_ExtMemLoader.stldr` |
| `MX25UM25645G` | 32 MB | `fsbl-mx25um25645g_w958d8nbya5i.hex` | `MX25UM25645G_ATK-CNN647B_ExtMemLoader.stldr` |

**确认方法（任选）**：看板上 Flash 丝印 / 查正点原子 N647 教程 / 在 CubeProgrammer 里逐个试加载器读 ID。

> 三个 `.stldr` 都是**预编译好的**，不需要在 CubeIDE 里自己建加载器工程。
> 拷进 `<CubeProgrammer>\bin\ExternalLoader\` 即可（见 `02-env-setup.md` §3）。

### 5.1 已实测：16 MB 就够

用 `tools/ihex_info.py` 解析了三个镜像的实际地址范围：

| 镜像 | 起始 | 结束 | 载荷 |
| :--- | :--- | :--- | ---: |
| FSBL | `0x70000000` | `0x70007080` | 28.1 KB |
| appli | `0x70100400` | `0x7012D200` | 179.5 KB |
| network-data（权重） | `0x70200000` | `0x70C8D411` | 10.6 MB |

在 16 MB Flash（`0x70000000` ~ `0x71000000`）里**占 65.9%，还剩 3.4 MB**。
所以 `BY25FQ128EL` 就足够，`MX25UM25645G`（32 MB）不是必需。

另外一个值得留意的差异：`fsbl` 有 `STM2` 签名头，**`appli.hex` 没有**（是裸 ARM 向量表）。
如果烧完不启动，先怀疑签名。完整地图与签名细节见 [`03-n6-deploy-notes.md`](03-n6-deploy-notes.md)。

---

## 6 本机工具链实测（2026-11-16）

| 工具 | 状态 | 判定 |
| :--- | :--- | :--- |
| Python | ✅ 3.14.6（`C:\Python314`） | ⚠️ **太新**：ultralytics / STEdgeAI / ModelZoo 均不支持，需另装 3.12 |
| pip | ✅ 26.1.2 | 可用 |
| Git | ✅ 2.55.0 | 可用（仓库已初始化并有 remote） |
| Java | ✅ 1.8.0_511 | 够用 |
| Node.js | ✅ v24.18.0 | 本项目不需要 |
| CMake | ❌ | CubeIDE 路线不需要；只有走 Makefile 才要 |
| arm-none-eabi-gcc | ❌ | CubeIDE 自带，不用单独装 |
| STM32CubeIDE | ✅ **1.17.0**（装于 `D:\ST`） | 2026-11-22 装好，`352_IMX335` 编译 0 error |
| STM32CubeProgrammer | ✅ **2.22.0**（装于 `D:\ST`） | ≥2.21，签名要加 `--align` |
| ST Edge AI Core | ❌ | 阶段 3 才需要，可延后 |
| ST-LINK Utility | ✅ 已装（x86） | 老工具，**不支持 N6，别用** |

---

## 7 差距清单

**必需（阶段 0）**

1. STM32CubeIDE **1.17.0**
   —— `991` 的 `.ioc` 由 **CubeMX 6.13.0** 生成，CubeIDE 1.17.0 自带 6.13.0，版本对齐可避免工程迁移
2. STM32CubeProgrammer **2.18.0 或更新**
3. ST-LINK 驱动（安装时勾选）
4. 外部 Flash 型号结论

**阶段 2~3 才需要**

5. ST Edge AI Core **2.0.0**（`network.c` 第 29 行写着 `STEdgeAI/2.0`，第 51 行要求
   `ll_aton 1.0.0-dev16`；用别的版本会报 `Possible mismatch in ll_aton library used`）
6. 独立 Python **3.12** 环境
7. （可选）`stm32ai-modelzoo-services` 仓库、CMake + Ninja

**资料**

8. 正点原子 N647 教程/视频：烧录开关位置、Flash 型号、屏接线、IMX335 模块接口
9. Ultralytics 代码为 **AGPL-3.0**，商用需单独授权

---

## 8 对 `00-roadmap.md` 的修正建议

原路线图是按"训练 → 量化 → 部署"排的，但落地时缺了**板级 bring-up** 这一段，
而它恰恰是最容易卡住的地方。建议阶段 0 拆成三小步：

| 子步 | 动作 | 验收 | 依赖 |
| :--- | :--- | :--- | :--- |
| **0a** 工具链 | 装 CubeIDE + CubeProgrammer + 加载器 | `352_IMX335` 编译 0 error | 无 |
| **0b** 硬件自检 | 烧 `352_IMX335`，摄像头 → 屏 | 画面连续、无撕裂 | IMX335 到货 |
| **0c** AI 通路 | 烧 `991` 预编译产物 | 屏上出现人体检测框 | Flash 型号确认 |

0c 通过后，NPU、权重加载、后处理、显示四者全通，
后面任何异常都不必再怀疑硬件——这是整个项目最大的"信心锚点"。

另外两点修正：

- **阶段 3 不必从零搭**：`991` 就是部署骨架，换模型时只动 `Model\` + `POSTPROCESS_TYPE` + 类别表
- **内存预期要下调**：N647 片内 SRAM 2 MB，官方 34 FPS 属于 N6570-DK 数据，
  阶段 4 的实测值才是本项目的真实基线
