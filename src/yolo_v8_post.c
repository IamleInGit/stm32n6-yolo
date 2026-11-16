/**
 * @file    yolo_v8_post.c
 * @brief   融合后处理实现（剪枝解码 + 类内 NMS）
 */
#include "yolo_v8_post.h"

#include <math.h>
#include <stddef.h>

#include "yolo_v8_decode.h"

static float sigmoidf_(float v)
{
    return 1.0f / (1.0f + expf(-v));
}

/* 按分数降序插入前 cap 个位置。与 yolo_v8_nms.c 的策略一致，
 * 逻辑很短所以各留一份，避免为一个 12 行的辅助函数扩大公共接口。 */
static void push_sorted(yolo_det_t *arr, int *n, int cap, const yolo_det_t *v)
{
    int pos;
    int i;

    if (*n >= cap) {
        if (v->score <= arr[cap - 1].score) {
            return;
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

int yolo_v8_postprocess(const float *box_logits,
                        const float *cls_logits,
                        int img_size,
                        int n_classes,
                        float conf_thres,
                        float iou_thres,
                        int max_det,
                        yolo_det_t *cand,
                        int cand_cap,
                        yolo_det_t *out,
                        int out_cap)
{
    int n_anchors = yolo_v8_anchor_count(img_size);
    int n_cand = 0;
    int n, c;

    if (box_logits == 0 || cls_logits == 0 || cand == 0 || out == 0 ||
        n_anchors <= 0 || n_classes <= 0 || conf_thres < 0.0f ||
        conf_thres > 1.0f || cand_cap <= 0 || out_cap <= 0) {
        return -1;
    }

    for (n = 0; n < n_anchors; n++) {
        float best = 0.0f;
        float ax, ay;
        int stride;
        yolo_det_t d;

        /* 1) 分类分数粗筛：不过阈值就完全跳过 DFL（省下最大的一块开销） */
        for (c = 0; c < n_classes; c++) {
            float s = sigmoidf_(cls_logits[(size_t)c * (size_t)n_anchors + n]);
            if (s > best) {
                best = s;
            }
        }
        if (best < conf_thres) {
            continue;
        }

        /* 2) 只对通过的锚点解码 */
        yolo_v8_anchor(img_size, n, &ax, &ay, &stride);
        {
            float lt = yolo_v8_dfl(box_logits, n_anchors, 0, n);
            float tp = yolo_v8_dfl(box_logits, n_anchors, 1, n);
            float rt = yolo_v8_dfl(box_logits, n_anchors, 2, n);
            float bt = yolo_v8_dfl(box_logits, n_anchors, 3, n);
            float x1 = ax - lt;
            float y1 = ay - tp;
            float x2 = ax + rt;
            float y2 = ay + bt;
            d.x1 = ((x1 + x2) * 0.5f) * (float)stride;
            d.y1 = ((y1 + y2) * 0.5f) * (float)stride;
            d.x2 = (x2 - x1) * (float)stride;   /* 暂存 w，下面换成 x2 */
            d.y2 = (y2 - y1) * (float)stride;   /* 暂存 h */
        }

        /* 3) 逐类判定并收集候选（此时 d.x2/d.y2 还是 w/h） */
        for (c = 0; c < n_classes; c++) {
            float s = sigmoidf_(cls_logits[(size_t)c * (size_t)n_anchors + n]);
            yolo_det_t item;
            float cx, cy, w, h;

            if (s < conf_thres) {
                continue;
            }
            cx = d.x1;
            cy = d.y1;
            w = d.x2;
            h = d.y2;
            item.x1 = cx - w * 0.5f;
            item.y1 = cy - h * 0.5f;
            item.x2 = cx + w * 0.5f;
            item.y2 = cy + h * 0.5f;
            item.score = s;
            item.cls = c;
            push_sorted(cand, &n_cand, cand_cap, &item);
        }
    }

    if (n_cand == 0) {
        return 0;
    }
    return yolo_v8_nms_dets(cand, n_cand, iou_thres, max_det, out, out_cap);
}
