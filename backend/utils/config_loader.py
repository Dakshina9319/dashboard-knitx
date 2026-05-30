from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_update(result[key], value)
        else:
            result[key] = value
    return result


def default_config() -> dict[str, Any]:
    return {
        "project": {"name": "KnitX", "environment": "development"},
        "model": {
            "path": "models/knitx_best.pt",
            "confidence": 0.25,
            "image_size": 640,
            "device": "cpu",
            "class_names": {0: "stain_or_spots", 1: "needle_line", 2: "holes"},
        },
        "class_remap": {"enabled": True, "map": {0: 2, 2: 0}},
        "inspection": {
            "roll_id": "ROLL_001",
            "session_id_prefix": "KNITX",
            "gsm": 202.0,
            "roll_weight_kg": 110.8,
            "operator": "operator",
            "machine_id": "PI5_LINE_01",
        },
        "calibration": {"mm_per_pixel": 0.20},
        "preprocessing": {
            "gaussian_kernel": 5,
            "threshold_block_size": 31,
            "threshold_c": 5,
            "canny_low": 50,
            "canny_high": 150,
            "clahe_clip_limit": 2.0,
            "clahe_tile_grid_size": 8,
        },
        "contours": {
            "min_area": 120,
            "max_area_ratio": 0.60,
            "min_aspect_ratio": 0.05,
            "max_aspect_ratio": 20.0,
            "reject_if_no_contours": False,
        },
        "tracker": {
            "iou_threshold": 0.30,
            "max_lost": 5,
            "min_hits_image": 1,
            "min_hits_video": 3,
            "cooldown_seconds": 3.0,
        },
        "runtime": {
            "mode": "image",
            "source": "",
            "camera_index": 0,
            "display": True,
            "save_visualizations": False,
            "stop_key": "q",
        },
        "storage": {
            "provider": "local",
            "database_path": "data/database/knitx_inspection.db",
            "defect_image_dir": "data/defect_images",
            "report_dir": "data/reports",
            "folder_mode": "auto_date_order",
            "custom_folder_name": "KnitX Reports",
            "date_folder_format": "%d-%m-%Y",
            "shortener": "none",
            "google_drive": {
                "credentials_path": "config/google_drive_credentials.json",
                "token_path": "data/google_drive_token.json",
                "parent_folder_id": "",
                "parent_folder_name": "KnitX Reports",
                "create_parent_folder": True,
            },
        },
        "visualization": {
            "mask_alpha": 0.35,
            "show_heatmap": False,
            "window_name": "KnitX Industrial Inspection",
        },
    }


def load_config(config_path: str | Path = "config/knitx_config.yaml") -> dict[str, Any]:
    path = Path(config_path)
    if not path.is_absolute():
        path = _repo_root() / path

    config = default_config()
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        config = _deep_update(config, loaded)

    return resolve_paths(config, _repo_root())


def resolve_paths(config: dict[str, Any], root: Path) -> dict[str, Any]:
    resolved = deepcopy(config)
    for section, keys in {
        "model": ["path"],
        "storage": ["database_path", "defect_image_dir", "report_dir"],
    }.items():
        for key in keys:
            value = Path(str(resolved[section][key]))
            if not value.is_absolute():
                value = root / value
            resolved[section][key] = str(value)

    drive_config = resolved["storage"].setdefault("google_drive", {})
    for key in ("credentials_path", "token_path"):
        value = Path(str(drive_config.get(key, "")))
        if value and not value.is_absolute():
            value = root / value
        drive_config[key] = str(value)
    return resolved


def ensure_runtime_dirs(config: dict[str, Any]) -> None:
    for key in ("defect_image_dir", "report_dir"):
        Path(config["storage"][key]).mkdir(parents=True, exist_ok=True)
    Path(config["storage"]["database_path"]).parent.mkdir(parents=True, exist_ok=True)
    token_path = config["storage"].get("google_drive", {}).get("token_path")
    if token_path:
        Path(token_path).parent.mkdir(parents=True, exist_ok=True)
