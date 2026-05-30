from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class AbnormalRegion:
    bbox: tuple[int, int, int, int]
    area: float
    aspect_ratio: float
    contour: np.ndarray


def find_abnormal_regions(preprocessed, frame_shape: tuple[int, int, int], config: dict) -> list[AbnormalRegion]:
    frame_area = frame_shape[0] * frame_shape[1]
    min_area = float(config.get("min_area", 120))
    max_area = frame_area * float(config.get("max_area_ratio", 0.60))
    min_aspect = float(config.get("min_aspect_ratio", 0.05))
    max_aspect = float(config.get("max_aspect_ratio", 20.0))

    combined = cv2.bitwise_or(preprocessed.threshold, preprocessed.edges)
    kernel = np.ones((3, 3), dtype=np.uint8)
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel, iterations=1)
    combined = cv2.dilate(combined, kernel, iterations=1)

    contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions: list[AbnormalRegion] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 0 or h <= 0:
            continue
        aspect_ratio = w / float(h)
        if not (min_aspect <= aspect_ratio <= max_aspect):
            continue
        regions.append(AbnormalRegion(bbox=(x, y, x + w, y + h), area=area, aspect_ratio=aspect_ratio, contour=contour))

    regions.sort(key=lambda region: region.area, reverse=True)
    return regions


def should_skip_frame(regions: list[AbnormalRegion], config: dict) -> bool:
    return bool(config.get("reject_if_no_contours", False)) and not regions
