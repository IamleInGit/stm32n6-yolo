#!/usr/bin/env python3
"""在卷积头处截断 YOLOv8 ONNX，并做数值校验。

动机：
  ultralytics 默认导出的 ONNX 已经包含"解码"（DFL Softmax + anchor 还原 + 拼接），
  输出是 [1, 4+nc, N] 的最终框。这带来两个问题：
    1. 解码路径里的 Sub/Div/Softmax 对量化极其敏感（阶段 2 实测：全量量化精度崩掉）
    2. 而 ST 的参考实现本来就把解码 + NMS 放在 C 代码里，模型只该输出原始头

  所以：把图截断到两个卷积头
      /model.22/Concat    → box  logits  [1, 4*reg_max, N]
      /model.22/Concat_1  → cls  logits  [1, nc, N]
  解码交给下游（MCU 的 C 代码 / 这里的 numpy 参考实现）。

用法：
    python notebooks/head_onnx.py extract <full.onnx> <head.onnx>
    python notebooks/head_onnx.py check   <full.onnx> <head.onnx> [head_int8.onnx]
"""

import sys

import numpy as np

STRIDES = (8, 16, 32)
REG_MAX = 16


def make_anchors(imgsz, strides=STRIDES):
    """复现 ultralytics 的 make_anchors：返回 (N,2) 的网格中心（单位=网格）。"""
    pts = []
    for s in strides:
        h = w = imgsz // s
        sx = np.arange(w, dtype=np.float32) + 0.5
        sy = np.arange(h, dtype=np.float32) + 0.5
        gx, gy = np.meshgrid(sx, sy)
        pts.append(np.stack([gx.ravel(), gy.ravel()], 1))
    return np.concatenate(pts, 0)


