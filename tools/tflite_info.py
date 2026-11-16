#!/usr/bin/env python3
"""读 .tflite 的输入/输出张量形状，不依赖 TensorFlow。

为什么需要：ST 的量化模型是 .tflite，但工程里的后处理常数（网格尺寸、类别数、
输出 buffer 大小）写在 C 头文件里，很容易和模型真实形状不一致，而且这种错位
不会报编译错误，只会让框全部算歪——极难排查。

用法：
    python tools/tflite_info.py <model.tflite> [更多.tflite]

依赖：pip install tflite
"""

import sys

TYPES = {
    0: "FLOAT32", 1: "FLOAT16", 2: "INT32", 3: "UINT8", 4: "INT64",
    5: "STRING", 6: "BOOL", 7: "INT16", 9: "INT8", 10: "FLOAT64",
}


def describe(path):
    from tflite.Model import Model as TFLModel  # 延迟导入，便于报错友好

    with open(path, "rb") as fh:
        buf = fh.read()
    model = TFLModel.GetRootAsModel(buf, 0)

    print(f"\n=== {path}")
    print(f"  文件大小   : {len(buf):,} 字节")
    print(f"  schema 版本: {model.Version()}")
    print(f"  子图数量   : {model.SubgraphsLength()}")

    sub = model.Subgraphs(0)

    def shape_of(tensor):
        return [tensor.Shape(i) for i in range(tensor.ShapeLength())]

    def emit(label, index):
        tensor = sub.Tensors(index)
        name = tensor.Name().decode("utf-8", "replace") if tensor.Name() else "?"
        shp = shape_of(tensor)
        elems = 1
        for d in shp:
            elems *= d
        tname = TYPES.get(tensor.Type(), f"type{tensor.Type()}")
        print(f"  {label}: {name}")
        print(f"        shape={shp}  dtype={tname}  elements={elems}")
        return name, shp, elems, tname

    outputs = []
    for i in range(sub.InputsLength()):
        emit(f"输入[{i}]", sub.Inputs(i))
    for i in range(sub.OutputsLength()):
        outputs.append(emit(f"输出[{i}]", sub.Outputs(i)))

    # 顺手做一次一致性判断：输出元素数能不能拆成 grid*grid*anchors*(5+classes)
    print("  解码可行性：")
    for name, shp, elems, _ in outputs:
        hits = []
        for grid in (7, 13, 14, 16, 20, 26, 28, 40):
            if elems % (grid * grid) != 0:
                continue
            per_cell = elems // (grid * grid)
            for anchors in (3, 4, 5):
                if per_cell % anchors == 0:
                    classes = per_cell // anchors - 5
                    if 0 <= classes <= 120:
                        hits.append(f"grid={grid} anchors={anchors} classes={classes}")
        print(f"        {elems} 元素 → " + ("；".join(hits) if hits else "拆不出常见 YOLO 布局"))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    try:
        import tflite  # noqa: F401
    except ImportError:
        print("缺少依赖：pip install tflite")
        return 2
    for path in argv[1:]:
        describe(path)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main(sys.argv))
