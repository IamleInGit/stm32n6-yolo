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
    ap.add_argument("--calib", default="minmax", choices=("minmax", "percentile", "entropy"),
                    help="校准方法；minmax 对离群值最敏感")
    ap.add_argument("--act", default="quint8", choices=("quint8", "qint8"),
                    help="激活量化类型；YOLO 检测头对 uint8 激活较敏感")
    ap.add_argument("--exclude-head", action="store_true",
                    help="把检测头（默认 /model.22 前缀）排除在量化之外，留在 float")
    ap.add_argument("--head-prefix", default="/model.22",
                    help="检测头节点名前缀")
    args = ap.parse_args()

    import onnx
    from onnxruntime.quantization import (CalibrationMethod, QuantFormat, QuantType,
                                          quantize_static)

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

    nodes_to_exclude = None
    if args.exclude_head:
        nodes_to_exclude = [n.name for n in m.graph.node if n.name.startswith(args.head_prefix)]
        print(f"排除检测头: {len(nodes_to_exclude)} 个节点（前缀 {args.head_prefix}）")
        if not nodes_to_exclude:
            heads = sorted({n.name.split("/")[1] for n in m.graph.node if n.name.startswith("/")})
            print(f"  ⚠ 前缀没匹配到任何节点，图里的顶层模块有: {heads[:12]}")

    quantize_static(
        model_input=str(model_path),
        model_output=str(out_path),
        calibration_data_reader=reader,
        quant_format=QuantFormat.QDQ,
        per_channel=True,                 # 对齐 ST modelzoo 的 granularity: per_channel
        activation_type=QuantType.QUInt8 if args.act == "quint8" else QuantType.QInt8,
        weight_type=QuantType.QInt8,       # 权重用 int8
        nodes_to_exclude=nodes_to_exclude,
        calibrate_method={
            "minmax": CalibrationMethod.MinMax,
            "percentile": CalibrationMethod.Percentile,
            "entropy": CalibrationMethod.Entropy,
        }[args.calib],
    )

    src_mb = model_path.stat().st_size / 1024 / 1024
    dst_mb = out_path.stat().st_size / 1024 / 1024
    print(f"\n输出      : {out_path}")
    print(f"体积      : {src_mb:.2f} MB → {dst_mb:.2f} MB（压缩到 {dst_mb / src_mb * 100:.1f}%）")

    # 统计图结构。注意：QDQ 格式下 Conv 节点仍叫 "Conv"，
    # 只是它的输入来自 DequantizeLinear、输出接 QuantizeLinear，
    # 所以**不能**按 op_type 统计"还有多少 Conv 没量化"——那是错的指标。
    q = onnx.load(str(out_path))
    ops = [n.op_type for n in q.graph.node]
    qdq = sum(1 for o in ops if o in ("QuantizeLinear", "DequantizeLinear"))
    conv_integer = sum(1 for o in ops if o == "ConvInteger")
    print(f"节点      : {len(ops)}（Q/DQ 节点 {qdq} 个，ConvInteger {conv_integer} 个）")
    print("说明      : QDQ 模式下 Conv 仍是 float 节点，整数路径由 Q/DQ 包裹实现；")
    print("            真实推理是否全程 int8，要看 STEdgeAI 的报告，不能数节点数。")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
