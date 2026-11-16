/**
 * @file    test_nms.c
 * @brief   主机端单元测试：读解码后的张量 → C 版 NMS → 输出文本结果
 *
 * 用法：
 *   test_nms.exe decoded.bin out.txt <n_classes> <n_anchors> <conf> <iou> <max_det>
 *
 * 输出格式（每行一个框）：
 *   <x1> <y1> <x2> <y2> <score> <cls>
 *
 * 只是验证工具，不参与固件编译。
 */
#include <stdio.h>
#include <stdlib.h>

#include "yolo_v8_nms.h"

#define CAND_CAP 512
#define OUT_CAP  128

static yolo_det_t g_cand[CAND_CAP];
static yolo_det_t g_out[OUT_CAP];

int main(int argc, char **argv)
{
    const char *bin_path, *out_path;
    int n_classes, n_anchors, max_det, kept, i;
    float conf, iou;
    size_t count;
    float *dec;
    FILE *f;

    if (argc < 8) {
        fprintf(stderr, "用法: %s decoded.bin out.txt n_classes n_anchors conf iou max_det\n", argv[0]);
        return 2;
    }
    bin_path = argv[1];
    out_path = argv[2];
    n_classes = atoi(argv[3]);
    n_anchors = atoi(argv[4]);
    conf = (float)atof(argv[5]);
    iou = (float)atof(argv[6]);
    max_det = atoi(argv[7]);

    count = (size_t)(4 + n_classes) * (size_t)n_anchors;
    dec = (float *)malloc(count * sizeof(float));
    if (dec == NULL) {
        return 2;
    }
    f = fopen(bin_path, "rb");
    if (f == NULL) {
        fprintf(stderr, "打不开 %s\n", bin_path);
        return 2;
    }
    if (fread(dec, sizeof(float), count, f) != count) {
        fprintf(stderr, "数据不足，期望 %zu 个 float\n", count);
        return 2;
    }
    fclose(f);

    kept = yolo_v8_nms(dec, n_classes, n_anchors, conf, iou, max_det,
                       g_cand, CAND_CAP, g_out, OUT_CAP);
    if (kept < 0) {
        fprintf(stderr, "NMS 参数非法\n");
        return 3;
    }

    f = fopen(out_path, "w");
    if (f == NULL) {
        return 2;
    }
    for (i = 0; i < kept; i++) {
        fprintf(f, "%.6f %.6f %.6f %.6f %.6f %d\n",
                g_out[i].x1, g_out[i].y1, g_out[i].x2, g_out[i].y2,
                g_out[i].score, g_out[i].cls);
    }
    fclose(f);
    printf("ok: %d detections\n", kept);
    free(dec);
    return 0;
}
