# 环境搭建（阶段 0a）

> 目标：从"什么都没装"到"能编译、能烧录、能调试"。
> 只要按顺序做完 §1~§4，就可以直接进 §5 验证。
>
> 预计耗时：**下载 1.5~2 h（看网速），安装与验证 40 min**。

---

## 0 前置检查

| 项目 | 要求 | 备注 |
| :--- | :--- | :--- |
| 系统 | Windows 10/11 x64 | ST 工具只有 x64 版本 |
| 磁盘 | **≥ 20 GB 可用** | CubeIDE ≈ 3 GB，CubeProgrammer ≈ 1 GB，STEdgeAI ≈ 2 GB，Python 包 ≈ 3 GB，模型与数据集另算 |
| 账号 | ST 官网账号（免费） | 下载 CubeIDE/CubeProgrammer 需登录 |
| 权限 | 本机管理员 | 装 ST-LINK 驱动要提权 |
| 网络 | 能访问 st.com | 国内下载慢是常态，建议提前挂着下 |

> **本机实测（2026-11-22）**：C: 只剩 **14.3 GB**，D: 有 **141.3 GB**。
> ST 三件套**一律装 D:**——CubeIDE 约 3 GB、CubeProgrammer 约 1 GB、STEdgeAI 约 2 GB，
> 装 C: 会直接告急，而且安装和编译过程还会大量写 `%TEMP%`。

### 0.1 路径约定（下文所有命令都按这个来）

| 工具 | 安装路径 |
| :--- | :--- |
| STM32CubeIDE 1.17.0 | `D:\ST\STM32CubeIDE_1.17.0` |
| STM32CubeProgrammer | `D:\ST\STM32CubeProgrammer` |
| ST Edge AI Core 4.0 | `D:\ST\STEdgeAI\2.0` |

PowerShell 里先把变量定下来，后面直接复用：

```powershell
$ST  = "D:\ST"
$IDE = "$ST\STM32CubeIDE_1.17.0"
$CP  = "$ST\STM32CubeProgrammer"
$AI  = "$ST\STEdgeAI\2.0"
```

> ⚠️ **CubeProgrammer 的安装器有个坑**：它默认路径是
> `C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer`。
> 只把盘符改成 D，会得到 `D:\ST\STMicroelectronics\STM32Cube\STM32CubeProgrammer`——
> 凭空多两层，下文命令全对不上。
> **在安装器里把整条路径替换成 `D:\ST\STM32CubeProgrammer`。**

装完如果路径和上表不一致（比如 STEdgeAI 自动加了版本层），用这条找真实位置再改变量：

```powershell
Get-ChildItem D:\ST -Recurse -Filter STM32_Programmer_CLI.exe -EA SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
```

**先避开一个坑**：机器上已装的 `STM32 ST-LINK Utility`（`C:\Program Files (x86)\STMicroelectronics`）
是 2005 年代的老工具，**不支持 STM32N6**，本项目的烧录一律用 CubeProgrammer。

---

## 1 安装 STM32CubeIDE 1.17.0

**为什么锁 1.17.0**：`991_AI_People_Detection.ioc` 由 **CubeMX 6.13.0** 生成，
CubeIDE 1.17.0 内置的正是 6.13.0。版本错配会在打开工程时触发 `.cproject` 迁移，
轻则要重新配一遍编译选项，重则链接脚本和 include 路径全丢。

- 下载页：<https://www.st.com/en/development-tools/stm32cubeide.html>（选 **1.17.0**，不要点最新版）
- 安装路径建议：`D:\ST\STM32CubeIDE_1.17.0`
- 安装选项：
  - ✅ ST-LINK 驱动（GDB server / ST-LINK server 一起装）
  - ✅ 关联 `.ioc`（可选，方便双击打开）
  - ⬜ 不需要装到 PATH

安装完成后可执行文件在：`D:\ST\STM32CubeIDE_1.17.0\STM32CubeIDE\stm32cubeide.exe`

> **工作区（workspace）不要设在 git 仓库里**。建议 `D:\STM32N6\workspace`。
> CubeIDE 会在工作区里生成巨大的 `.metadata\`，放进仓库只会污染 git。

---

## 2 安装 STM32CubeProgrammer 2.18.0 或更新

- 下载页：<https://www.st.com/en/development-tools/stm32cubeprog.html>
- 安装选项：
  - ✅ **ST-LINK driver**（必须，否则连不上板）
  - ✅ ST-LINK server（CubeIDE 调试时共用，建议装）
  - ✅ 加入 PATH（勾了省事；没勾就手动加，见下）
- 默认路径：`D:\ST\STM32CubeProgrammer`
- 命令行工具都在 `bin\` 下：
  - `STM32_Programmer_CLI.exe` —— 烧录
  - `STM32_SigningTool_CLI.exe` —— 签名（脱机启动时才用）
  - `ExternalLoader\` —— 外部 Flash 加载器目录

手动加 PATH（PowerShell，需重开终端生效）：

```powershell
$cp = "D:\ST\STM32CubeProgrammer\bin"
[Environment]::SetEnvironmentVariable(
  "Path",
  [Environment]::GetEnvironmentVariable("Path","Machine") + ";$cp",
  "Machine")
