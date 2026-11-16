/**
 * @file    yolo_v8_nms.c
 * @brief   YOLOv8 后处理 NMS 实现（纯 C99）
 */
#include "yolo_v8_nms.h"

#include <stddef.h>

float yolo_box_iou(const yolo_det_t *a, const yolo_det_t *b)
{
    float ix1 = a->x1 > b->x1 ? a->x1 : b->x1;
    float iy1 = a->y1 > b->y1 ? a->y1 : b->y1;
    float ix2 = a->x2 < b->x2 ? a->x2 : b->x2;
    float iy2 = a->y2 < b->y2 ? a->y2 : b->y2;
    float iw = ix2 - ix1;
    float ih = iy2 - iy1;
    float inter, area_a, area_b, uni;

    if (iw <= 0.0f || ih <= 0.0f) {
        return 0.0f;
    }
    inter = iw * ih;
    area_a = (a->x2 - a->x1) * (a->y2 - a->y1);
    area_b = (b->x2 - b->x1) * (b->y2 - b->y1);
    uni = area_a + area_b - inter;
    if (uni <= 0.0f) {
        return 0.0f;
    }
    return inter / uni;
}

/* 按分数降序插入到前 cap 个位置（候选数很少，插入排序比快排划算） */
static void insert_sorted(yolo_det_t *arr, int *n, int cap, const yolo_det_t *v)
{
    int pos;
    int i;

    if (*n >= cap) {
        if (v->score <= arr[cap - 1].score) {
            return; /* 比最后一名还小，直接丢 */
        }
        pos = cap - 1;
    } else {
        pos = (*n)++;
    }
    for (i = pos; i > 0 && arr[i - 1].score < v->score; i--) {
        arr[i] = arr[i - 1];
    }
    arr[i] = *v;
}

int yolo_v8_nms_dets(const yolo_det_t *cand, int n_cand, float iou_thres,
                     int max_det, yolo_det_t *out, int out_cap)
{
    int i, kept = 0;

    if (cand == 0 || out == 0 || n_cand < 0 || out_cap <= 0 || max_det <= 0) {
        return -1;
    }
    if (max_det > out_cap) {
        max_det = out_cap;
    }
    for (i = 0; i < n_cand && kept < max_det; i++) {
        int m;
        int suppressed = 0;
        for (m = 0; m < kept; m++) {
            if (out[m].cls == cand[i].cls &&
                yolo_box_iou(&cand[i], &out[m]) > iou_thres) {
                suppressed = 1;
                break;
            }
        }
        if (!suppressed) {
            out[kept++] = cand[i];
        }
    }
    return kept;
}

int yolo_v8_nms(const float *dec,
                int n_classes,
                int n_anchors,
                float conf_thres,
                float iou_thres,
                int max_det,
                yolo_det_t *cand,
                int cand_cap,
                yolo_det_t *out,
                int out_cap)
{
    int c, n, kept = 0;

    if (dec == 0 || cand == 0 || out == 0 || n_classes <= 0 || n_anchors <= 0 ||
        cand_cap <= 0 || out_cap <= 0 || max_det <= 0) {
        return -1;
    }
    if (max_det > out_cap) {
        max_det = out_cap;
    }

    for (c = 0; c < n_classes; c++) {
        int n_cand = 0;
        int cls_start = kept;   /* 本类已保留的框从 out[cls_start] 开始 */

        /* 1) 置信度过滤，保留分数最高的 cand_cap 个候选 */
        for (n = 0; n < n_anchors; n++) {
            float s = dec[(size_t)(4 + c) * (size_t)n_anchors + n];
            yolo_det_t d;
            float cx, cy, w, h;

            if (s < conf_thres) {
                continue;
            }
            cx = dec[(size_t)0 * (size_t)n_anchors + n];
            cy = dec[(size_t)1 * (size_t)n_anchors + n];
            w = dec[(size_t)2 * (size_t)n_anchors + n];
            h = dec[(size_t)3 * (size_t)n_anchors + n];

            d.x1 = cx - w * 0.5f;
            d.y1 = cy - h * 0.5f;
            d.x2 = cx + w * 0.5f;
            d.y2 = cy + h * 0.5f;
            d.score = s;
            d.cls = c;
            insert_sorted(cand, &n_cand, cand_cap, &d);
        }

        /* 2) 贪心 NMS：已保留的框直接放在 out[cls_start..kept-1]，
         *    拿它当"保留集合"，不额外占内存 */
        for (n = 0; n < n_cand && kept < max_det; n++) {
            int m;
            int suppressed = 0;

            for (m = cls_start; m < kept; m++) {
                if (yolo_box_iou(&cand[n], &out[m]) > iou_thres) {
                    suppressed = 1;
                    break;
                }
            }
            if (!suppressed) {
                out[kept++] = cand[n];
            }
        }
    }
    return kept;
}
