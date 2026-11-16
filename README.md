# STM32N6 + YOLO：在 MCU 上跑目标检测

> 学习记录 · 2026-11 起 · 🚧 进行中

[中文](#中文) · [English](#english)

---

## 中文

把 YOLO 目标检测模型训练好、量化压缩，部署到 STM32N6 的 NPU 上，测出真实的帧率和功耗。

**这不是产品，是学习过程。** 代码边学边加，所以这个仓库的提交历史本身就是进度条。

### 为什么做

- 在 MCU 上跑视觉模型，是这两年少有的「能把嵌入式经验用上新地方」的方向
- 我熟悉寄存器、时钟、DMA 这一层，缺的是模型训练和量化那一半
- 想把「能跑」和「跑得好」之间的差距，用实测数据量出来

### 路线图

| 阶段 | 内容 | 状态 |
| :--- | :--- | :--- |
| 0. 环境 | 开发板、工具链、ST Edge AI 跑通 | 🚧 PC 侧就绪，ST 工具待装 |
| 1. 基线 | PC 上跑通 YOLO 推理，固定数据集与指标 | ✅ mAP50 0.575 |
| 2. 量化 | INT8 量化，量出精度损失 | ✅ 3.34 MB，mAP50 0.547 |
| 3. 部署 | 模型转换、烧录，在板子上跑出第一帧结果 | 🚧 模型与后处理侧完成，待 STEdgeAI |
| 4. 实测 | 帧率、内存占用、功耗 | ⬜ 待硬件 |
| 5. 优化 | 分辨率、算子替换、双缓冲 | 🚧 后处理已优化 44×，板端待测 |

拆解和验收标准见 [docs/00-roadmap.md](docs/00-roadmap.md)，当前进展与交接见 [docs/08-handoff.md](docs/08-handoff.md)。

### 目录

```
src/        固件代码
notebooks/  训练、量化、评估脚本
models/     模型产物（大文件不入库）
docs/       路线图与学习笔记
assets/     图片、波形、实测截图
```

### 环境

安装步骤、验收命令与踩坑记录见 [docs/02-env-setup.md](docs/02-env-setup.md)。每跑通一步，把版本号、命令、坑记进 `docs/`。

| 组件 | 版本 |
| :--- | :--- |
| 开发板 | 正点原子 ATK-CNN647B（STM32N647X0HxQ） |
| 摄像头 | IMX335（在途） |
| STM32CubeIDE | 1.17.0 |
| STM32CubeProgrammer | 2.18.0 |
| ST Edge AI Core | 4.0.0（待装） |
| Python | 3.12.16（uv，已装于 `D:\STM32N6\py\yolo312`；系统自带 3.14 工具链不支持） |

### 说明

个人学习项目，不保证工程质量，也不保证能直接用在产品上。

---

## English

Train a YOLO detector, quantize it, and deploy it to the NPU on an STM32N6 — then measure the real frame rate and power draw.

**This is a learning log, not a product.** Code is added as I go, so the commit history itself is the progress bar.

### Roadmap

| Phase | Content | Status |
| :--- | :--- | :--- |
| 0. Setup | Board, toolchain, ST Edge AI working | ⬜ |
| 1. Baseline | YOLO inference on PC, fixed dataset and metrics | ⬜ |
| 2. Quantize | INT8 quantization, measure accuracy loss | ⬜ |
| 3. Deploy | Convert the model, flash it, get the first frame | ⬜ |
| 4. Measure | Frame rate, memory footprint, power | ⬜ |
| 5. Optimize | Resolution, operator replacement, double buffering | ⬜ |

Details and acceptance criteria: [docs/00-roadmap.md](docs/00-roadmap.md).

### Layout

```
src/        firmware
notebooks/  training, quantization, evaluation scripts
models/     model artifacts (large files are not committed)
docs/       roadmap and study notes
assets/     images, waveforms, measurements
```
