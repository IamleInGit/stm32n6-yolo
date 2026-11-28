#!/usr/bin/env python3
"""从 coco128 生成单类 person 数据集 v2：正样本 + 负样本。

和 v1（make_person_dataset.py）的区别：
  v1 只有含 person 的图（61 张）
  v2 把「没有 person 的图」也留下，标签为空文件 —— 也就是**负样本**

为什么需要负样本：
  只有正样本时，模型没见过「没有人」的负例，会把键盘、手、桌面纹理也判成人。
  负样本告诉它「这些场景里没有目标」，是压制误检最直接的手段。

用法：
    python notebooks/make_dataset_v2.py [输出目录]
默认输出 D:\\STM32N6\\yolo-baseline\\datasets\\person_v2
"""

import random
import shutil
import sys
from pathlib import Path

PERSON_CLASS = 0
SPLIT = 0.8
SEED = 0


def main(argv):
    out_root = Path(argv[1]) if len(argv) > 1 else Path(r"D:\STM32N6\yolo-baseline\datasets\person_v2")

    from ultralytics.data.utils import check_det_dataset

    info = check_det_dataset("coco128.yaml")
    src_root = Path(info["path"])
    img_dir = src_root / "images" / "train2017"
    lbl_dir = src_root / "labels" / "train2017"

    print(f"coco128: {src_root}")

    items = []          # [(img_path, [label lines])]
    n_pos = n_neg = n_box = 0
    for lbl in sorted(lbl_dir.glob("*.txt")):
        lines = []
        for raw in lbl.read_text(encoding="utf-8").splitlines():
            parts = raw.split()
            if len(parts) == 5 and int(parts[0]) == PERSON_CLASS:
                lines.append("0 " + " ".join(parts[1:]))
        img = img_dir / (lbl.stem + ".jpg")
        if not img.exists():
            continue
        items.append((img, lines))
        if lines:
            n_pos += 1
            n_box += len(lines)
        else:
            n_neg += 1

    print(f"  正样本(含 person): {n_pos} 张 / {n_box} 个框")
    print(f"  负样本(无 person): {n_neg} 张（标签留空）")

    # 负样本只保留一小部分：占比过高会让模型偏向"无目标"，召回骤降
    MAX_NEG = 20
    pos_items = [it for it in items if it[1]]
    neg_items = [it for it in items if not it[1]]
    rng = random.Random(SEED)
    rng.shuffle(neg_items)
    if len(neg_items) > MAX_NEG:
        print(f"  负样本上限 {MAX_NEG} 张（原 {len(neg_items)} 张），避免比例失衡")
        neg_items = neg_items[:MAX_NEG]
    items = pos_items + neg_items

    random.Random(SEED).shuffle(items)
    n_train = int(len(items) * SPLIT)
    splits = {"train": items[:n_train], "val": items[n_train:]}

    # 必须清空旧输出：否则上一次生成的图会残留，导致同一张图同时出现在 train/val（数据泄漏）
    if out_root.exists():
        for stale in ("images", "labels"):
            p = out_root / stale
            if p.exists():
                shutil.rmtree(p)
                print(f"  已清空旧目录: {p.name}/")

    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out_root / sub).mkdir(parents=True, exist_ok=True)

    for split, rows in splits.items():
        pos = sum(1 for _, l in rows if l)
        for img, lines in rows:
            shutil.copy2(img, out_root / "images" / split / img.name)
            (out_root / "labels" / split / (img.stem + ".txt")).write_text(
                ("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
        print(f"  {split}: {len(rows)} 张（其中正样本 {pos}）")

    yaml_path = out_root / "person_v2.yaml"
    yaml_path.write_text(
        f"path: {out_root.as_posix()}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: 1\n"
        f"names: ['person']\n",
        encoding="utf-8")
    print(f"\n数据集: {out_root}")
    print(f"配置  : {yaml_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main(sys.argv))
