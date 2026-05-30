from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DefectMeasurement:
    width_px: int
    height_px: int
    width_mm: float
    height_mm: float
    area_mm2: float
    size_inch: float
    points: int


def assign_4_point_score(size_inch: float) -> int:
    if size_inch <= 3:
        return 1
    if size_inch <= 6:
        return 2
    if size_inch <= 9:
        return 3
    return 4


def measure_defect(bbox: tuple[int, int, int, int], mm_per_pixel: float) -> DefectMeasurement:
    x1, y1, x2, y2 = bbox

    # STEP 1: YOLO detects defect and returns bbox.
    # STEP 2: Get bounding box width and height in pixels.
    width_px = max(0, x2 - x1)
    height_px = max(0, y2 - y1)

    # STEP 3: Convert pixels to real-world millimeters and inches.
    width_mm = width_px * mm_per_pixel
    height_mm = height_px * mm_per_pixel
    area_mm2 = width_mm * height_mm
    size_inch = max(width_mm, height_mm) / 25.4

    # STEP 4: Apply industrial 4-point rule.
    points = assign_4_point_score(size_inch)

    return DefectMeasurement(
        width_px=width_px,
        height_px=height_px,
        width_mm=width_mm,
        height_mm=height_mm,
        area_mm2=area_mm2,
        size_inch=size_inch,
        points=points,
    )


def calculate_points_per_100_sq_yards(total_points: int, gsm: float, roll_weight_kg: float) -> float:
    if roll_weight_kg <= 0:
        raise ValueError("roll_weight_kg must be greater than zero")
    return round((total_points * gsm * 0.083) / roll_weight_kg, 2)


def grade_fabric(points_per_100_sq_yards: float) -> str:
    if points_per_100_sq_yards <= 20:
        return "ACCEPT"
    if points_per_100_sq_yards <= 40:
        return "SECOND QUALITY"
    return "REJECT"
