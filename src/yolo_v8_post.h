/**
 * @file    yolo_v8_post.h
 * @brief   融合后处理：原始头 → 剪枝解码 → NMS（一步到位）
 *
 * 与"先 yolo_v8_decode() 全场解码、再 yolo_v8_nms()"相比，这里的关键优化是
 * **先用分类分数剪枝，只对通过阈值的锚点做 DFL**。
 *
 * 以 224 输入、1 类为例：
 *   两步法：1029 锚点 × 4 边 × 16 档 = 65,856 次 expf
 *   融合法：1029 次（分类 sigmoid）+ 通过的几十个锚点 × 64 次 ≈ 3,000 次
 *
 * 功能与两步法完全等价（已在主机上逐框比对通过）。
 */
#ifndef YOLO_V8_POST_H
#define YOLO_V8_POST_H

#include "yolo_v8_nms.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief 一步完成解码 + 置信度过滤 + NMS
 *
 * @param box_logits  [4 * 16, n_anchors]
 * @param cls_logits  [n_classes, n_anchors]
 * @param img_size    网络输入边长
 * @param n_classes   类别数
 * @param conf_thres  置信度阈值
 * @param iou_thres   NMS 的 IoU 阈值
 * @param max_det     最多输出框数
 * @param cand        调用方提供的候选缓冲区（scratch）
 * @param cand_cap    候选缓冲区容量
 * @param out         输出数组
 * @param out_cap     输出容量
 * @return 检测数；参数非法返回 -1
 */
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
                        int out_cap);

#ifdef __cplusplus
}
#endif

#endif /* YOLO_V8_POST_H */
