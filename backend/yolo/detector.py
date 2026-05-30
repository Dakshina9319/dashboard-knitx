from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
        from ultralytics import YOLO

        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(
                f"YOLO model not found at {path}. Place a model there or update config/knitx_config.yaml."
            )

        self.model = YOLO(str(path))
        self.confidence = confidence
        self.image_size = image_size
        self.device = device
        self.class_names = {int(k): str(v) for k, v in class_names.items()}
        self.remap_enabled = bool(class_remap.get("enabled", False))
        self.class_remap = {int(k): int(v) for k, v in class_remap.get("map", {}).items()}

    def detect(self, frame) -> list[Detection]:
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
