# 部署配置与内存地图

> 数据来源：`991_AI_People_Detection` 的预编译产物实测（`tools/ihex_info.py`）
> 与 ST Edge AI 生成物里的内存池注释（`Model\network.c`）。
> 这些是**板上跑得通的那一版**的真实参数，换模型时逐条对照。

---

## 1 外部 Flash 地图（xSPI2，基址 `0x70000000`）

| 区域 | 起始 | 结束 | 大小 | 内容 | 签名 |
| :--- | :--- | :--- | ---: | :--- | :--- |
| FSBL | `0x70000000` | `0x70007080` | 28.1 KB | 第一级引导 | ✅ 有 `STM2` 头 + 签名 |
| （预留） | `0x70007080` | `0x70100000` | ~1 MB | 空 | — |
| 应用头部 | `0x70100000` | `0x70100400` | 1 KB | 空（向量表前预留） | — |
| 应用 | `0x70100400` | `0x7012D200` | 179.5 KB | `appli`，XIP 就地执行 | ❌ **无签名** |
| 权重池 | `0x70200000` | `0x70CFEAF8` | **11.0 MB** | NPU 权重（mpool `index=5`） | — |
| （空闲） | `0x70CFEAF8` | `0x71000000` | ~3.1 MB | 未使用 | — |

**结论：16 MB 的 `BY25FQ128EL` 够用，占用 65.9%。**
32 MB 的 `MX25UM25645G` 只是更宽松，不是必需。

> 应用区被限制在 `0x70100000 ~ 0x70200000` 这 **1 MB** 内（因为权重从 `0x70200000` 开始）。
> 当前只用了 179.5 KB，换 YOLOv8n 后代码量增长也远不会顶到 1 MB，但这是个硬边界。

### 1.1 签名状态：一个必须留意的差异

- `fsbl-*.hex` 前 4 字节是 `53 54 4D 32`（ASCII `STM2`）→ ST 镜像头，已签名
- `appli.hex` 前 4 字节是 `00 00 20 34`（SP = `0x34200000`）→ ARM 向量表，**裸镜像，未签名**

而 ST 官方流程要求应用也用 `STM32_SigningTool_CLI -t ssbl` 签过名才能放 `0x70100000`。
正点原子直接给了未签名版本，说明**它的 FSBL 大概率不做校验**（boot ROM 只校验 FSBL）。

**如果烧完不启动，第一个补救动作就是自己签一次：**

```powershell
STM32_SigningTool_CLI -bin appli.bin -nk -t ssbl -hv 2.3 --align -o appli_sign.bin
```

> `--align` 仅 CubeProgrammer **2.21+** 需要；更早版本去掉该参数。这一点待板上验证。

### 1.2 两个构建配置（决定"跑 RAM"还是"烧 Flash"）

| 配置 | 链接脚本 | 运行地址 | 用途 | 要签名 |
| :--- | :--- | :--- | :--- | :--- |
| `Debug` | `STM32N647X0HXQ_LRUN_RAMxspi1.ld` | `0x34000400`（片内 RAM） | CubeIDE 在线调试，掉电即失 | 不需要 |
| `Release` | `STM32N647X0HXQ_ROMxspi2_RAMxspi1.ld` | `0x70100400`（外部 Flash，XIP） | 脱机启动 | 需要 |

`352_IMX335` 与 `991` 的配置名和链接脚本完全一致。
包内预编译的 `appli.hex` 链接在 `0x70100400`，**就是 Release 那一份**。

> **烧录顺序很重要**：权重池是绝对地址 `0x70200000`，写死在 `network.c` 的 mpool 里，
> 与 Debug/Release 无关。所以**哪怕只是在 RAM 里在线调试，也必须先把 `network-data.hex` 写进外部 Flash**，
> 否则 NPU 读到的是空白 Flash——表现是推理输出全零或直接 HardFault。
>
> 推荐顺序：① 烧 FSBL → ② 烧 network-data → ③ `Debug` 配置在线调试 → ④ 稳了再 `Release` + 签名 + 烧 `0x70100000`

### 1.3 怎么确定板上是哪颗 Flash

**结论：应用侧自动识别，FSBL 和烧录加载器不会。**

`Drivers\BSP\NORFlash\norflash.c` 先发 `0x9F` 读 JEDEC ID，再分支：

```c
if      (NORFlash_IS_BY25FQ128EL(JEDECID))       { ... }
else if (NORFlash_IS_DUAL_BY25FQ128EL(JEDECID))  { ... }
else if (NORFlash_IS_MX25UM25645G(JEDECID))      { ... }
```

