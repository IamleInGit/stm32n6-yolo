#!/usr/bin/env python3
"""int8 静态量化（QDQ 格式）——ST 量化流程的本地探路版。

为什么先做这个：
  板上要的是 int8 模型，但 ST 的 `stm32ai-modelzoo-services` / `stedgeai` 还没装。
  先用 onnxruntime 的 quantize_static 产一版 QDQ int8，可以提前答三个问题：
    1. 体积能压到多少（fp32 12 MB → ？）
    2. 掉点大概什么量级（mAP50 会掉多少）
    3. 哪些算子会被留在 float（这些算子将来可能拖慢 NPU）

注意：这不是最终产物。ST 的官方路径是 `chain_qe` / `chain_qd`，
      它的 `onnx_quantizer` 产出的 QDQ 与这里不完全等价。
      这里只用来**预判量级**，不作为交付物。

用法：
    python notebooks/quantize_onnx.py <model.onnx> <图片目录> [--out out.onnx] [--size 224]
"""

import argparse
import sys
from pathlib import Path

import numpy as np


def letterbox(img, size, pad=114):
    """等比缩放 + 灰边填充，和训练/验证时的预处理保持一致。"""
    import cv2

    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), pad, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas


def build_reader(img_dir, input_name, size, limit):
    from onnxruntime.quantization import CalibrationDataReader

    class PersonReader(CalibrationDataReader):
        def __init__(self):
            exts = {".jpg", ".jpeg", ".png", ".bmp"}
            self.paths = sorted(p for p in Path(img_dir).rglob("*") if p.suffix.lower() in exts)
            if limit:
                self.paths = self.paths[:limit]
            self.idx = 0
            self.name = input_name
            self.size = size

        def get_next(self):
            if self.idx >= len(self.paths):
                return None
            import cv2

            img = cv2.imread(str(self.paths[self.idx]))
            self.idx += 1
            if img is None:
                return self.get_next()
            img = letterbox(img, self.size)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            x = img.astype(np.float32) / 255.0
            x = np.transpose(x, (2, 0, 1))[None, ...]   # HWC → NCHW
            return {self.name: np.ascontiguousarray(x)}

        def __len__(self):
            return len(self.paths)

    return PersonReader()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("images")
    ap.add_argument("--out", default=None)
    ap.add_argument("--size", type=int, default=224)
    ap.add_argument("--limit", type=int, default=None, help="只用前 N 张校准")
    args = ap.parse_args()

    import onnx
    from onnxruntime.quantization import QuantFormat, QuantType, quantize_static

    model_path = Path(args.model)
    out_path = Path(args.out) if args.out else model_path.with_name(model_path.stem + "_int8.onnx")

    m = onnx.load(str(model_path))
    input_name = m.graph.input[0].name
    print(f"模型      : {model_path}")
    print(f"输入张量  : {input_name}")

    reader = build_reader(args.images, input_name, args.size, args.limit)
    n = len(reader)
    if n == 0:
        print("校准集为空，检查图片目录")
        return 2
    print(f"校准集    : {n} 张图 @ {args.size}x{args.size}")

    quantize_static(
        model_input=str(model_path),
        model_output=str(out_path),
        calibration_data_reader=reader,
        quant_format=QuantFormat.QDQ,
        per_channel=True,                 # 对齐 ST modelzoo 的 granularity: per_channel
        activation_type=QuantType.QUInt8,  # 激活用 uint8
        weight_type=QuantType.QInt8,       # 权重用 int8
        optimize_model=True,
    )

    src_mb = model_path.stat().st_size / 1024 / 1024
    dst_mb = out_path.stat().st_size / 1024 / 1024
    print(f"\n输出      : {out_path}")
    print(f"体积      : {src_mb:.2f} MB → {dst_mb:.2f} MB（压缩到 {dst_mb / src_mb * 100:.1f}%）")

    # 统计有多少算子仍留在 float（这些是量化没覆盖到的）
    q = onnx.load(str(out_path))
    ops = [n.op_type for n in q.graph.node]
    fp = sum(1 for o in ops if o in ("Conv", "MatMul", "Gemm"))
    qdq = sum(1 for o in ops if o in ("QuantizeLinear", "DequantizeLinear"))
    print(f"节点      : {len(ops)}（Q/DQ 节点 {qdq} 个）")
    print(f"仍为 float 的主算子: {fp} 个 Conv/MatMul")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