```

---

## 3 安装 ATK 板的外部 Flash 加载器（关键一步）

N6 没有片内 Flash，程序要写进板上 NOR，CubeProgrammer 必须靠 `.stldr` 才能寻址。
正点原子已经把三个变体**编译好**了，直接复制即可：

```powershell
$src = "D:\STM32N6\SoftwarePackage\External_Loader"
$dst = "D:\ST\STM32CubeProgrammer\bin\ExternalLoader"

Get-ChildItem $src -Recurse -Filter *_ATK-CNN647B_ExtMemLoader.stldr |
    Copy-Item -Destination $dst -Force

Get-ChildItem $dst -Filter *ATK-CNN647B* | Select-Object Name, Length
```

期望看到 3 个文件，各约 40 KB：

```
BY25FQ128EL_ATK-CNN647B_ExtMemLoader.stldr
DUAL_BY25FQ128EL_ATK-CNN647B_ExtMemLoader.stldr
MX25UM25645G_ATK-CNN647B_ExtMemLoader.stldr
```

> 到阶段 0c 烧录时，还要从中**选定唯一一个**与板上芯片对应的 `.stldr`。
> 型号确认方法见 [`01-assets.md`](01-assets.md) §5。

---

## 4 验收清单

逐条执行，全部通过才算阶段 0a 完成。

### 4.1 CubeProgrammer 可用

```powershell
STM32_Programmer_CLI --version
```

期望：打印 `STM32CubeProgrammer` 及 `v2.18.x` 以上版本号。
若提示"不是内部或外部命令"，说明 PATH 没生效——用绝对路径重试，或重开终端。

### 4.2 CubeIDE 就位

```powershell
Test-Path "D:\ST\STM32CubeIDE_1.17.0\STM32CubeIDE\stm32cubeide.exe"
```

期望：`True`

### 4.3 加载器就位

见 §3 最后一条命令，应列出 3 个 `.stldr`。

### 4.4 板子能被识别（**需要板子在手**）

1. 用 **USB-C to USB-C** 线接板上 ST-LINK 口（普通 USB-A 口供电可能不足）
2. 板子上的 BOOT 开关拨到 **Development / 从 RAM 启动** 模式
3. 执行：

```powershell
STM32_Programmer_CLI -c port=SWD mode=HOTPLUG
```

期望：能读出 Device ID / Revision，不报 `No STM32 target found`。

> 若连不上：先查线（很多"连不上"是 A-to-C 线）、再查 BOOT 开关、最后查驱动（设备管理器里
> 是否出现 `STMicroelectronics STLink USB Device`）。
> `mode=HOTPLUG` 是 N6 的关键参数，普通 connect 常常失败。

---

## 5 首次编译验证：`352_IMX335`

这一步**不烧录也能做**，目的是确认工具链完整。

1. 打开 CubeIDE，选工作区 `D:\STM32N6\workspace`（**不要**选 `D:\MyGit\...`）
2. `File → Open Projects from File System...`
3. Import source 指向：
   `D:\STM32N6\SoftwarePackage\Projects\35_Sensor\352_IMX335\STM32CubeIDE\Appli`
4. Finish，等待索引（首次会有几分钟 `Building workspace`）
5. 选中工程，构建配置切到 **Debug**（对应 `LRUN_RAMxspi1.ld`，即"跑在 RAM"）
6. `Project → Build Project`

**期望**：Console 末尾 `Build Finished. 0 errors, 0 warnings`，并生成 `.elf` / `.bin`。

### 5.1 如果不通过，先看这三条

| 现象 | 原因 | 处理 |
| :--- | :--- | :--- |
| 大量 `undefined reference to HAL_xxx` | `STM32Cube_FW_N6_V1.0.0` 路径没解析到 | 确认工程仍位于 `SoftwarePackage\Projects\...`，**没有把单个例程目录拷出来**。`.project` 用 `PARENT-5-PROJECT_LOC` 引用 FW，目录层级动了就断 |
| `No such file or directory` 指向 `Middlewares/...` | 同上，包结构被改动 | 恢复原始层级；`SoftwarePackage` 整体别挪、别改名 |
| `postbuild` 相关报错 | `postbuild.sh` 依赖 shell，Windows 下可能失败 | `.elf` 已经生成的话可忽略；或把 Post-build steps 改成直接调用 `arm-none-eabi-objcopy -O binary` |

> **别被 include 路径吓到**：`.cproject` 里有一批 `../../../../../../STM32Cube_FW_N6_V1.0.0/...`。
> 按工程根目录算是"错"的，但 CubeIDE 传给编译器的相对 `-I` 是以**构建目录**（`<工程>/Debug/`）
> 为工作目录解析的，退 6 级正好落在 `SoftwarePackage\`。所以这些路径是对的，**别手改**。
> 想验证就先跑 `tools/check_project.py`（见 §9）。

> **原则**：例程永远"原地编译"，不要拷到仓库里改。
> 仓库的 `src/` 先只放我们**新写**的模块（后处理、绘制工具），
> 等阶段 3 工程结构稳定了再决定要不要整体迁入。

---

## 6 延后安装（阶段 2~3 再做，别现在折腾）

### 6.1 ST Edge AI Core **2.0.0**（不是 4.0）

- 下载页：<https://www.st.com/en/development-tools/stedgeai-core.html>
- 默认路径：`D:\ST\STEdgeAI\2.0`
- 可执行文件：`D:\ST\STEdgeAI\2.0\Utilities\windows\stedgeai.exe`

**版本为什么必须是 2.0** —— 从包内文件里直接读到两条硬证据：

```
Model\network.c:29  --load-mdesc-file = "STEdgeAI/2.0/Utilities/configs/stm32n6"
Model\network.c:51  #if LL_ATON_VERSION_MAJOR != 1 || ... _DEV != 16
```

即：这版 `network.c` 是 **STEdgeAI 2.0** 生成的，且要求 **ll_aton 1.0.0-dev16**。
换任何别的版本（包括 ST 官方仓库 README 里写的 4.0.0）都会报
`Possible mismatch in ll_aton library used`。

> 这个坑我踩过：先前文档按 ST 官方 GettingStarted 仓库的 "Tools Version: STEdgeAI 4.0.0" 写，
> 那个仓库已经升级过；而本工程是正点原子 2025-01 的版本，配套的是 2.0。
> **以包内 `network.c` 的这行注释为准，不要以任何 README 为准。**

### 6.1.1 后处理中间件的真实路径

计划里提到的 `Middlewares/ai-postprocessing-wrapper/README.md` **在软件包里不存在**。
本包对应的目录是：

```
Middlewares\STM32_VISION_MODELS_PP\     ← 头文件 od_yolov8_pp_if.h 等都在这里
```

查后处理类型（`..._UF` / `..._UI`）时去这里翻，别去找那个不存在的路径。

### 6.2 Python 3.12 独立环境（✅ 已完成，2026-11-16）

本机系统 Python 是 **3.14.6**，太新：ultralytics / STEdgeAI / `stm32ai-modelzoo-services` 都还没跟上。
已用 `uv` 在**用户级**装好独立 3.12——不碰系统 Python，不需要管理员权限：

```powershell
python -m pip install --user uv
$uv = "$env:APPDATA\Python\Python314\Scripts\uv.exe"
$env:UV_CACHE_DIR = "D:\STM32N6\uv-cache"        # 缓存放 D:，别占 C:
& $uv python install 3.12
& $uv venv D:\STM32N6\py\yolo312 --python 3.12
& $uv pip install --python D:\STM32N6\py\yolo312\Scripts\python.exe numpy onnx onnxruntime tqdm
```

**实测结果**：

| 组件 | 版本 | 位置 |
| :--- | :--- | :--- |
| Python | **3.12.16** | `%APPDATA%\uv\python\cpython-3.12.16-windows-x86_64-none\` |
| venv | — | `D:\STM32N6\py\yolo312` |
| numpy / onnx / onnxruntime | 2.5.5 / 1.23.2 / 1.32.0 | 同上 |
| onnxruntime providers | `CPUExecutionProvider` | 无 CUDA，纯 CPU 推理 |

> venv **故意放在仓库外**（`D:\STM32N6\py\`），避免几 GB 依赖进 git。
> 用的时候：`D:\STM32N6\py\yolo312\Scripts\activate`

⚠️ **进量化阶段要降版本**：ST 教程锁定 `onnx==1.16.1`、`onnxruntime==1.20.1`、opset **17**。
现在是"最新版"，等真正跑 `stm32ai_main.py` 前按 ST 要求重装：

```powershell
& $uv pip install --python D:\STM32N6\py\yolo312\Scripts\python.exe onnx==1.16.1 onnxruntime==1.20.1
```

**尚未安装**：`torch` / `ultralytics`（约 2~3 GB，训练阶段再装）。

---

## 7 版本记录（装完就填，后面排查全靠它）

| 组件 | 版本 | 路径 |
| :--- | :--- | :--- |
| STM32CubeIDE | **1.17.0（✅ 已装）** | `D:\ST\STM32CubeIDE_1.17.0` |
| STM32CubeProgrammer | **2.22.0（✅ 已装）** | `D:\ST\STM32CubeProgrammer` |
| STM32CubeMX（内置） | 6.13.0 | 随 CubeIDE |
| STM32Cube FW N6 | V1.0.0 | `D:\STM32N6\SoftwarePackage\STM32Cube_FW_N6_V1.0.0` |
| ST Edge AI Core | 2.0.0（待装） | `D:\ST\STEdgeAI\2.0` |
| Python | **3.12.16（✅ 已装）** | `D:\STM32N6\py\yolo312` |
| uv | 0.13.8（✅ 已装） | `%APPDATA%\Python\Python314\Scripts\uv.exe` |
| 外部 Flash 型号 | **待确认** | — |
| 调试器 | **待确认** | — |

---

## 8 主机端 C 编译器（zig，免安装）

本机原本**没有任何 C 编译器**（无 cl / gcc / clang / make / cmake），
但 `src/` 里的解码代码需要真正编译验证。解决办法：

```powershell
python -m pip install --user uv            # 已有
& $uv pip install --python D:\STM32N6\py\yolo312\Scripts\python.exe ziglang
& $py -m ziglang cc --version              # clang 22.1.8
```

`ziglang` 是 PyPI 上的 wheel 包，自带完整的 zig（含 C 编译器），**不需要管理员权限**。

```powershell
& $py -m ziglang cc -O2 -Wall -Wextra -std=c99 -o test_decode.exe src\test_decode.c src\yolo_v8_decode.c
```

> **一个网络上的实测发现**：这台机器只有 **PyPI 是快的**（~2 MB/s），
> 其它站点（`ziglang.org`、`images.cocodataset.org`、`github.com`）一律被限到 **≈46 KB/s**，
> 而且 `images.cocodataset.org` 的 HTTPS 还会证书不匹配（`SEC_E_WRONG_PRINCIPAL`）。
> **结论：需要什么工具，优先找 PyPI 上的 wheel 包，别直接下压缩包。**
> 96 MB 的 zig 直接下载要 35 分钟，走 PyPI 只用了 1 分 16 秒。

---

## 9 阶段 0a 完成判据

- [ ] `STM32_Programmer_CLI --version` 正常输出版本
- [ ] CubeIDE 1.17.0 启动正常
- [ ] 3 个 `.stldr` 已放进 `ExternalLoader\`
- [ ] 能 `-c port=SWD mode=HOTPLUG` 连上板子
- [ ] `352_IMX335` 在 Debug 配置下 **0 error** 编译通过
- [ ] 上表版本信息已填完

打勾之后进阶段 0b：IMX335 到货 → 烧 `352_IMX335` → 屏上出画面。

---

## 10 仓库自带工具（不装任何 ST 工具也能跑）

| 脚本 | 用途 | 用法 |
| :--- | :--- | :--- |
| `tools/ihex_info.py` | 看 hex 的地址范围、载荷大小、能否放进指定容量的 Flash；顺带判断有没有签名头 | `python tools/ihex_info.py <file.hex> --flash 16M` |
| `tools/check_project.py` | 解析 `.project` / `.cproject`，提前发现"导入后编不过" | `python tools/check_project.py <工程目录>` |
| `tools/tflite_info.py` | 读 `.tflite` 的真实输入/输出张量形状，核对 C 里的后处理常数 | `python tools/tflite_info.py <model.tflite>` |
| `tools/onnx_info.py` | 读 `.onnx` 的输入/输出形状、opset、算子构成，判断有无 NMS（ST 不允许） | `python tools/onnx_info.py <model.onnx>` |

`check_project.py` 的两级判定：

- **[硬] 链接资源**：`.project` 里 `PARENT-n-PROJECT_LOC` 指向的真实文件。缺了必然编译失败。
- **[软] 相对 include**：`-I` 路径，按 `Debug/` / `Release/` 兜底解析（见 §5.1 的说明）。

**2026-11-16 实测结果**：

| 工程 | 链接资源 | 硬错误 | 软警告 |
| :--- | ---: | ---: | ---: |
| `352_IMX335` | 30 | 0 | 0 |
| `991_AI_People_Detection` | 314 | 0 | 0 |

两个工程结构完好，导入 CubeIDE 后应能直接编译。
