# 模型转换流程（PC 侧，不需要开发板）

从 Ultralytics 权重到 STEdgeAI 生成的 C 代码，全程可在 PC 上完成。

## 1. 训练 / 选模型

```bash
yolo detect train model=yolov8n.pt data=configs/my_dataset.yaml imgsz=256 epochs=100 batch=16
```

零成本替代：直接用 COCO 预训练的 `yolov8n.pt`，不训练也能跑。

## 2. 导出 int8 TFLite

前提：

- Python 3.9~3.11
- `exporter.py` 中 `quant_type="per-channel"`（`tools/export_onnx.py --format tflite` 会自动打补丁）

```bash
python tools/export_onnx.py --weights yolov8n.pt --format tflite --imgsz 256
```

产物：

- `yolov8n_saved_model/yolov8n_integer_quant.tflite`（int8 输入输出）
- `yolov8n_saved_model/yolov8n_full_integer_quant.tflite`（float 输入输出）

**部署要求 uint8 输入**，由 STEdgeAI 的 `--input-data-type uint8` 处理。

## 3. 可选：用 ST 脚本重新量化

当 Ultralytics 自带量化掉点严重时，用 ST 的 `tflite_quant.py` 配 `configs/quant_config.yaml`，关键是把 `calib_dataset_path` 换成本场景的真实图片（100 张左右），不要用 coco8。

## 4. STEdgeAI 转换

优先用软件包自带的 `Model/generate-n6-model.sh`，只改模型路径。核心参数：

- `--target stm32n6`
- `--input-data-type uint8`
- `--optimization balanced`

若改用网页版 <https://stedgeai-dc.st.com/>，上传 tflite、选 STM32N6，下载生成的 C 代码。

**检查点**：转换报告里不应有大量层回退到 CPU 执行（fallback 多则帧率崩）。

## 5. 落地到工程

替换 `network.c`、`network_ecblobs.h`，重新生成 `network_data.hex`，并修改 `app_config.h`：

```c
#define NB_CLASSES 2
static const char* classes_table[NB_CLASSES] = {"cat", "dog"};
```

后处理类型按输出格式选：float 输出用 `POSTPROCESS_OD_YOLO_V8_UF`，int8 输出用 `..._UI`（以 `Middlewares/ai-postprocessing-wrapper/README.md` 为准）。

## 6. 性能参考

STM32N6 上 YOLOv8n @256×256 约 29 ms / 34 fps（官方数据）。同代 NPU 的 N647 应在同一量级，以实测为准。
