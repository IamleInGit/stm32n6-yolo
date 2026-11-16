/**
 * @file    test_post.c
 * @brief   融合后处理的端到端测试：原始头 → yolo_v8_postprocess() → 框
 *
 * 用法：
 *   test_post.exe box.bin cls.bin out.txt <imgsz> <nc> <conf> <iou> <max_det> [iters]
 *
 * 输出与 test_pipeline.exe 相同格式，便于逐行比对两条路径。
 */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#include "yolo_v8_decode.h"
#include "yolo_v8_post.h"

#define CAND_CAP 512
#define OUT_CAP  128

static yolo_det_t g_cand[CAND_CAP];
static yolo_det_t g_out[OUT_CAP];

int main(int argc, char **argv)
{
    const char *box_path, *cls_path, *out_path;
    int img_size, n_classes, max_det, iters = 0, kept = 0, i;
    float conf, iou;
    size_t n_box, n_cls, n_anchors;
    float *box = NULL, *cls = NULL;
    FILE *f;

    if (argc < 9) {
        fprintf(stderr, "用法: %s box.bin cls.bin out.txt imgsz nc conf iou max_det [iters]\n",
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

    n_anchors = (size_t)yolo_v8_anchor_count(img_size);
    if (n_anchors == 0) {
        return 2;
    }
    n_box = (size_t)4 * YOLO_REG_MAX * n_anchors;
    n_cls = (size_t)n_classes * n_anchors;

    box = (float *)malloc(n_box * sizeof(float));
    cls = (float *)malloc(n_cls * sizeof(float));
    if (box == NULL || cls == NULL) {
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

    {
        int n = (iters > 0) ? iters : 1;
        clock_t t0 = clock();
        for (i = 0; i < n; i++) {
            kept = yolo_v8_postprocess(box, cls, img_size, n_classes, conf, iou, max_det,
                                       g_cand, CAND_CAP, g_out, OUT_CAP);
            if (kept < 0) {
                fprintf(stderr, "postprocess 参数非法\n");
                return 3;
            }
        }
        if (iters > 0) {
            double ms = (double)(clock() - t0) * 1000.0 / (double)CLOCKS_PER_SEC / (double)iters;
            printf("主机端 postprocess: %.3f ms/帧（%d 次平均）\n", ms, iters);
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
    return 0;
}
