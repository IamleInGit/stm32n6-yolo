# 硬件与接线

## 主控

| 项目 | 参数 |
|---|---|
| 型号 | STM32N647X0H3Q |
| 内核 | Cortex-M55 @ 800 MHz |
| NPU | Neural-ART，600 GOPS |
| 内部 SRAM | 4.2 MB 连续 |
| 图形/多媒体 | NeoChrom GPU、JPEG 编解码、H.264 编码器 |
| 片内 Flash | **无**（必须从外部 NOR 启动） |

## 核心板资源

| 器件 | 容量 | 接口 |
|---|---|---|
| NOR Flash | 32 MB | Octo-SPI / Dual-Quad SPI |
| HyperRAM | 32 MB | HyperBus |
| SD NAND | 16 Gb | 4 bit SD |
| EEPROM | 2 Kb | I2C |

## 底板接口

| 接口 | 用途 | 本项目 |
|---|---|---|
| `J2` | MIPI CSI-2 摄像头 | **主用**，接 MCIMX335 |
| `P7` | DVP 摄像头 | OV5640（P5 阶段才用） |
| `RGBLCD`（核心板） | RGB 屏 | 800×480 4.3"/7" |
| `P6` | BOOT 跳线 | 见 [烧录与 BOOT](03-flashing.md) |
| `TF CARD` | TF 卡 | 照相机例程需要 |
| USB Type-C | 供电 / 串口 / ST-LINK | 用数据线，不用充电线 |

## 采购 / 到货清单

| 状态 | 物料 | 说明 |
|---|---|---|
| ☐ | 正点原子 MCIMX335 | AI 例程唯一支持的摄像头 |
| ☑ | 800×480 RGB 屏 | 第三方同分辨率屏可能因时序不同而花屏 |
| ☑ | OV5640 | 已有，P5 阶段再用 |
| ☐ | TF 卡 ≥8 GB / FAT32 | |
| ☐ | USB-C 数据线 | |
| ☐ | 5V/3A DC 电源（可选） | 摄像头花屏、复位不稳时换它 |

## 供电注意

USB 供电不足会表现为：摄像头出图花屏、烧录中途失败、上电偶发不启动。遇到这类"玄学"问题，先换 DC 供电再排查代码。
