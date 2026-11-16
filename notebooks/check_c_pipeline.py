#!/usr/bin/env python3
"""端到端验证：C 版 decode+NMS vs ultralytics 全流程。

对比的两条路：
  A. 完整 ONNX 输出 [1,4+nc,N] → ultralytics non_max_suppression   （参考）
  B. 原始头 ONNX 输出 box/cls → C 的 yolo_v8_decode + yolo_v8_nms   （固件链路）

用法：
    python notebooks/check_c_pipeline.py <head.onnx> <full.onnx> <图片目录> <test_pipeline.exe> [imgsz] [conf] [iou] [max_det]
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from head_onnx import _prep, _run  # noqa: E402
from check_c_nms import iou_xyxy, ref_nms  # noqa: E402


def main(argv):
    if len(argv) < 5:
        print(__doc__)
        return 2
    head_onnx, full_onnx, img_dir, exe = argv[1], argv[2], Path(argv[3]), argv[4]
    imgsz = int(argv[5]) if len(argv) > 5 else 224
    conf = float(argv[6]) if len(argv) > 6 else 0.25
    iou = float(argv[7]) if len(argv) > 7 else 0.45
    max_det = int(argv[8]) if len(argv) > 8 else 30

    import onnx

    g = onnx.load(full_onnx).graph
    n_classes = g.output[0].type.tensor_type.shape.dim[1].dim_value - 4
    n_anchors = g.output[0].type.tensor_type.shape.dim[2].dim_value
    print(f"nc={n_classes} na={n_anchors} conf={conf} iou={iou} max_det={max_det}")

    imgs = sorted(list(img_dir.glob("*.jpg")) + list(img_dir.glob("*.png")))
    tmp = Path(tempfile.mkdtemp(prefix="yv8p_"))

    tot_ref = tot_c = tot_m = tot_m50 = 0
    worst_iou, worst_score = 1.0, 0.0
    print(f"\n{'image':<22}{'参考':>6}{'C链路':>7}{'IoU>.99':>9}{'IoU>.5':>8}{'最小IoU':>10}")
    for p in imgs:
        x = _prep(p, imgsz)

        # A: 参考路径
        pred_full = _run(full_onnx, x)[0]
        det_ref = ref_nms(pred_full, conf, iou, max_det)

        # B: 固件链路
        box, cls = _run(head_onnx, x)
        (tmp / "box.bin").write_bytes(np.ascontiguousarray(box, np.float32).tobytes())
        (tmp / "cls.bin").write_bytes(np.ascontiguousarray(cls, np.float32).tobytes())
        r = subprocess.run([exe, str(tmp / "box.bin"), str(tmp / "cls.bin"), str(tmp / "out.txt"),
                            str(imgsz), str(n_classes), str(conf), str(iou), str(max_det)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("  C 链路失败:", r.stderr.strip())
            return 3
        txt = (tmp / "out.txt").read_text().strip()
        det_c = np.array([[float(v) for v in ln.split()] for ln in txt.splitlines()],
                         np.float32) if txt else np.zeros((0, 6), np.float32)

        m, min_iou = 0, 1.0
        m50 = 0
        for d in det_c:
            best_iou = 0.0
            best = -1
            for j, e in enumerate(det_ref):
                v = iou_xyxy(d[:4], e[:4])
                if v > best_iou:
                    best_iou, best = v, j
            if best_iou > 0.5:
                m50 += 1
            if best_iou > 0.99:
                m += 1
                min_iou = min(min_iou, best_iou)
                worst_score = max(worst_score, abs(float(d[4]) - float(det_ref[best][4])))
        tot_ref += len(det_ref)
        tot_c += len(det_c)
        tot_m += m
        tot_m50 += m50
        if m:
            worst_iou = min(worst_iou, min_iou)
        print(f"{p.name:<22}{len(det_ref):>6}{len(det_c):>7}{m:>6}{m50:>7}{min_iou:>10.4f}")

    print(f"\n合计: 参考 {tot_ref} / C链路 {tot_c} / IoU>.99 {tot_m} / IoU>.5 {tot_m50}")
    print(f"最小 IoU {worst_iou:.5f}，最大分数差 {worst_score:.6f}")
    if tot_ref == tot_c == tot_m:
        print("✅ 端到端一致：原始头 → C 解码 → C NMS == ultralytics 全流程")
    else:
        print("⚠ 存在差异")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main(sys.argv))
