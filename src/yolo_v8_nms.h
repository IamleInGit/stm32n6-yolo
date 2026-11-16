/**
 * @file    yolo_v8_nms.h
 * @brief   YOLOv8 后处理 NMS（纯 C99，无动态内存）
 *
 * 接在 yolo_v8_decode() 后面用：
 *   原始头 → yolo_v8_decode() → [4+nc, N] → yolo_v8_nms() → 检测框
 *
 * 设计取舍：
 *   - 不用 malloc：候选框数组由调用方提供（scratch），适合 MCU
 *   - 按类别分别做 NMS（与 ultralytics 的类内 NMS 语义一致）
 *   - 分数排序用插入排序的前 K 保留，避免整表 qsort 的开销
 */
#ifndef YOLO_V8_NMS_H
#define YOLO_V8_NMS_H

#ifdef __cplusplus
extern "C" {
#endif

/** 一个检测结果，坐标单位与输入一致（像素） */
typedef struct {
    float x1;
    float y1;
    float x2;
    float y2;
    float score;
    int   cls;
} yolo_det_t;

/**
 * @brief 对解码后的张量做置信度过滤 + 类内 NMS
 *
 * @param dec         [4 + n_classes, n_anchors]，(cx,cy,w,h,概率...)，像素坐标
 * @param n_classes   类别数
 * @param n_anchors   锚点数
 * @param conf_thres  置信度阈值
 * @param iou_thres   IoU 阈值
 * @param max_det     最多输出多少个框
 * @param cand        调用方提供的候选缓冲区（scratch），建议 >= 128
 * @param cand_cap    候选缓冲区容量
 * @param out         输出数组，容量 out_cap
 * @param out_cap     输出容量
 * @return 实际检测数；参数非法返回 -1
 */
int yolo_v8_nms(const float *dec,
                int n_classes,
                int n_anchors,
                float conf_thres,
                float iou_thres,
                int max_det,
                yolo_det_t *cand,
                int cand_cap,
                yolo_det_t *out,
                int out_cap);

/** 两个框的 IoU（供单元测试复用） */
float yolo_box_iou(const yolo_det_t *a, const yolo_det_t *b);

#ifdef __cplusplus
}
#endif

#endif /* YOLO_V8_NMS_H */
