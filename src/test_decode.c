/**
 * @file    test_decode.c
 * @brief   主机端单元测试：读原始头二进制 → C 解码 → 写结果，供 Python 比对
 *
 * 用法：
 *   test_decode.exe box.bin cls.bin out.bin <imgsz> <n_classes> <n_anchors>
 *
 * 这只是验证工具，不参与固件编译。
 */
#include <stdio.h>
#include <stdlib.h>

#include "yolo_v8_decode.h"

static float *read_bin(const char *path, size_t count)
{
    FILE *f = fopen(path, "rb");
    float *buf;

    if (f == NULL) {
        fprintf(stderr, "打不开 %s\n", path);
        exit(2);
    }
    buf = (float *)malloc(count * sizeof(float));
    if (buf == NULL) {
        fprintf(stderr, "内存不足 (%zu floats)\n", count);
        exit(2);
    }
    if (fread(buf, sizeof(float), count, f) != count) {
        fprintf(stderr, "%s 数据不足，期望 %zu 个 float\n", path, count);
        exit(2);
    }
    fclose(f);
    return buf;
}

int main(int argc, char **argv)
{
    const char *box_path, *cls_path, *out_path;
    int img_size, n_classes, n_anchors, rc;
    size_t n_out;
    float *box, *cls, *out;
    FILE *f;

    if (argc < 7) {
        fprintf(stderr, "用法: %s box.bin cls.bin out.bin imgsz n_classes n_anchors\n", argv[0]);
        return 2;
    }
    box_path = argv[1];
    cls_path = argv[2];
    out_path = argv[3];
    img_size = atoi(argv[4]);
    n_classes = atoi(argv[5]);
    n_anchors = atoi(argv[6]);

    box = read_bin(box_path, (size_t)4 * YOLO_REG_MAX * (size_t)n_anchors);
    cls = read_bin(cls_path, (size_t)n_classes * (size_t)n_anchors);

    n_out = (size_t)(4 + n_classes) * (size_t)n_anchors;
    out = (float *)malloc(n_out * sizeof(float));
    if (out == NULL) {
        return 2;
    }

    rc = yolo_v8_decode(box, cls, img_size, n_classes, n_anchors, out);
    if (rc != 0) {
        fprintf(stderr, "解码失败 rc=%d（n_anchors=%d，按 imgsz=%d 应为 %d）\n",
                rc, n_anchors, img_size, yolo_v8_anchor_count(img_size));
        return 3;
    }

    f = fopen(out_path, "wb");
    if (f == NULL) {
        fprintf(stderr, "写不了 %s\n", out_path);
        return 2;
    }
    fwrite(out, sizeof(float), n_out, f);
    fclose(f);

    printf("ok: %d anchors, %d classes, %zu floats\n", n_anchors, n_classes, n_out);
    free(box);
    free(cls);
    free(out);
    return 0;
}
