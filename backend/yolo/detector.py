from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class Detection:
    bbox: tuple[int, int, int, int]
    confidence: float
    class_id: int
    class_name: str


class YoloDetector:
    def __init__(
        self,
        model_path: str,
        confidence: float,
        image_size: int,
        device: str,
        class_names: dict[int, str],
        class_remap: dict[str, Any],
    ) -> None:
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(
                f"YOLO model not found at {path}. Place a model there or update config/knitx_config.yaml."
            )

        self.is_onnx = path.suffix.lower() == ".onnx"
        self.confidence = confidence
        self.image_size = image_size
        self.class_names = {int(k): str(v) for k, v in class_names.items()}
        self.remap_enabled = bool(class_remap.get("enabled", False))
        self.class_remap = {int(k): int(v) for k, v in class_remap.get("map", {}).items()}

        if self.is_onnx:
            # Load using pre-compiled OpenCV DNN module (no Torch or Ultralytics needed!)
            self.net = cv2.dnn.readNetFromONNX(str(path))
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            print(f"[YOLO] Loaded pure ONNX model '{path.name}' via OpenCV DNN (CPU optimized).")
        else:
            # Fallback to Ultralytics YOLO (requires PyTorch & Ultralytics installed)
            from ultralytics import YOLO
            self.model = YOLO(str(path))
            self.device = device
            print(f"[YOLO] Loaded PyTorch model '{path.name}' via Ultralytics.")

    def detect(self, frame) -> list[Detection]:
        if self.is_onnx:
            # 1. Image preprocessing: resize and blob creation for square YOLOv8 input (BCHW format)
            h, w = frame.shape[:2]
            blob = cv2.dnn.blobFromImage(
                frame,
                1.0 / 255.0,
                (self.image_size, self.image_size),
                swapRB=True,
                crop=False,
            )
            self.net.setInput(blob)
            
            # 2. Forward pass: output shape [1, 5+classes, 8400] or similar
            outputs = self.net.forward()
            
            # Postprocessing: reshape/transpose to [8400, 5+classes]
            outputs = outputs[0]
            if outputs.shape[0] < outputs.shape[1]:
                outputs = outputs.T

            detections: list[Detection] = []
            for row in outputs:
                classes_scores = row[4:]
                class_id = np.argmax(classes_scores)
                conf = classes_scores[class_id]

                if conf >= self.confidence:
                    cx, cy, box_w, box_h = row[:4]

                    # Scale back to original input frame aspect ratio
                    x_factor = w / self.image_size
                    y_factor = h / self.image_size

                    x1 = int((cx - box_w / 2) * x_factor)
                    y1 = int((cy - box_h / 2) * y_factor)
                    x2 = int((cx + box_w / 2) * x_factor)
                    y2 = int((cy + box_h / 2) * y_factor)

                    target_class_id = int(class_id)
                    if self.remap_enabled:
                        target_class_id = self.class_remap.get(target_class_id, target_class_id)
                    class_name = self.class_names.get(target_class_id, f"class_{target_class_id}")

                    detections.append(
                        Detection(
                            bbox=(x1, y1, x2, y2),
                            confidence=float(conf),
                            class_id=target_class_id,
                            class_name=class_name,
                        )
                    )

            # 3. Apply Non-Maximum Suppression (NMS) to clear duplicates
            boxes = [d.bbox for d in detections]
            confs = [d.confidence for d in detections]
            indices = cv2.dnn.NMSBoxes(boxes, confs, self.confidence, 0.45)

            final_detections: list[Detection] = []
            if len(indices) > 0:
                for idx in indices.flatten():
                    final_detections.append(detections[idx])
            return final_detections
        else:
            # PyTorch Ultralytics fallback
            results = self.model(
                frame,
                conf=self.confidence,
                imgsz=self.image_size,
                device=self.device,
                verbose=False,
            )

            detections: list[Detection] = []
            for result in results:
                if result.boxes is None:
                    continue
                for box in result.boxes:
                    x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                    confidence = float(box.conf[0])
                    class_id = int(box.cls[0])
                    if self.remap_enabled:
                        class_id = self.class_remap.get(class_id, class_id)
                    class_name = self.class_names.get(class_id, f"class_{class_id}")
                    detections.append(
                        Detection(
                            bbox=(x1, y1, x2, y2),
                            confidence=confidence,
                            class_id=class_id,
                            class_name=class_name,
                        )
                    )
            return detections
