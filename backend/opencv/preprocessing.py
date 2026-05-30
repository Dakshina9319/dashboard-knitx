from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class PreprocessResult:
    gray: np.ndarray
    enhanced: np.ndarray
    blurred: np.ndarray
    threshold: np.ndarray
    edges: np.ndarray


def _odd(value: int) -> int:
    value = max(3, int(value))
    return value if value % 2 == 1 else value + 1


def preprocess_frame(frame: np.ndarray, config: dict) -> PreprocessResult:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    tile_size = int(config.get("clahe_tile_grid_size", 8))
    clahe = cv2.createCLAHE(
        clipLimit=float(config.get("clahe_clip_limit", 2.0)),
        tileGridSize=(tile_size, tile_size),
    )
    enhanced = clahe.apply(gray)

    kernel = _odd(int(config.get("gaussian_kernel", 5)))
    blurred = cv2.GaussianBlur(enhanced, (kernel, kernel), 0)

    block_size = _odd(int(config.get("threshold_block_size", 31)))
    threshold = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        int(config.get("threshold_c", 5)),
    )

    edges = cv2.Canny(
        blurred,
        int(config.get("canny_low", 50)),
        int(config.get("canny_high", 150)),
    )
    return PreprocessResult(gray=gray, enhanced=enhanced, blurred=blurred, threshold=threshold, edges=edges)
