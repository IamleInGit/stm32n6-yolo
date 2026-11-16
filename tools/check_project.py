#!/usr/bin/env python3
"""工程链接体检：不装 CubeIDE 也能提前发现"导入后编不过"。

STM32N6 例程用两种方式引用外部依赖，失效表现完全不同，所以分开报：

  [硬错误] .project 的 linkedResources
           <locationURI>PARENT-5-PROJECT_LOC/STM32Cube_FW_N6_V1.0.0/...</locationURI>
           → 这些是真正的编译单元，缺了必然 undefined reference，工程直接废掉。

  [软警告] .cproject 的 Include paths (-I) 里的相对路径
           ../../../../../../STM32Cube_FW_N6_V1.0.0/Drivers/STM32N6xx_HAL_Driver/Inc
           → 注意：CubeIDE 传给编译器的相对 -I，工作目录是**构建配置目录**
             （<工程>/Debug/），不是工程根目录。所以判断基准要按 Debug/ 算，
             否则会得出"路径全错、需要修改工程"的错误结论。
           → GCC 对不存在的 -I 是静默忽略，不一定报错；但一旦报
             "找不到 stm32n6xx_hal.h"，这里就是第一嫌疑点。

以 ${workspace_loc} 开头的属于 Eclipse 虚拟文件夹（linked resource 映射出来的），
磁盘上本来就不存在，一律跳过，不算问题。

用法：
    python tools/check_project.py <含 .project 的目录> [<目录2> ...]
退出码：有硬错误返回 1，只有软警告返回 0。
"""

import os
import re
import sys
import xml.etree.ElementTree as ET

PARENT_RE = re.compile(r"^PARENT-(\d+)-PROJECT_LOC/(.*)$")
PROJECT_RE = re.compile(r"^PROJECT_LOC/(.*)$")

# CubeIDE 的构建配置目录名。相对 -I 以它们为工作目录解析。
BUILD_DIRS = ("Debug", "Release")


def resolve_uri(uri, proj_dir):
    m = PARENT_RE.match(uri)
    if m:
        base = proj_dir
        for _ in range(int(m.group(1))):
            base = os.path.dirname(base)
        return os.path.normpath(os.path.join(base, m.group(2)))
    m = PROJECT_RE.match(uri)
    if m:
        return os.path.normpath(os.path.join(proj_dir, m.group(1)))
    return None


def collect_links(project_file):
    root = ET.parse(project_file).getroot()
    links = []
    for link in root.iter("link"):
        uri = link.findtext("locationURI")
        if not uri:
            continue
        links.append((link.findtext("name") or "?", uri, link.findtext("type") or "1"))
    return links


def collect_include_paths(cproject_file):
    """只取 includepaths 选项下的 listOptionValue，避开 defaults 那串配置 blob。"""
    if not os.path.isfile(cproject_file):
        return []
    root = ET.parse(cproject_file).getroot()
    out = []
    for opt in root.iter("option"):
        if not (opt.get("superClass") or "").endswith("includepaths"):
            continue
        for val in opt.iter("listOptionValue"):
            raw = (val.get("value") or "").strip()
            if raw:
                out.append(raw)
    return sorted(set(out))


def check_project(proj_dir):
    proj_dir = os.path.abspath(proj_dir)
    project_file = os.path.join(proj_dir, ".project")

    print(f"\n=== {proj_dir}")
    if not os.path.isfile(project_file):
        print("  [X] 没有 .project，这不是 CubeIDE 工程目录")
        return 1

    hard = 0

    links = collect_links(project_file)
    bad_links = []
    for name, uri, _ in links:
        path = resolve_uri(uri, proj_dir)
        if path is None:
            continue  # VIRTUAL/其他 URI 形式，跳过
        if not os.path.exists(path):
            bad_links.append((name, path))

    print(f"  [硬] 链接资源 {len(links)} 项，缺失 {len(bad_links)} 项")
    for name, path in bad_links:
        print(f"        [X] {name}")
        print(f"            → {path}")
    hard += len(bad_links)

    incs = collect_include_paths(os.path.join(proj_dir, ".cproject"))
    soft = []
    skipped = 0
    via_build_dir = 0
    for inc in incs:
        if "${workspace_loc}" in inc or inc.startswith("${"):
            skipped += 1
            continue
        if not inc.startswith(".."):
            continue
        # 先按工程根目录算，再按构建配置目录算（CubeIDE 的真实工作目录）
        candidates = [proj_dir] + [os.path.join(proj_dir, c) for c in BUILD_DIRS]
        hit = None
        for base in candidates:
            path = os.path.normpath(os.path.join(base, inc))
            if os.path.exists(path):
                hit = (path, base)
                break
        if hit is None:
            soft.append((inc, os.path.normpath(os.path.join(proj_dir, inc))))
        elif hit[1] != proj_dir:
            via_build_dir += 1

    print(f"  [软] 相对 include {len(incs)} 条，缺失 {len(soft)} 条"
          f"（跳过 {skipped} 条 workspace_loc 虚拟路径；"
          f"{via_build_dir} 条按构建目录 Debug/Release 解析成立）")
    for inc, path in soft:
        ups = inc.count("../")
        print(f"        [!] 退 {ups} 级 → {path}")

    if soft:
        print("        → 修复思路：按 <工程>/Debug/ 为基准核对层级，不要把对的改错。")

    if hard:
        print("  ⇒ 有硬错误：工程必然编译失败。多半是例程被拷出了 SoftwarePackage，层级断了。")
        return 1
    print("  ⇒ 链接资源全部可达，工程骨架完好。")
    if soft:
        print("  ⇒ 仅 include 路径有偏差，GCC 会静默忽略；若报找不到 HAL 头文件，优先修这里。")
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    rc = 0
    for arg in argv[1:]:
        rc |= check_project(arg)
    return rc


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main(sys.argv))
