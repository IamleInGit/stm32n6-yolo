#!/usr/bin/env python3
"""验证融合后处理：yolo_v8_postprocess() 必须与"两步法"逐框等价，并且更快。

对比三条：
  A. ultralytics 全流程（参考）
  B. 两步法：yolo_v8_decode() → yolo_v8_nms()
  C. 融合法：yolo_v8_postprocess()

用法：
    python notebooks/check_c_fused.py <head.onnx> <full.onnx> <图片目录> <test_pipeline.exe> <test_post.exe> [imgsz] [conf] [iou] [max_det]
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from head_onnx import _prep, _run  # noqa: E402
from check_c_nms import iou_xyxy, ref_nms  # noqa: E402


def parse(path):
    txt = Path(path).read_text().strip()
    if not txt:
        return np.zeros((0, 6), np.float32)
    return np.array([[float(v) for v in ln.split()] for ln in txt.splitlines()], np.float32)


def run(exe, box, cls, out, imgsz, nc, conf, iou, max_det, iters=None):
    args = [exe, box, cls, out, str(imgsz), str(nc), str(conf), str(iou), str(max_det)]
    if iters:
        args.append(str(iters))
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return parse(out), r.stdout.strip()


def main(argv):
    if len(argv) < 6:
        print(__doc__)
        return 2
    head_onnx, full_onnx, img_dir = argv[1], argv[2], Path(argv[3])
    exe2, exe1 = argv[4], argv[5]
    imgsz = int(argv[6]) if len(argv) > 6 else 224
    conf = float(argv[7]) if len(argv) > 7 else 0.25
    iou = float(argv[8]) if len(argv) > 8 else 0.45
    max_det = int(argv[9]) if len(argv) > 9 else 30

    import onnx

    g = onnx.load(full_onnx).graph
    nc = g.output[0].type.tensor_type.shape.dim[1].dim_value - 4

    imgs = sorted(list(img_dir.glob("*.jpg")) + list(img_dir.glob("*.png")))
    tmp = Path(tempfile.mkdtemp(prefix="yv8f_"))

    max_dc, max_dr = 0.0, 0.0
    tot = {"ref": 0, "two": 0, "fus": 0, "two_match": 0, "fus_match": 0}
    print(f"{'image':<22}{'参考':>6}{'两步':>6}{'融合':>6}{'两步==融合':>12}")
    for p in imgs:
        x = _prep(p)
        det_ref = ref_nms(_run(full_onnx, x)[0], conf, iou, max_det)
        box, cls = _run(head_onnx, x)
        (tmp / "b.bin").write_bytes(np.ascontiguousarray(box, np.float32).tobytes())
        (tmp / "c.bin").write_bytes(np.ascontiguousarray(cls, np.float32).tobytes())

        d_two, _ = run(exe2, str(tmp / "b.bin"), str(tmp / "c.bin"), str(tmp / "two.txt"),
                       imgsz, nc, conf, iou, max_det)
        d_fus, _ = run(exe1, str(tmp / "b.bin"), str(tmp / "c.bin"), str(tmp / "fus.txt"),
                       imgsz, nc, conf, iou, max_det)

        # 融合 vs 两步：应逐位一致
        same = "是" if (len(d_two) == len(d_fus) and
                        (len(d_two) == 0 or np.abs(d_two - d_fus).max() < 1e-6)) else "否"
        if len(d_two) and len(d_fus) == len(d_two):
            max_dc = max(max_dc, float(np.abs(d_two - d_fus).max()))

        def count_match(det):
            m = 0
            for d in det:
                if any(iou_xyxy(d[:4], e[:4]) > 0.5 for e in det_ref):
                    m += 1
            return m

        tot["ref"] += len(det_ref)
        tot["two"] += len(d_two)
        tot["fus"] += len(d_fus)
        tot["two_match"] += count_match(d_two)
        tot["fus_match"] += count_match(d_fus)
        print(f"{p.name:<22}{len(det_ref):>6}{len(d_two):>6}{len(d_fus):>6}{same:>12}")

    print(f"\n合计 参考 {tot['ref']} / 两步 {tot['two']} / 融合 {tot['fus']}")
    print(f"两步法与参考 IoU>0.5 匹配 {tot['two_match']}，融合法 {tot['fus_match']}")
    print(f"两步 vs 融合 最大差值 {max_dc:.9f}")
    if tot["two"] == tot["fus"] and max_dc < 1e-6:
        print("✅ 融合后处理与两步法完全等价")

    # 耗时对比（用最后一张图的输入，各跑 300 次）
    print("\n--- 主机端耗时（300 次平均）---")
    _, out2 = run(exe2, str(tmp / "b.bin"), str(tmp / "c.bin"), str(tmp / "two.txt"),
                  imgsz, nc, conf, iou, max_det, 300)
    _, out1 = run(exe1, str(tmp / "b.bin"), str(tmp / "c.bin"), str(tmp / "fus.txt"),
                  imgsz, nc, conf, iou, max_det, 300)
    print("两步法:", out2.splitlines()[0] if out2 else "?")
    print("融合法:", out1.splitlines()[0] if out1 else "?")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main(sys.argv))
