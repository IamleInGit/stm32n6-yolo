"""同一批图片在不同输入分辨率下跑一次，输出对比表和带标注的结果图。

用途：判断 256×256 够不够用——如果 256 下你自己都认不出目标，模型也一样。

用法：
    python tools/bench_imgsz.py --source ./my_photos --imgsz 256 320
    python tools/bench_imgsz.py --weights yolov8n.pt --source ./datasets/coco8/images/val
"""

import argparse
import time
from pathlib import Path

from ultralytics import YOLO

IMG_SUFFIX = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", default="yolov8n.pt", help="权重文件")
    parser.add_argument("--source", required=True, help="图片目录")
    parser.add_argument("--imgsz", type=int, nargs="+", default=[256, 320], help="待测试的分辨率")
    parser.add_argument("--out", default="results/bench", help="输出目录")
    parser.add_argument("--conf", type=float, default=0.25, help="置信度阈值")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"目录不存在：{source}")
        return 1
    images = [p for p in source.rglob("*") if p.suffix.lower() in IMG_SUFFIX]
    if not images:
        print(f"目录里没有图片：{source}")
        return 1

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"权重 {args.weights} / 图片 {len(images)} 张 / 阈值 {args.conf}")
    model = YOLO(args.weights)

    rows = []
    for size in args.imgsz:
        start = time.perf_counter()
        results = model.predict(
            source=str(source),
            imgsz=size,
            conf=args.conf,
            save=True,
            project=str(outdir),
            name=f"imgsz{size}",
            exist_ok=True,
            verbose=False,
        )
        elapsed = (time.perf_counter() - start) * 1000 / max(len(results), 1)
        boxes = sum(len(r.boxes) for r in results if r.boxes is not None)
        rows.append((size, len(results), boxes, elapsed))
        print(f"  imgsz={size:<4} 框 {boxes:<4} 平均 {elapsed:6.0f} ms/张（含预处理，仅作横向对比）")

    table = ["| imgsz | 图片数 | 检测框总数 | 平均耗时 ms |", "|---|---|---|---|"]
    table += [f"| {s} | {n} | {b} | {c:.0f} |" for s, n, b, c in rows]
    summary = outdir / "summary.md"
    summary.write_text("\n".join(table) + "\n", encoding="utf-8")

    print(f"\n结果图与汇总：{summary.resolve()}")
    print("看什么：框是否贴合、是否漏检、小目标是否消失。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