而 FSBL 走的是 `MX_EXTMEM_MANAGER_Init()` + `STM32CubeIDE` 里的 `stm32_extmem_conf.h`，
**编译期写死**——所以三个 `fsbl-*.hex` 不能混用，`.stldr` 也不能混用。

三条确认途径，从易到难：

1. **看丝印**：NOR 芯片表面印着 `BY25FQ128EL` 或 `MX25UM25645G`。
2. **跑 `352_IMX335` 的 Debug 配置**：应用自己会识别，串口日志里能看到命中的是哪颗。
   Debug 模式跑在 RAM 里，不需要 FSBL，也不写外部 Flash，零风险。
3. **逐个试加载器读一个字**（只读，安全）：

```powershell
$bin = "D:\ST\STM32CubeProgrammer\bin"
foreach ($f in "BY25FQ128EL","DUAL_BY25FQ128EL","MX25UM25645G") {
    Write-Host "--- $f"
    & "$bin\STM32_Programmer_CLI.exe" -c port=SWD mode=HOTPLUG `
        -el "$bin\ExternalLoader\${f}_ATK-CNN647B_ExtMemLoader.stldr" `
        -r32 0x70000000 1
}
```

能正常读出数据、不报 init/timeout 的那个就是对的。
用错的加载器会在初始化阶段就失败，不会损坏芯片。

> **一个能省事的地方**：既然应用会自动识别，那么只要你用 `Debug`（RAM）模式开发，
> **唯一依赖加载器的动作就是"写权重"**。权重烧完之后，调试和运行都与 Flash 型号无关，
> 只有最后做脱机启动（烧 `fsbl-*.hex`）时才会再次用到。

---


| 区域 | 地址范围 | 大小 | 用途 |
| :--- | :--- | ---: | :--- |
| SRAM（app 运行区） | `0x34000400` ~ `0x34200000` | 2047 KB | 应用代码、堆栈、Camera/LCD buffer、ThreadX |
| AXISRAM3 | `0x34200000` ~ `0x34270000` | 448 KB | ┐ |
| AXISRAM4 | `0x34270000` ~ `0x342E0000` | 448 KB | │ NPU 激活内存 |
| AXISRAM5 | `0x342E0000` ~ `0x34350000` | 448 KB | │ （mpool `index=7`，vpool） |
| AXISRAM6 | `0x34350000` ~ `0x343C0000` | 448 KB | ┘ |
| **NPU 合计** | `0x34200000` ~ `0x343C0000` | **1.75 MB** | 激活 + 中间张量 |

> **这 1.75 MB 就是模型激活的预算上限。**
> 换模型前先用 `stedgeai` 的 report 看激活峰值，超了就降分辨率或开 tiling。
> 两个区域首尾相接（app 区正好到 `0x34200000` 为止），所以给 app 抢内存会直接压到 NPU。

### 2.1 HyperRAM（有个待确认的不一致）

| 来源 | 地址 | 大小 |
| :--- | :--- | ---: |
| mpool（`network.c` 注释 `index=4`） | `0x90000000` | 16 MB |
| 链接脚本 `EXTRAM` | `0x91000000` | 16 MB |

两者差 16 MB，说明 HyperRAM 实际容量可能 ≥ 32 MB，或链接脚本那块是另一段窗口。
本阶段用不到，但**往 HyperRAM 放 buffer 前要确认清楚**，别让两个地址混用。

---

## 3 模型接口尺寸（tflite 实测 + C 代码交叉核对）

| 项 | 值 | 出处 |
| :--- | :--- | :--- |
| 输入 | `[1, 224, 224, 3]` **UINT8** = 150528 字节 | tflite `serving_default_input_1:0`；`network.c` mpool 8 |
| 输出 | `[1, 7, 7, 30]` **FLOAT32** = 1470 元素 = **5880 字节** | tflite `StatefulPartitionedCall:0`；`network.c` mpool 9 |
| 网格 | 7 × 7 | `postprocess_conf.h` `GRID_WIDTH/HEIGHT` |
| anchors | 5 组（已归一化） | `postprocess_conf.h` |
| 类别 | 1 | `postprocess_conf.h` `NB_CLASSES (1)` |
| 输入格式 | RGB888 | `NN_FORMAT = DCMIPP_PIXEL_PACKER_FORMAT_RGB888_YUV444_1` |
| 输出格式 | float32 | `--native-float` |

**关键换算**：`30 = 5 anchors × (5 box + 1 class)`，`7×7×30 = 1470 元素`，
float32 所以占 **1470 × 4 = 5880 字节**。

