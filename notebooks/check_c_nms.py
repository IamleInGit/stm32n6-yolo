#!/usr/bin/env python3
"""用真实张量校验 C 版 NMS，与 ultralytics 的 non_max_suppression 逐框比对。

用法：
    python notebooks/check_c_nms.py <full.onnx> <图片目录> <test_nms.exe> [imgsz] [conf] [iou] [max_det]
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from head_onnx import _prep, _run  # noqa: E402


def ref_nms(pred, conf, iou, max_det):
    import torch
    try:
        from ultralytics.utils.nms import non_max_suppression
    except ImportError:
        from ultralytics.utils.ops import non_max_suppression
    nc = pred.shape[1] - 4
    arr = np.ascontiguousarray(pred, dtype=np.float32)
    if arr.ndim == 2:            # 单帧 [4+nc, N] 时补 batch 维
        arr = arr[None]
    t = torch.from_numpy(arr)
    out = non_max_suppression(t, conf_thres=conf, iou_thres=iou, max_det=max_det, nc=nc)
    return out[0].cpu().numpy() if len(out) else np.zeros((0, 6), np.float32)


def iou_xyxy(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    model, img_dir, exe = argv[1], Path(argv[2]), argv[3]
    imgsz = int(argv[4]) if len(argv) > 4 else 224
    conf = float(argv[5]) if len(argv) > 5 else 0.25
    iou = float(argv[6]) if len(argv) > 6 else 0.45
    max_det = int(argv[7]) if len(argv) > 7 else 30

    import onnx

    g = onnx.load(model).graph
    n_classes = g.output[0].type.tensor_type.shape.dim[1].dim_value - 4
    n_anchors = g.output[0].type.tensor_type.shape.dim[2].dim_value
    print(f"模型 {Path(model).name}: nc={n_classes}, na={n_anchors}, "
          f"conf={conf}, iou={iou}, max_det={max_det}")

    imgs = sorted(list(img_dir.glob("*.jpg")) + list(img_dir.glob("*.png")))
    tmp = Path(tempfile.mkdtemp(prefix="yv8n_"))

    total_ref = total_c = matched = 0
    worst_iou = 1.0
    worst_score = 0.0
    print(f"\n{'image':<22}{'ultralytics':>12}{'C':>6}{'匹配':>6}{'最小IoU':>10}")
    for p in imgs:
        pred = _run(model, _prep(p, imgsz))[0]
        (tmp / "dec.bin").write_bytes(np.ascontiguousarray(pred, dtype=np.float32).tobytes())

        r = subprocess.run([exe, str(tmp / "dec.bin"), str(tmp / "nms.txt"),
                            str(n_classes), str(n_anchors), str(conf), str(iou), str(max_det)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("  C NMS 失败:", r.stderr.strip())
            return 3
        txt = (tmp / "nms.txt").read_text().strip()
        det_c = np.array([[float(v) for v in line.split()] for line in txt.splitlines()],
                         dtype=np.float32) if txt else np.zeros((0, 6), np.float32)

        det_r = ref_nms(pred, conf, iou, max_det)

        total_ref += len(det_r)
        total_c += len(det_c)

        # 逐个匹配（两边都按分数降序）
        m, min_iou = 0, 1.0
        for d in det_c:
            best, best_iou = -1, 0.0
            for j, e in enumerate(det_r):
                v = iou_xyxy(d[:4], e[:4])
                if v > best_iou:
                    best, best_iou = j, v
            if best_iou > 0.99:
                m += 1
                min_iou = min(min_iou, best_iou)
                worst_score = max(worst_score, abs(float(d[4]) - float(det_r[best][4])))
        matched += m
        if m:
            worst_iou = min(worst_iou, min_iou)
        print(f"{p.name:<22}{len(det_r):>12}{len(det_c):>6}{m:>6}{min_iou:>10.4f}")

    print(f"\n合计: ultralytics {total_ref} 框 / C {total_c} 框 / 成功匹配 {matched}")
    print(f"最小 IoU {worst_iou:.5f}，最大分数差 {worst_score:.6f}")
    if total_ref == total_c == matched:
        print("✅ C 版 NMS 与 ultralytics 完全一致")
    else:
        print("⚠ 存在差异，需要检查")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main(sys.argv))
