# 烧录与 BOOT

## BOOT 模式（P6 跳线）

| 模式 | 跳线 | 用途 |
|---|---|---|
| **Development boot** | B1 接 3V3 | 调试 / 烧录 |
| **Flash boot** | B0、B1 都接 GND | 正常运行 |

STM32N6 **没有片内 Flash**，固件必须落在外部 NOR。所以有三个独立的东西要烧：

| 文件 | 作用 | 什么时候需要重烧 |
|---|---|---|
| `fsbl.hex` | First Stage Boot Loader，把应用从 Flash 搬进 RAM | 只烧一次 |
| `appli.hex` | 应用程序 | 每次改代码 |
| `network-data.hex` | 神经网络权重 | **每次换模型** |

> "改了模型但没反应"的头号原因就是漏烧 `network-data.hex`。

## 命令行烧录

```bash
# <loader> 用软件包里自带的 .stldr
STM32_Programmer_CLI -c port=SWD mode=HOTPLUG -el "<loader>.stldr" -hardRst -w fsbl.hex
STM32_Programmer_CLI -c port=SWD mode=HOTPLUG -el "<loader>.stldr" -hardRst -w appli.hex
STM32_Programmer_CLI -c port=SWD mode=HOTPLUG -el "<loader>.stldr" -hardRst -w network-data.hex
```

顺序无关。烧完把跳线拨回 Flash boot 再上电。

## 从源码构建（P3 之后才需要）

```bash
STM32_SigningTool_CLI -bin Project.bin -nk -t ssbl -hv 2.3 --align -o Project_sign.bin
STM32_Programmer_CLI -c port=SWD mode=HOTPLUG -el "<loader>.stldr" -hardRst -w Project_sign.bin 0x70100000
```

`--align` 是 CubeProgrammer 2.21 之后才有的参数，旧版本去掉它。

## 现象对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| 找不到目标 | BOOT 在 Flash boot；充电线；ST-LINK 驱动 | 切 Development boot，加 `-hardRst`，换数据线 |
| 烧完重启黑屏 | 漏烧 `network-data.hex`；跳线没拨回 | 三个都烧，B0/B1 接地 |
| 屏花屏 | 非原厂屏 / FPC 没插到位 / 供电不足 | 换原厂屏，换 DC 供电 |
| 有画面无框 | 后处理类型错 / 类别数不对 | 改 `app_config.h` |
| 框全乱 | per-tensor 量化；校准集与实际场景不符 | 改 per-channel，校准集用自己场景的图 |
| 编译报 `ll_aton` 不匹配 | ST Edge AI 版本与工程不一致 | 统一到 2.0.0，或整体重新生成 |
