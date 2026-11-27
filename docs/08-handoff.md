# 交接摘要（2026-11-16）

## 一句话状态

**模型侧已闭环、可交付；板端 0a–0c 全部打通。**

**P1 达成**：屏上实时出现人体检测框——摄像头、LCD、NPU、后处理、权重加载全部打通。
2026-11-22 先跑通出厂固件；**2026-11-27 自己烧录 991 的 fsbl / network-data / appli 三条 hex 并验证通过**（不再是出厂固件）。
（模型为 1 类 `person` 检测；**不是** YOLOv8n，也还不是我们自己训的模型。）

**烧录链路闭环（2026-11-25）**：用 CubeProgrammer 把 991 的三条 hex 写进外部 Flash，
切回 Flash boot 后正常启动，屏上显示 `Inference 225 ms / FPS 4.29 / Persons 3`。
**这是第一次跑"我们自己烧进去的固件"**，端到端工具链验证完毕。

> 出厂固件已整片备份：`D:\STM32N6\backup\atk-factory-16MB.bin`
> SHA256 `1242B6AA15B6AF1A5BAD4DA7AEF2462F8DDDC66BFE8E4CF4015C4D83684AE8A2`

> ⚠️ **待查的性能疑点**：`Inference 225 ms / FPS 4.29` 对 224 输入的 TinyYOLOv2 来说偏慢。
> 首发怀疑是时钟没跑满，或瓶颈在 DCMIPP→LTDC 而非 NPU。留到阶段 5 第一个查。

2026-11-22 外部条件全部落地：

| 原阻塞项 | 现状 |
| :--- | :--- |
| ST 工具链 | ✅ CubeIDE 1.17.0 + CubeProgrammer 2.22.0（`D:\ST`） |
| 外部 Flash 型号 | ✅ **BY25FQ128EL（16 MB）**，读 `0x70000000` 得 `STM2` 头 |
| IMX335 | ✅ 已到货并点亮 |
| 烧录/启动 | ✅ 出厂固件完整，Flash boot 正常启动 |
| **新增问题** | ⚠️ 板载 ST-LINK 是兼容芯片（FW `V2J35S7`），**CubeIDE 的 GDB server 拒绝启动**；改用 CubeProgrammer CLI 烧 Flash 绕开 |

---

## 已完成（每条都有实测证据）

| 项 | 结果 | 证据位置 |
| :--- | :--- | :--- |
| PC 侧环境 | Python 3.12.16 + torch 2.15.0+cpu + ultralytics 8.4.215 + onnx 1.23.2 | `02-env-setup.md` §6.2 |
| 主机 C 编译器 | zig 0.17.1（走 PyPI，1 分 16 秒装好） | `02-env-setup.md` §8 |
| 单类基线 | **mAP50 0.575 / mAP50-95 0.340**（61 张图，224） | `04-baseline-pipeline.md` |
| int8 量化 | 12.04 → **3.34 MB**，mAP50 **0.547**（只排 24 个无权重解码节点） | `05-quantization.md` §0 |
| 量化掉点根因 | anchor 解码 + DFL 路径，**不是**数据量、**不是**校准策略 | `05-quantization.md` §3 |
| 截断到卷积头 | 3.31 MB，全 int8 无 float 例外，框偏移 **0.433 px** | `05-quantization.md` §8 |
| C 解码 | 与 numpy 参考最大差 **6.1e-5** | `06-firmware-decode.md` §2 |
| C NMS | 与 ultralytics **逐框等价**（60/60、861/861，IoU 1.00000） | `06-firmware-decode.md` §7.2 |
| 融合后处理 | 与两步法**逐位一致**，主机端 **44~59× 加速** | `06-firmware-decode.md` §9 |
| 多分辨率 | 224/320/416 全部逐位一致，无硬编码 | `06-firmware-decode.md` §10 |
| 部署方案 | 两条路线 + 9 处常数清单 + 命令 | `07-deployment-runbook.md` |

---

## 未完成与原因

| 目标 | 状态 | 卡在哪 |
| :--- | :--- | :--- |
| ① 环境 | 🚧 一半 | CubeIDE / CubeProgrammer 需 ST 账号下载 |
| ② `352_IMX335` | ⬜ 未开始 | 同上 + IMX335 未到 |
| ③ `991` NPU | ⬜ 未开始 | 同上 + **外部 Flash 型号未知** |
| ④ 部署 | 🚧 模型侧完成 | ST Edge AI 未安装，`network.c` 生成不了 |
| ⑤ 实测 | ⬜ 未开始 | 全部依赖硬件 |

---

## 你回来后按这个顺序做

1. **装 STM32CubeIDE 1.17.0 + CubeProgrammer 2.18+**
   → `02-env-setup.md` §1–§2，装完把 3 个 `.stldr` 拷进 `ExternalLoader\`（§3）
2. **看板上 NOR 芯片丝印，确认型号**
   → `03-n6-deploy-notes.md` §1.3（三选一，选错上电不启动）
3. **编译 `352_IMX335`**（不烧也行，验证工具链）
   → `02-env-setup.md` §5，预期 0 error
4. **按手册走 0b → 0c**
   → `07-deployment-runbook.md` §1–§2

第 3 步只要 20 分钟，做完就能确认整条工具链是通的。

---

## 三个待解技术问题（会决定后续路线）

| # | 问题 | 影响 | 怎么解 |
| :-- | :--- | :--- | :--- |
| 1 | ST 的 `od_yolov8_pp_if.h` 吃**原始头**还是**已解码**输出？ | 决定走路线 A（20 KB 输出）还是 B（267 KB） | 读那个头文件 + `app_postprocess.c` 的取数方式 |
| 2 | `appli.hex` 没有 `STM2` 签名头，FSBL 会不会拒绝启动？ | 影响 0c 能否一次成功 | 烧完看现象，失败就自己签一次 |
| 3 | float 检测头在 int8 的 Neural-ART 上实际开销多少？ | 决定要不要截断 | 看 `stedgeai` 的 report |

---

## 数字速查

| 指标 | 值 |
| :--- | :--- |
| 模型输入 | `[1, 224, 224, 3]`（板上 NHWC uint8）/ `[1,3,224,224]`（ONNX NCHW float） |
| 模型输出 | `[1, 5, 1029]` float32 = **20,580 字节** |
| 原始头输出 | `[1,64,1029]` + `[1,1,1029]` = 267,540 字节 |
| int8 权重 | 3.34 MB（现有池 11 MB，占 30%） |
| 片内 SRAM | 约 2 MB，其中 NPU 激活池 **1.75 MB** |
| 权重 Flash 地址 | **`0x70200000`**，应用区 `0x70100000`（上限 1 MB） |
| 后处理耗时（主机） | 0.013 ms @224、0.020 ms @320 |
| 锚点数 | 224→1029、320→2100、416→3549（`Σ(img/stride)²`） |

---

## 仓库地图

| 目录 | 内容 |
| :--- | :--- |
| `docs/` | 8 份文档，从资产盘点到部署手册（按 00→07 顺序读） |
| `src/` | 4 个源文件 + 4 个测试入口：`yolo_v8_decode` / `yolo_v8_nms` / `yolo_v8_post` |
| `tools/` | `ihex_info`（hex 体检）、`check_project`（工程链接体检）、`tflite_info`、`onnx_info` |
| `notebooks/` | 数据集生成、量化、以及 4 个"与 ultralytics 逐值比对"的校验脚本 |

**大文件都不在仓库里**：模型在 `D:\STM32N6\yolo-baseline\`，数据在 `D:\MyGit\datasets\`，
venv 在 `D:\STM32N6\py\yolo312`。
