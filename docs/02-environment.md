# 环境搭建

## 版本矩阵（必须对齐）

| 软件 | 版本 | 说明 |
|---|---|---|
| STM32CubeIDE | 1.17.x / 1.18.x | 必须 ≥1.17（N6 器件支持起点）；GCC 需为 `12.3.rel1` |
| STM32CubeProgrammer | ≥ 2.18 | N6 外部 Flash loader 支持 |
| ST Edge AI Core | **2.0.0** | 与软件包里 `network.c` 的版本绑定 |
| ST Neural-ART 包 | `stedgeai-stneuralart-10.0.0.zip` | 安装 STEdgeAI 时要求指定，需单独下载 |
| Python（训练/导出） | 3.9 ~ 3.11 | 3.12 不支持 `tensorflow 2.15.1` / `tflite_support` |
| ultralytics | 8.3.x | ST 文档验证过 8.3.157 |
| tensorflow / tf_keras | 2.15.1 / 2.15.1 | 高了会挂 |
| onnx / onnxruntime | 1.15.0 / 1.18.1 | |

## 安装顺序

1. STM32CubeProgrammer（顺带装 ST-LINK 驱动）
2. STM32CubeIDE → 验证 `arm-none-eabi-gcc --version` 输出 `12.3.rel1`
3. 解压 Neural-ART 包到短路径，如 `C:\ST\stneuralart_10.0.0`
4. 安装 ST Edge AI Core 2.0.0，指定上一步路径

> 路径不要含中文和空格，STEdgeAI 对此敏感。

## Python 环境

```bash
conda create -n n6 python=3.10 -y
conda activate n6

# 无独显：先装 CPU 版 torch，省 2 GB
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

pip install -r requirements-cpu.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 需要导出 int8 TFLite 时再加
pip install tensorflow==2.15.1 tf_keras==2.15.1
```

自检：

```bash
python tools/check_env.py
```

## 已知问题

### ST 官网下载反复跳登录

现象：登录后点下载仍回到登录页；换"Download as a guest"同样循环。

已排除：家庭网络与公司网络同样复现 → 不是网络问题。

怀疑原因与对策：

1. **Edge 跟踪防护拦截跨域 Cookie**（默认"平衡"档）
   - 改 `edge://settings/privacy` 为"基本"
   - `edge://settings/content/cookies` 允许 `[*.]st.com`
   - `edge://settings/content/popups` 允许 `[*.]st.com`
   - `edge://settings/siteData` 清除 st.com 数据
2. **弹窗拦截导致"资料补全"流程中断**，会话永远不完整
3. **QQ 邮箱注册的账号未验证**，或资料未补全 → 下载权限不生效
4. 换 Firefox 全新配置验证（若 Firefox 能下，即为浏览器策略问题）

绕过路径：正点原子资料包内可能自带安装包；或让同事代下；模型转换可用网页版 <https://stedgeai-dc.st.com/>。
