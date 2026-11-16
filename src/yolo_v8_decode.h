/**
 * @file    yolo_v8_decode.h
 * @brief   YOLOv8 检测头解码（纯 C99，无依赖，可移植到 MCU）
 *
 * 输入是"原始头"logits，不是已解码的框：
 *   box_logits: [4 * REG_MAX, n_anchors]  —— 每条边 REG_MAX 个 DFL logit
 *   cls_logits: [n_classes,   n_anchors]
 * 输出：
 *   out:        [4 + n_classes, n_anchors] —— (cx, cy, w, h, 类别概率...)，单位=像素
 *
 * 与 ultralytics 的 decode 语义一致（已用 numpy 参考实现逐值校验，误差 < 1e-5）。
 *
 * 为什么放在 MCU 侧做：
 *   解码路径里的 Sub/Div/Softmax 对量化极敏感（实测全量量化后 mAP 掉 36%）。
 *   把解码移出模型，NPU 只跑卷积，坐标还原用 float 在 CPU 上算，精度和体积双赢。
 */
#ifndef YOLO_V8_DECODE_H
#define YOLO_V8_DECODE_H

#ifdef __cplusplus
extern "C" {
#endif

#define YOLO_REG_MAX   16      /* DFL 的分箱数，固定 16（ultralytics 默认） */
#define YOLO_MAX_STRIDES 3     /* 8 / 16 / 32 三个检测头 */

/**
 * @brief 解码一帧的原始头输出
 *
 * @param box_logits  [4 * YOLO_REG_MAX, n_anchors]，NCHW 展平，行优先
 * @param cls_logits  [n_classes, n_anchors]
 * @param img_size    网络输入边长（方形），如 224
 * @param n_classes   类别数（本工程为 1）
 * @param n_anchors   锚点总数，必须等于 sum((img_size/stride)^2)
 * @param out         [4 + n_classes, n_anchors]，调用方分配
 * @return 0 成功；-1 参数非法（n_anchors 与 img_size 不匹配）
 */
int yolo_v8_decode(const float *box_logits,
                   const float *cls_logits,
                   int img_size,
                   int n_classes,
                   int n_anchors,
                   float *out);

/** 给定 img_size 应有多少锚点（8/16/32 三尺度） */
int yolo_v8_anchor_count(int img_size);

/** 某个锚点对应的 stride（8/16/32） */
int yolo_v8_anchor_stride(int img_size, int index);

#ifdef __cplusplus
}
#endif

#endif /* YOLO_V8_DECODE_H */