> 我第一次读到 `NN_BUFFER_OUT_SIZE 5880` 时，按"5880 个元素"去拆，误算成 `14×14×30`。
> 它其实是**字节数**。换模型时这个值要按 `网格² × 5 × (5 + 类数) × 4` 重算——
> 少了这一步，症状是"能编译、能推理、框全歪"，非常难查。

anchors（`postprocess_conf.h`，归一化到网格尺度）：

```
0.9883,  3.3606
2.1194,  5.3759
3.0520,  9.1336
5.5517,  9.3066
9.7260, 11.1422
```

### 3.1 一处待确认的不一致

`app_config.h` 写的是 `NN_CLASSES 2` + `{"person", "not_person"}`，
但 `postprocess_conf.h` 是 `NB_CLASSES (1)`，模型输出也只有 1 个类别。
后处理实际用的是 `postprocess_conf.h`，所以**真正解码的只有 1 类（person）**，
`"not_person"` 永远不会出现。

改自己模型时这两处必须一起改，否则标签/阈值会按错的类数走。

---

## 4 `user_neuralart.json`：生成模型的真实参数

```json
"options" : "--enable-epoch-controller --all-buffers-info --no-hw-sw-parallelism
             --cache-maintenance --enable-virtual-mem-pools --native-float
             --optimization 3 --Os --Omax-ca-pipe 4 --Ocache-opt"
```

| 选项 | 作用 | 换模型时的处理 |
| :--- | :--- | :--- |
| `--native-float` | 输入端/输出端保持 float，不在边界做 int8 转换 | **保持**，否则后处理读数据要改写 |
| `--enable-virtual-mem-pools` | 允许虚拟内存池，缓冲区可复用/叠加，省 SRAM | **保持**，关掉大概率跑不进 1.75 MB |
| `--cache-maintenance` | 自动插入 cache 维护操作 | **保持**，N6 的 NPU 与 M7 侧 cache 不一致会读到脏数据 |
| `--enable-epoch-controller` | 启用流水控制，层间并行 | 保持 |
| `--Omax-ca-pipe 4` | 卷积累加流水深度，速度/内存权衡 | 保持；想压内存可试下调 |
| `--optimization 3 --Os` | 高优化 + 体积优先 | 保持 |
| `--no-hw-sw-parallelism` | 关闭软硬件并行调度 | 保持 |
| `--all-buffers-info` | 输出全部 buffer 信息（诊断用） | 保留，便于看 report |

> 这些都是"开关级"的取舍，**不要凭直觉改**。改动后必须重跑并对比
> report 里的激活峰值和实测帧率，否则很容易出现"能编译但跑飞"。

---

## 5 换模型时的改动清单（按顺序）

| # | 文件 / 位置 | 改什么 | 忘改的后果 |
| :-- | :--- | :--- | :--- |
| 1 | `Model\` | 放新生成的 `network.c`、`network_ecblobs.h` | 编译报 `Possible mismatch in ll_aton library used` |
| 2 | `Binary\network-data.hex` | 用新 `.xSPI2.raw` 重新 objcopy 到 `0x70200000` | 推理结果乱码/全零 |
| 3 | `Appli\Core\Inc\app_config.h` | `NN_WIDTH/HEIGHT`、`NN_CLASSES` + 类别表 | 框坐标全偏 |
| 4 | 同上 | `NN_BUFFER_OUT_SIZE`（按 `网格² × 5 × (5+类数) × 4` 重算字节数） | 输出 buffer 越界或截断 |
| 5 | 同上 | `POSTPROCESS_TYPE`（YOLOv2 → YOLOv8） | 后处理按错格式解码，不出框 |
| 6 | `Appli\Core\Inc\postprocess_conf.h` | 网格尺寸、anchors、类数（`AI_OBJDETECT_*`） | 框位置错、置信度错 |
| 7 | `Model\user_neuralart.json` | 不动（沿用） | — |

第 6 步的宏名在 `app_postprocess.c` 里能直接看到：
`AI_OBJDETECT_YOLOV2_PP_NB_ANCHORS` / `_NB_CLASSES` / `_GRID_HEIGHT` / `_GRID_WIDTH` / `_ANCHORS`，
YOLOv8 对应 `AI_OBJDETECT_YOLOV8_PP_NB_CLASSES`。

---

## 6 待验证项（等硬件到位后逐条打勾）

- [ ] `appli.hex` 未签名能否被 FSBL 接受并启动
- [ ] 三个 `.stldr` 中哪个与板上 Flash 匹配
- [ ] 实际帧率与单帧 NPU 耗时
- [ ] HyperRAM 真实基址与容量（§2.1 的不一致）
- [ ] `max_onchip_sram_size=1024KB` 与实际使用 1.75 MB 的关系（mpool 里有这个参数，但实际池是 1.75 MB）
