from __future__ import annotations

import cv2
import numpy as np

from measurement.calculator import DefectMeasurement
from opencv.contour_filter import AbnormalRegion
from utils.tracker import TrackedDefect


STATUS_COLORS = {
    "ACCEPT": (60, 180, 80),
    "SECOND QUALITY": (0, 190, 255),
    "REJECT": (35, 35, 220),
    "RUNNING": (0, 190, 255),
}


def draw_industrial_overlay(
    frame: np.ndarray,
    regions: list[AbnormalRegion],
    defects: list[tuple[TrackedDefect, DefectMeasurement]],
    fps: float,
    roll_id: str,
    session_id: str,
    total_points: int,
    fabric_grade: str,
    config: dict,
) -> np.ndarray:
    canvas = frame.copy()
    _draw_masks(canvas, defects, float(config.get("mask_alpha", 0.35)), bool(config.get("show_heatmap", False)))
    _draw_contours(canvas, regions)
    _draw_defects(canvas, defects)
    _draw_status_panel(canvas, fps, roll_id, session_id, total_points, fabric_grade)
    return canvas


def _draw_masks(frame: np.ndarray, defects: list[tuple[TrackedDefect, DefectMeasurement]], alpha: float, heatmap: bool) -> None:
    overlay = frame.copy()
    for track, _measurement in defects:
        x1, y1, x2, y2 = track.bbox
        color = (0, 0, 210)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
        if heatmap:
            roi = overlay[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
            if roi.size:
                heat = np.zeros_like(roi)
                heat[:, :, 2] = 255
                heat[:, :, 1] = 120
                overlay[y1:y2, x1:x2] = cv2.addWeighted(roi, 0.45, heat, 0.55, 0)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, dst=frame)


def _draw_contours(frame: np.ndarray, regions: list[AbnormalRegion]) -> None:
    for region in regions[:25]:
        cv2.drawContours(frame, [region.contour], -1, (0, 180, 255), 1)


def _draw_defects(frame: np.ndarray, defects: list[tuple[TrackedDefect, DefectMeasurement]]) -> None:
    for track, measurement in defects:
        x1, y1, x2, y2 = track.bbox
        color = (25, 25, 230) if measurement.points >= 4 else (0, 170, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        label = f"{track.class_name} {track.confidence:.2f}"
        measurement_label = f"{measurement.size_inch:.2f} in | {measurement.points} pt"
        _label(frame, label, x1, max(18, y1 - 24), color)
        _label(frame, measurement_label, x1, max(38, y1 - 4), color)

        center = ((x1 + x2) // 2, (y1 + y2) // 2)
        cv2.drawMarker(frame, center, color, markerType=cv2.MARKER_CROSS, markerSize=14, thickness=1)


def _draw_status_panel(
    frame: np.ndarray,
    fps: float,
    roll_id: str,
    session_id: str,
    total_points: int,
    fabric_grade: str,
) -> None:
    panel_h = 94
    cv2.rectangle(frame, (0, 0), (frame.shape[1], panel_h), (26, 28, 30), -1)
    cv2.line(frame, (0, panel_h), (frame.shape[1], panel_h), (80, 80, 80), 1)

    grade_color = STATUS_COLORS.get(fabric_grade, STATUS_COLORS["RUNNING"])
    cv2.putText(frame, "KnitX INDUSTRIAL FABRIC INSPECTION", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.66, (235, 235, 235), 2)
    cv2.putText(frame, f"ROLL: {roll_id}", (16, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (210, 210, 210), 1)
    cv2.putText(frame, f"SESSION: {session_id}", (16, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

    right_x = max(360, frame.shape[1] - 300)
    cv2.putText(frame, f"FPS {fps:.1f}", (right_x, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (210, 210, 210), 1)
    cv2.putText(frame, f"POINTS {total_points}", (right_x, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (210, 210, 210), 1)
    cv2.putText(frame, fabric_grade, (right_x, 84), cv2.FONT_HERSHEY_SIMPLEX, 0.62, grade_color, 2)


def _label(frame: np.ndarray, text: str, x: int, y: int, color: tuple[int, int, int]) -> None:
    (w, h), _baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.46, 1)
    y = max(h + 6, y)
    cv2.rectangle(frame, (x, y - h - 6), (x + w + 8, y + 4), (25, 25, 25), -1)
    cv2.rectangle(frame, (x, y - h - 6), (x + w + 8, y + 4), color, 1)
    cv2.putText(frame, text, (x + 4, y), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (245, 245, 245), 1)
