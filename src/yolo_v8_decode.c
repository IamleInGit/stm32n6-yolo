/**
 * @file    yolo_v8_decode.c
 * @brief   YOLOv8 检测头解码实现（纯 C99）
 */
#include "yolo_v8_decode.h"

#include <math.h>
#include <stddef.h>

#define N_STRIDES 3

static const int k_strides[N_STRIDES] = {8, 16, 32};

int yolo_v8_anchor_count(int img_size)
{
    int total = 0;
    int i;
    for (i = 0; i < N_STRIDES; i++) {
        int g = img_size / k_strides[i];
        total += g * g;
    }
    return total;
}

int yolo_v8_anchor_stride(int img_size, int index)
{
    int base = 0;
    int i;
    (void)img_size;
    for (i = 0; i < N_STRIDES; i++) {
        int g = img_size / k_strides[i];
        int count = g * g;
        if (index < base + count) {
            return k_strides[i];
        }
        base += count;
    }
    return k_strides[N_STRIDES - 1];
}

/* 把锚点索引映射成网格坐标（单位=网格，中心偏移 0.5）。
 * 顺序与 ultralytics 的 make_anchors 一致：按 stride 分块，块内按 y 行优先。 */
void yolo_v8_anchor(int img_size, int index, float *ax, float *ay, int *stride)
{
    int base = 0;
    int i;
    for (i = 0; i < N_STRIDES; i++) {
        int s = k_strides[i];
        int g = img_size / s;
        int count = g * g;
        if (index < base + count) {
            int k = index - base;
            int row = k / g;
            int col = k % g;
            *ax = (float)col + 0.5f;
            *ay = (float)row + 0.5f;
            *stride = s;
            return;
        }
        base += count;
    }
    *ax = 0.0f;
    *ay = 0.0f;
    *stride = k_strides[N_STRIDES - 1];
}

/* 对 REG_MAX 个 logit 做 softmax，再按 0..REG_MAX-1 加权求和 → 期望距离
 * 注意：必须带锚点索引 n，否则整块锚点会共用同一组距离（曾经的 bug）
 * 优化：exp 只算一遍存进栈数组，省掉一半 expf 调用（MCU 上很值钱）
 * 对外开放：融合后处理（yolo_v8_postprocess）需要单独对某个锚点算 DFL */
float yolo_v8_dfl(const float *logits, int n_anchors, int c, int n)
{
    float e[YOLO_REG_MAX];
    float m = -INFINITY;
    float sum = 0.0f;
    float inv_sum;
    float acc = 0.0f;
    int k;
    const float *p = logits + (size_t)c * YOLO_REG_MAX * (size_t)n_anchors + (size_t)n;

    for (k = 0; k < YOLO_REG_MAX; k++) {
        float v = p[(size_t)k * (size_t)n_anchors];
        if (v > m) {
            m = v;
        }
    }
    for (k = 0; k < YOLO_REG_MAX; k++) {
        e[k] = expf(p[(size_t)k * (size_t)n_anchors] - m);
        sum += e[k];
    }
    inv_sum = 1.0f / sum;
    for (k = 0; k < YOLO_REG_MAX; k++) {
        acc += e[k] * inv_sum * (float)k;
    }
    return acc;
}

int yolo_v8_decode(const float *box_logits,
                   const float *cls_logits,
                   int img_size,
                   int n_classes,
                   int n_anchors,
                   float *out)
{
    int n;

    if (box_logits == 0 || cls_logits == 0 || out == 0 || img_size <= 0 ||
        n_classes <= 0 || n_anchors <= 0) {
        return -1;
    }
    if (n_anchors != yolo_v8_anchor_count(img_size)) {
        return -1;
    }

    for (n = 0; n < n_anchors; n++) {
        float ax, ay;
        int stride;
        float lt, tp, rt, bt;
        float x1, y1, x2, y2;
        float *o = out + n;
        int c;

        yolo_v8_anchor(img_size, n, &ax, &ay, &stride);

        lt = yolo_v8_dfl(box_logits, n_anchors, 0, n);
        tp = yolo_v8_dfl(box_logits, n_anchors, 1, n);
        rt = yolo_v8_dfl(box_logits, n_anchors, 2, n);
        bt = yolo_v8_dfl(box_logits, n_anchors, 3, n);

        x1 = ax - lt;
        y1 = ay - tp;
        x2 = ax + rt;
        y2 = ay + bt;

        /* 输出 (cx, cy, w, h)，乘 stride 还原到像素 */
        o[0 * n_anchors] = ((x1 + x2) * 0.5f) * (float)stride;
        o[1 * n_anchors] = ((y1 + y2) * 0.5f) * (float)stride;
        o[2 * n_anchors] = (x2 - x1) * (float)stride;
        o[3 * n_anchors] = (y2 - y1) * (float)stride;

        for (c = 0; c < n_classes; c++) {
            float v = cls_logits[(size_t)c * (size_t)n_anchors + n];
            o[(size_t)(4 + c) * (size_t)n_anchors] = 1.0f / (1.0f + expf(-v));
        }
    }
    return 0;
}