def stride_of_anchor(imgsz, strides=STRIDES):
    out = []
    for s in strides:
        out.append(np.full((imgsz // s) ** 2, s, dtype=np.float32))
    return np.concatenate(out)


def dfl_decode(box_raw, cls_raw, imgsz):
    """原始头 → [1, 4+nc, N]（xywh 像素坐标 + 类别概率），与 ultralytics 输出对齐。"""
    # box_raw: [1, 4*reg_max, N] → [1, 4, reg_max, N]
    b = box_raw.reshape(1, 4, REG_MAX, -1)
    # 在 reg_max 维上做 softmax，再按 0..reg_max-1 加权求和 → 距离
    e = np.exp(b - b.max(axis=2, keepdims=True))
    soft = e / e.sum(axis=2, keepdims=True)
    dist = (soft * np.arange(REG_MAX, dtype=np.float32).reshape(1, 1, REG_MAX, 1)).sum(axis=2)

    anchors = make_anchors(imgsz)[None, :, :].transpose(0, 2, 1)   # [1,2,N]
    lt, rb = dist[:, 0:2, :], dist[:, 2:4, :]
    x1y1 = anchors - lt
    x2y2 = anchors + rb
    c_xy = (x1y1 + x2y2) / 2.0
    wh = x2y2 - x1y1
    boxes = np.concatenate([c_xy, wh], 1) * stride_of_anchor(imgsz)[None, None, :]

    cls = 1.0 / (1.0 + np.exp(-cls_raw))
    return np.concatenate([boxes, cls], 1)


def extract(full_path, head_path):
    import onnx
    from onnx.utils import extract_model

    m = onnx.load(full_path)
    outputs = []
    for target in ("/model.22/Concat", "/model.22/Concat_1"):
        node = next((n for n in m.graph.node if n.name == target), None)
        if node is None:
            raise SystemExit(f"找不到节点 {target}")
        outputs.append(node.output[0])
    print("截断输出:", outputs)

    extract_model(full_path, head_path,
                  input_names=[m.graph.input[0].name], output_names=outputs)
    h = onnx.load(head_path)
    import os
    print(f"已生成: {head_path}  ({os.path.getsize(head_path)/1024/1024:.2f} MB, "
          f"{len(h.graph.node)} 节点)")
    for o in h.graph.output:
        dims = [d.dim_value for d in o.type.tensor_type.shape.dim]
        print(f"  输出 {o.name}: {dims}  = {int(np.prod(dims))} 元素")
    return head_path


def _run(model_path, x):
    import onnxruntime as ort
    s = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    return s.run(None, {s.get_inputs()[0].name: x})


def _prep(img_path, imgsz=224):
    import cv2
    if img_path:
        img = cv2.imread(str(img_path))
        if img is None:
            raise SystemExit(f"读不了图: {img_path}")
        h, w = img.shape[:2]
        r = min(imgsz / h, imgsz / w)
        nh, nw = int(round(h * r)), int(round(w * r))
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((imgsz, imgsz, 3), 114, np.uint8)
        top, left = (imgsz - nh) // 2, (imgsz - nw) // 2
        canvas[top:top + nh, left:left + nw] = img
        img = canvas
    else:
        img = np.full((imgsz, imgsz, 3), 128, np.uint8)
    x = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return np.transpose(x, (2, 0, 1))[None].copy()


def check(full_path, head_path, int8_path=None, img_path=None):
    x = _prep(img_path)
    print(f"测试图: {img_path or '(纯灰)'}")

    ref = _run(full_path, x)[0]
    heads = _run(head_path, x)
    dec = dfl_decode(heads[0], heads[1], 224)
    print(f"\n完整模型输出 {ref.shape} / 截断+解码 {dec.shape}")
    err = np.abs(ref - dec)
    print(f"与完整模型的差异: max {err.max():.6f}  mean {err.mean():.6f}")

    if int8_path:
        h8 = _run(int8_path, x)
        dec8 = dfl_decode(h8[0], h8[1], 224)
        # 比较原始头（fp32 vs int8）
        for i, tag in enumerate(("box", "cls")):
            d = np.abs(heads[i] - h8[i])
            print(f"  {tag} 原始头 fp32 vs int8: max {d.max():.4f} mean {d.mean():.4f} "
                  f"(量程 {heads[i].min():.2f}~{heads[i].max():.2f})")
        e8 = np.abs(ref - dec8)
        print(f"解码后 fp32 vs int8: max {e8.max():.3f}px  mean {e8.mean():.3f}px")
        # 框中心偏移（只统计有目标的锚点）
        mask = ref[:, 4:, :].max(axis=1)[0] > 0.25
        if mask.any():
            dc = np.abs(ref[0, 0:2, mask] - dec8[0, 0:2, mask])
            dw = np.abs(ref[0, 2:4, mask] - dec8[0, 2:4, mask])
            print(f"  置信度>0.25 的 {mask.sum()} 个锚点: 中心偏移 mean {dc.mean():.3f}px，"
                  f"宽高偏移 mean {dw.mean():.3f}px")


def sweep(full_path, head_path, int8_path, img_dir):
    """在整目录上统计 int8 截断模型相对 fp32 完整模型的框偏移。"""
    import glob
    import os

    paths = sorted(glob.glob(os.path.join(img_dir, "*.jpg")) +
                   glob.glob(os.path.join(img_dir, "*.png")))
    if not paths:
        raise SystemExit(f"目录里没有图: {img_dir}")

    print(f"扫描 {len(paths)} 张图 @ {img_dir}\n")
    print(f'{"image":<22}{"conf>0.25":>10}{"中心偏移":>10}{"最大偏移":>10}{"conf>0.5":>10}')
    all_mean, all_n, worst = 0.0, 0, 0.0
    for p in paths:
        x = _prep(p)
        ref = _run(full_path, x)[0]
        dec8 = dfl_decode(*_run(int8_path, x), 224)
        conf = ref[:, 4:, :].max(axis=1)[0]
        m = conf > 0.25
        n = int(m.sum())
        if n:
            d = np.abs(ref[0, 0:2, m] - dec8[0, 0:2, m])
            mean_d = float(d.mean())
            worst = max(worst, float(d.max()))
            all_mean += mean_d * n
            all_n += n
            print(f"{os.path.basename(p):<22}{n:>10}{mean_d:>10.3f}{d.max():>10.3f}{int((conf > 0.5).sum()):>10}")
        else:
            print(f"{os.path.basename(p):<22}{0:>10}{'-':>10}{'-':>10}{0:>10}")

    if all_n:
        print(f"\n合计 {all_n} 个高置信锚点：加权平均中心偏移 "
              f"{all_mean / all_n:.3f} px，最坏 {worst:.3f} px（图幅 224 px）")
    else:
        print("\n没有高置信检测，指标无意义")


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    cmd, full, head = sys.argv[1], sys.argv[2], sys.argv[3]
    if cmd == "extract":
        extract(full, head)
    elif cmd == "check":
        check(full, head,
              sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None,
              sys.argv[5] if len(sys.argv) > 5 else None)
    elif cmd == "sweep":
        if len(sys.argv) < 6:
            print(__doc__)
            return 2
        sweep(full, head, sys.argv[4], sys.argv[5])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
