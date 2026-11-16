#!/usr/bin/env python3
"""用真实模型张量校验 C 版解码，与 numpy 参考实现逐值比对。

流程：
  对每张图 → onnxruntime 跑"原始头"模型 → 拿到 box/cls logits
  → 存成二进制 → 交给 C 版解码 → 读回结果
  → 同时用 numpy 参考实现算一遍 → 比差异

用法：
    python notebooks/check_c_decode.py <head.onnx> <图片目录> <test_decode.exe> [imgsz]

依赖：onnxruntime, numpy, opencv（venv 里都有）
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from head_onnx import _prep, _run, dfl_decode  # noqa: E402


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2

    model, img_dir, exe = argv[1], Path(argv[2]), argv[3]
    imgsz = int(argv[4]) if len(argv) > 4 else 224

    import onnx

    g = onnx.load(model).graph
    n_classes = g.output[1].type.tensor_type.shape.dim[1].dim_value
    n_anchors = g.output[0].type.tensor_type.shape.dim[2].dim_value
    print(f"模型 {Path(model).name}: n_classes={n_classes}, n_anchors={n_anchors}")

    imgs = sorted(list(img_dir.glob("*.jpg")) + list(img_dir.glob("*.png")))
    if not imgs:
        print("目录里没有图")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="yv8_"))
    worst = 0.0
    total = 0
    print(f"\n{'image':<22}{'最大差异':>12}{'平均差异':>12}")
    for p in imgs:
        x = _prep(p)
        box, cls = _run(model, x)
        box = np.ascontiguousarray(box, dtype=np.float32)
        cls = np.ascontiguousarray(cls, dtype=np.float32)

        (tmp / "box.bin").write_bytes(box.tobytes())
        (tmp / "cls.bin").write_bytes(cls.tobytes())

        r = subprocess.run([exe, str(tmp / "box.bin"), str(tmp / "cls.bin"),
                            str(tmp / "out.bin"), str(imgsz), str(n_classes), str(n_anchors)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  C 解码失败: {r.stderr.strip()}")
            return 3

        out_c = np.fromfile(tmp / "out.bin", dtype=np.float32).reshape(4 + n_classes, n_anchors)
        ref = dfl_decode(box, cls, imgsz)[0]

        diff = np.abs(out_c - ref)
        # 框坐标单位是像素，概率单位是 0~1，分开看更有意义
        box_diff = diff[:4]
        cls_diff = diff[4:]
        worst = max(worst, float(box_diff.max()))
        total += 1
        print(f"{p.name:<22}{box_diff.max():>12.6f}{box_diff.mean():>12.6f}"
              f"   (类别概率 max {cls_diff.max():.6f})")

    print(f"\n{total} 张图，框坐标最大差异 {worst:.6f} px")
    if worst < 1e-4:
        print("✅ C 实现与 numpy 参考一致（< 1e-4）")
    else:
        print("⚠ 差异偏大，检查实现")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main(sys.argv))
