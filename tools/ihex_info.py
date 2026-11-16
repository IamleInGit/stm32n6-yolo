#!/usr/bin/env python3
"""Intel HEX 镜像体检工具。

用途：不装任何 ST 工具，也能回答三个问题
  1. 这个 hex 烧到哪个地址段？（决定会不会踩到别的区域）
  2. 总共占多少字节、有没有空洞？
  3. 放得进 16 MB / 32 MB 的外部 Flash 吗？

用法：
    python tools/ihex_info.py <file.hex> [--base 0x70000000] [--flash 16M|32M]

只用标准库，Python 3.8+ 均可。
"""

import sys
import os

RECORD_NAMES = {
    0x00: "DATA",
    0x01: "EOF",
    0x02: "EXT_SEG_ADDR",
    0x03: "START_SEG_ADDR",
    0x04: "EXT_LIN_ADDR",
    0x05: "START_LIN_ADDR",
}


def parse_hex(path):
    """返回 (payload_bytes, merged_segments, rectype_counts, first_bytes)。"""
    base = 0
    segs = []
    total = 0
    counts = {}
    first = b""
    with open(path, "r", encoding="ascii", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            if not line.startswith(":"):
                raise ValueError(f"{path}:{lineno} 不是 Intel HEX 记录: {line[:40]!r}")
            try:
                raw = bytes.fromhex(line[1:])
            except ValueError as exc:
                raise ValueError(f"{path}:{lineno} 十六进制解析失败: {exc}") from exc
            if len(raw) < 5:
                continue
            length, addr, rtype = raw[0], (raw[1] << 8) | raw[2], raw[3]
            data = raw[4:4 + length]
            counts[rtype] = counts.get(rtype, 0) + 1

            if rtype == 0x00:
                start = base + addr
                segs.append((start, start + length))
                total += length
                if not first:
                    first = data[:32]
            elif rtype == 0x01:
                break
            elif rtype == 0x02:
                base = ((data[0] << 8) | data[1]) << 4
            elif rtype == 0x04:
                base = ((data[0] << 8) | data[1]) << 16
            # 0x03 / 0x05 只是入口地址，不影响布局

    segs.sort()
    merged = []
    for start, end in segs:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return total, merged, counts, first


def parse_size(text):
    text = text.strip().upper()
    mult = 1
    for suffix, factor in (("M", 1024 ** 2), ("K", 1024)):
        if text.endswith(suffix):
            mult, text = factor, text[:-1]
            break
    return int(text, 0) * mult


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    path = argv[1]
    flash_base = 0x70000000
    flash_size = None
    args = argv[2:]
    for i, arg in enumerate(args):
        if arg == "--base" and i + 1 < len(args):
            flash_base = int(args[i + 1], 0)
        elif arg == "--flash" and i + 1 < len(args):
            flash_size = parse_size(args[i + 1])

    if not os.path.isfile(path):
        print(f"找不到文件: {path}")
        return 2

    total, segs, counts, first = parse_hex(path)
    lo = segs[0][0]
    hi = segs[-1][1]

    print(f"文件      : {os.path.basename(path)}")
    print(f"文件大小  : {human(os.path.getsize(path))}")
    print(f"有效载荷  : {human(total)}  ({total} 字节)")
    print(f"地址范围  : 0x{lo:08X} .. 0x{hi:08X}  (跨度 {human(hi - lo)})")
    print(f"段数      : {len(segs)}")
    print(f"记录类型  : " + ", ".join(
        f"{RECORD_NAMES.get(k, hex(k))}×{v}" for k, v in sorted(counts.items())))

    if len(segs) > 1:
        gaps = sum(segs[i + 1][0] - segs[i][1] for i in range(len(segs) - 1))
        print(f"空洞      : {human(gaps)}（未写入的间隙，属正常，但会拖慢烧录）")
    print(f"起始字节  : {first.hex(' ')}")
    if len(first) >= 8:
        sp = int.from_bytes(first[0:4], "little")
        pc = int.from_bytes(first[4:8], "little")
        plausible = 0x30000000 <= sp <= 0x40000000 and (pc & 1) == 1
        print(f"  → 首 4 字节当 SP 解释: 0x{sp:08X}，次 4 字节当 PC: 0x{pc:08X}"
              f"  {'（像 ARM 向量表 → 未签名裸镜像）' if plausible else '（不像向量表 → 可能是已签名镜像或非 ARM 镜像）'}")

    if flash_size:
        end = flash_base + flash_size
        print()
        print(f"Flash 容量校验（基址 0x{flash_base:08X}，{human(flash_size)}）")
        print(f"  芯片末地址: 0x{end:08X}")
        if lo < flash_base:
            print(f"  [X] 起始地址 0x{lo:08X} 低于 Flash 基址，写不进去")
        elif hi > end:
            print(f"  [X] 溢出 {human(hi - end)}，放不下")
        else:
            print(f"  [OK] 放得下，剩余 {human(end - hi)}")
        used = (hi - lo) / flash_size * 100
        print(f"  占用率: {used:.1f}%")
    return 0


if __name__ == "__main__":
    # Windows 控制台默认 GBK，输出中文会乱码；统一走 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main(sys.argv))
