"""导出模型：ONNX（任何 Python 版本）或 int8 TFLite（需 Python 3.9~3.11）。

ST 工具链只接受 per-channel 量化的 int8 模型，而 Ultralytics 默认 per-tensor，
所以导出 TFLite 前必须先打补丁（脚本会自动做）。

用法：
    python tools/export_onnx.py --weights yolov8n.pt --imgsz 256
    python tools/export_onnx.py --weights runs/detect/train/weights/best.pt --format tflite
"""

import argparse
import importlib.util
import pathlib
import sys

from ultralytics import YOLO


def patch_tflite_exporter() -> bool:
    """把 ultralytics 的 TFLite 量化方式改为 per-channel（幂等）。"""
    spec = importlib.util.find_spec("ultralytics")
    if spec is None or spec.origin is None:
        print("找不到 ultralytics 安装位置")
        return False

    exporter = pathlib.Path(spec.origin).parent / "engine" / "exporter.py"
    if not exporter.exists():
        print(f"找不到 {exporter}")
        return False

    text = exporter.read_text(encoding="utf-8")
    if 'quant_type="per-channel"' in text:
        print("已经是 per-channel，跳过补丁")
        return True

    patched = text.replace('quant_type="per-tensor"', 'quant_type="per-channel"')
    if patched == text:
        print("未找到 quant_type 字面量，请手动检查 exporter.py")
        return False

    exporter.write_text(patched, encoding="utf-8")
    print(f"已改写为 per-channel：{exporter}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", default="yolov8n.pt")
    parser.add_argument("--format", default="onnx", choices=["onnx", "tflite"])
    parser.add_argument("--imgsz", type=int, default=256)
    parser.add_argument("--half", action="store_true", help="仅对 onnx 有意义")
    args = parser.parse_args()

    if args.format == "tflite":
        if sys.version_info[:2] not in {(3, 9), (3, 10), (3, 11)}:
            print(f"当前 Python {sys.version_info.major}.{sys.version_info.minor} 不支持 TFLite 导出")
            print("请用 3.10 环境：conda create -n n6 python=3.10")
            return 1
        if not patch_tflite_exporter():
            return 1

    model = YOLO(args.weights)
    out = model.export(format=args.format, imgsz=args.imgsz, int8=(args.format == "tflite"))
    print(f"导出完成：{out}")
    if args.format == "tflite":
        print("确认产物中 *_integer_quant.tflite 的输入类型为 uint8，再交给 ST 工具链。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
