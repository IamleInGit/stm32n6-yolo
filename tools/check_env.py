"""环境自检：确认本机能否跑 YOLO 训练 / 导出 / 板端模型转换。

用法：
    python tools/check_env.py
"""

import importlib
import platform
import sys

PKGS = ["torch", "torchvision", "ultralytics", "onnx", "onnxruntime", "cv2", "numpy"]
TFLITE_PY = {(3, 9), (3, 10), (3, 11)}


def version_of(pkg: str) -> str:
    try:
        mod = importlib.import_module(pkg)
    except Exception as exc:  # noqa: BLE001
        return f"未安装 ({exc.__class__.__name__})"
    return str(getattr(mod, "__version__", "unknown"))


def main() -> int:
    py = sys.version_info
    print(f"Python      : {py.major}.{py.minor}.{py.micro}  ({platform.machine()})")
    print(f"平台        : {platform.system()} {platform.release()}")
    print("-" * 46)

    for pkg in PKGS:
        print(f"{pkg:<12}: {version_of(pkg)}")

    try:
        import torch  # noqa: PLC0415

        cuda = torch.cuda.is_available()
        print("-" * 46)
        print(f"CUDA        : {cuda}" + (f" ({torch.cuda.get_device_name(0)})" if cuda else ""))
        print("训练建议    : " + ("可用 GPU，小数据集几分钟" if cuda else "纯 CPU，100 张图建议 <100 epochs 或挂后台"))
    except Exception:  # noqa: BLE001
        pass

    print("-" * 46)
    if (py.major, py.minor) in TFLITE_PY:
        print("TFLite 导出 : 版本可用")
    else:
        print("TFLite 导出 : 当前 Python 版本不支持 int8 TFLite / ST 量化")
        print("              用 Miniconda 建 3.10 环境：conda create -n n6 python=3.10")

    missing = [p for p in PKGS if version_of(p).startswith("未安装")]
    if missing:
        print(f"\n待安装：pip install -r requirements-cpu.txt -i https://pypi.tuna.tsinghua.edu.cn/simple")
        return 1

    print("\n基础环境 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
