#!/usr/bin/env python3
"""读 .onnx 的输入/输出张量、opset、算子构成，判断能不能进 ST 的量化流程。

用途：
  1. 导出后第一件事就是核对形状——ST 的 stedgeai 对输入布局敏感
  2. 确认输出是"3 头拼接/单张量"还是 end2end（带 NMS）——
     ST 的后处理库要求**不带 NMS**，end2end=True 导出的模型不能直接用
  3. 统计算子类型，某些算子 N6 NPU 不支持，会回落到 CPU 拖慢推理

用法：
    python tools/onnx_info.py <model.onnx> [更多.onnx]

依赖：pip install onnx
"""

import sys
from collections import Counter

DTYPES = {1: "FLOAT32", 2: "UINT8", 3: "INT8", 6: "INT32", 7: "INT64",
          9: "BOOL", 10: "FLOAT16", 11: "FLOAT64"}


def dims_to_str(dims):
    out = []
    for d in dims:
        if d.HasField("dim_value"):
            out.append(str(d.dim_value))
        elif d.HasField("dim_param") and d.dim_param:
            out.append(d.dim_param)
        else:
            out.append("?")
    return "[" + ", ".join(out) + "]"


def describe(path):
    import onnx

    model = onnx.load(path)
    graph = model.graph

    print(f"\n=== {path}")
    opsets = ", ".join(f"{o.domain or 'ai.onnx'}={o.version}" for o in model.opset_import)
    print(f"  opset      : {opsets}")
    print(f"  IR 版本    : {model.ir_version}")

    initializers = {i.name for i in graph.initializer}
    print(f"  输入:")
    for inp in graph.input:
        if inp.name in initializers:
            continue
        tt = inp.type.tensor_type
        print(f"    {inp.name:<40} {dims_to_str(tt.shape.dim):<20} {DTYPES.get(tt.elem_type, tt.elem_type)}")

    print(f"  输出:")
    for out in graph.output:
        tt = out.type.tensor_type
        shape = dims_to_str(tt.shape.dim)
        elems = 1
        for d in tt.shape.dim:
            if d.HasField("dim_value"):
                elems *= d.dim_value
            else:
                elems = 0
                break
        extra = f"  = {elems} 元素 / {elems * 4} 字节(float32)" if elems else ""
        print(f"    {out.name:<40} {shape:<20} {DTYPES.get(tt.elem_type, tt.elem_type)}{extra}")

    ops = Counter(n.op_type for n in graph.node)
    print(f"  算子      : {len(graph.node)} 个节点 / {len(ops)} 种")
    print("    " + ", ".join(f"{k}×{v}" for k, v in ops.most_common(12)))

    # 判断是否带 NMS（end2end 导出）
    has_nms = any(k in ops for k in ("NonMaxSuppression", "NMS"))
    if has_nms:
        print("  ⚠ 检测到 NonMaxSuppression/NMS：这是 end2end 导出，")
        print("    ST 的后处理库会自己算 NMS，导出时必须 end2end=False")
    else:
        print("  ✓ 不含 NMS，符合 ST 部署要求（NMS 留给 MCU 侧后处理）")

    # 粗判 YOLO 输出布局
    for out in graph.output:
        d = [x.dim_value for x in out.type.tensor_type.shape.dim if x.HasField("dim_value")]
        if len(d) == 3 and d[0] == 1:
            print(f"  → 输出 {out.name} 形状 {d}：单张量、非 end2end，"
                  f"类别数 ≈ {d[1] - 4}（若按 [1, 4+cls, N] 布局）")
    print(f"  文件大小  : {onnx.__version__} / 见下")
    return has_nms


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    try:
        import onnx  # noqa: F401
    except ImportError:
        print("缺少依赖：pip install onnx")
        return 2
    bad = 0
    for path in argv[1:]:
        if describe(path):
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main(sys.argv))
