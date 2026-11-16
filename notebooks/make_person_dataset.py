#!/usr/bin/env python3
"""从 coco128 生成单类 person 数据集（YOLO 格式）。

为什么需要：板上要跑的是"人检测"，1 类。而 COCO 是 80 类，
80 类模型的输出是 [1, 84, N]，光输出 buffer 就 345 KB；
单类是 [1, 5, N]，只有 20 KB。差 17 倍，N647 的 2 MB SRAM 经不起这个浪费。

做法：
  1. 用 ultralytics 自带的 coco128（128 张真图 + 真标注，自动下载）
  2. 只保留 class 0（person），重映射为 0，丢掉其余 79 类的框
  3. 没有 person 的图整张丢掉（小数据集里负样本只会拖慢收敛）
  4. 按 80/20 切 train/val，生成 data.yaml

用法：
    python notebooks/make_person_dataset.py [输出目录]

输出目录默认 D:\\STM32N6\\yolo-baseline\\datasets\\person128
"""

import random
import shutil
import sys
from pathlib import Path

PERSON_CLASS = 0
SPLIT = 0.8
SEED = 0


def main(argv):
    out_root = Path(argv[1]) if len(argv) > 1 else Path(r"D:\STM32N6\yolo-baseline\datasets\person128")

    from ultralytics.data.utils import check_det_dataset

    info = check_det_dataset("coco128.yaml")
    src_root = Path(info["path"])
    img_dir = src_root / "images" / "train2017"
    lbl_dir = src_root / "labels" / "train2017"

    print(f"coco128 位置: {src_root}")
    print(f"  图片: {len(list(img_dir.glob('*.jpg')))} 张")

    kept, dropped, boxes = [], 0, 0
    for lbl in sorted(lbl_dir.glob("*.txt")):
        lines = []
        for raw in lbl.read_text(encoding="utf-8").splitlines():
            parts = raw.split()
            if len(parts) != 5:
                continue
            if int(parts[0]) != PERSON_CLASS:
                continue
            lines.append("0 " + " ".join(parts[1:]))
        img = img_dir / (lbl.stem + ".jpg")
        if not img.exists():
            continue
        if lines:
            kept.append((img, lines))
            boxes += len(lines)
        else:
            dropped += 1

    print(f"  含 person 的图: {len(kept)} 张，共 {boxes} 个框")
    print(f"  无 person 丢弃: {dropped} 张")

    random.Random(SEED).shuffle(kept)
    n_train = int(len(kept) * SPLIT)
    splits = {"train": kept[:n_train], "val": kept[n_train:]}

    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out_root / sub).mkdir(parents=True, exist_ok=True)

    for split, items in splits.items():
        for img, lines in items:
            shutil.copy2(img, out_root / "images" / split / img.name)
            (out_root / "labels" / split / (img.stem + ".txt")).write_text(
                "\n".join(lines) + "\n", encoding="utf-8")
        print(f"  {split}: {len(items)} 张")

    yaml_path = out_root / "person128.yaml"
    yaml_path.write_text(
        f"path: {out_root.as_posix()}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: 1\n"
        f"names: ['person']\n",
        encoding="utf-8")

    print(f"\n数据集已生成: {out_root}")
    print(f"配置: {yaml_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main(sys.argv))
