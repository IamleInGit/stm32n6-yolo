/**
 * @file    test_pipeline.c
 * @brief   端到端集成测试：原始头 → 解码 → NMS → 最终框
 *
 * 这条链路就是固件里实际要跑的：
 *   NPU 输出 network.c 的 buffer
 *     → yolo_v8_decode()
 *     → yolo_v8_nms()
 *     → 画框
 *
 * 用法：
 *   test_pipeline.exe box.bin cls.bin out.txt <imgsz> <nc> <conf> <iou> <max_det> [iters]
 *
 * out.txt 每行: <x1> <y1> <x2> <y2> <score> <cls>
 * iters > 0 时额外打印主机端单帧耗时（不含进程启动开销）。
 *
 * 只是验证工具，不参与固件编译。
 */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#include "yolo_v8_decode.h"
#include "yolo_v8_nms.h"

#define CAND_CAP 512
#define OUT_CAP  128

static yolo_det_t g_cand[CAND_CAP];
static yolo_det_t g_out[OUT_CAP];

int main(int argc, char **argv)
{
    const char *box_path, *cls_path, *out_path;
    int img_size, n_classes, max_det, iters = 0, kept = 0, i;
    float conf, iou;
    size_t n_box, n_cls, n_dec;
    float *box = NULL, *cls = NULL, *dec = NULL;
    FILE *f;

    if (argc < 9) {
        fprintf(stderr,
                "用法: %s box.bin cls.bin out.txt imgsz nc conf iou max_det [iters]\n",
                argv[0]);
        return 2;
    }
    box_path = argv[1];
    cls_path = argv[2];
    out_path = argv[3];
    img_size = atoi(argv[4]);
    n_classes = atoi(argv[5]);
    conf = (float)atof(argv[6]);
    iou = (float)atof(argv[7]);
    max_det = atoi(argv[8]);
    if (argc > 9) {
        iters = atoi(argv[9]);
    }

    if (yolo_v8_anchor_count(img_size) <= 0) {
        return 2;
    }
    n_box = (size_t)4 * YOLO_REG_MAX * (size_t)yolo_v8_anchor_count(img_size);
    n_cls = (size_t)n_classes * (size_t)yolo_v8_anchor_count(img_size);
    n_dec = (size_t)(4 + n_classes) * (size_t)yolo_v8_anchor_count(img_size);

    box = (float *)malloc(n_box * sizeof(float));
    cls = (float *)malloc(n_cls * sizeof(float));
    dec = (float *)malloc(n_dec * sizeof(float));
    if (box == NULL || cls == NULL || dec == NULL) {
        fprintf(stderr, "内存不足\n");
        return 2;
    }

    f = fopen(box_path, "rb");
    if (f == NULL || fread(box, sizeof(float), n_box, f) != n_box) {
        fprintf(stderr, "读不了 %s\n", box_path);
        return 2;
    }
    fclose(f);
    f = fopen(cls_path, "rb");
    if (f == NULL || fread(cls, sizeof(float), n_cls, f) != n_cls) {
        fprintf(stderr, "读不了 %s\n", cls_path);
        return 2;
    }
    fclose(f);

    /* 跑一次（或 iters 次） */
    {
        int n = (iters > 0) ? iters : 1;
        clock_t t0 = clock();
        for (i = 0; i < n; i++) {
            kept = 0;
            if (yolo_v8_decode(box, cls, img_size, n_classes,
                               yolo_v8_anchor_count(img_size), dec) != 0) {
                fprintf(stderr, "解码参数非法\n");
                return 3;
            }
            kept = yolo_v8_nms(dec, n_classes, yolo_v8_anchor_count(img_size),
                               conf, iou, max_det, g_cand, CAND_CAP, g_out, OUT_CAP);
            if (kept < 0) {
                fprintf(stderr, "NMS 参数非法\n");
                return 3;
            }
        }
        if (iters > 0) {
            double ms = (double)(clock() - t0) * 1000.0 / (double)CLOCKS_PER_SEC / (double)iters;
            printf("主机端 decode+NMS: %.3f ms/帧（%d 次平均）\n", ms, iters);
        }
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
    free(box);
    free(cls);
    free(dec);
    return 0;
}
