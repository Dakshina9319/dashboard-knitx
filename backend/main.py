from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from camera.camera_capture import ThreadedCamera, iter_image_paths, open_video
from cloud_storage import build_storage_provider
from database.sqlite_handler import InspectionDatabase
from measurement.calculator import calculate_points_per_100_sq_yards, grade_fabric, measure_defect
from opencv.contour_filter import find_abnormal_regions, should_skip_frame
from opencv.preprocessing import preprocess_frame
from opencv.visualization import draw_industrial_overlay
from reports.qr_generator import generate_qr_report
from utils.config_loader import ensure_runtime_dirs, load_config
from utils.tracker import DefectTracker
from yolo.detector import YoloDetector


class KnitXRuntime:
    def __init__(self, config: dict, mode: str) -> None:
        self.config = config
        self.mode = mode
        self.roll_id = str(config["inspection"]["roll_id"])
        self.gsm = float(config["inspection"]["gsm"])
        self.roll_weight_kg = float(config["inspection"]["roll_weight_kg"])
        self.mm_per_pixel = float(config["calibration"]["mm_per_pixel"])
        self.storage_provider = build_storage_provider(config)

        now = datetime.now()
        prefix = str(config["inspection"]["session_id_prefix"])
        self.session_id = f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}"
        self.started_at = now.strftime("%Y-%m-%d %H:%M:%S")

        self.db = InspectionDatabase(config["storage"]["database_path"])
        self.db.start_session(
            {
                "session_id": self.session_id,
                "roll_id": self.roll_id,
                "gsm": self.gsm,
                "roll_weight_kg": self.roll_weight_kg,
                "operator": config["inspection"].get("operator"),
                "machine_id": config["inspection"].get("machine_id"),
                "started_at": self.started_at,
            }
        )

        self.detector = YoloDetector(
            model_path=config["model"]["path"],
            confidence=float(config["model"]["confidence"]),
            image_size=int(config["model"]["image_size"]),
            device=str(config["model"]["device"]),
            class_names=config["model"]["class_names"],
            class_remap=config["class_remap"],
        )
        self.reset_tracker()

        self.total_defects = 0
        self.total_points = 0
        self.frame_number = 0
        self.last_frame_time = datetime.now()
        self.cloud_folder_url: str | None = None

    def reset_tracker(self) -> None:
        tracker_config = self.config["tracker"]
        min_hits = (
            int(tracker_config["min_hits_image"])
            if self.mode == "image"
            else int(tracker_config["min_hits_video"])
        )
        self.tracker = DefectTracker(
            iou_threshold=float(tracker_config["iou_threshold"]),
            max_lost=int(tracker_config["max_lost"]),
            min_hits=min_hits,
            cooldown_seconds=float(tracker_config["cooldown_seconds"]),
        )

    def process_frame(self, frame, source_name: str) -> tuple[object, bool]:
        self.frame_number += 1
        now = datetime.now()
        elapsed = max((now - self.last_frame_time).total_seconds(), 1e-6)
        fps = 1.0 / elapsed
        self.last_frame_time = now

        preprocessed = preprocess_frame(frame, self.config["preprocessing"])
        regions = find_abnormal_regions(preprocessed, frame.shape, self.config["contours"])

        confirmed_defects = []
        if not should_skip_frame(regions, self.config["contours"]):
            detections = self.detector.detect(frame)
            confirmed_defects = self.tracker.update(detections)

        visible = []
        new_defect_logged = False
        for track in confirmed_defects:
            measurement = measure_defect(track.bbox, self.mm_per_pixel)
            visible.append((track, measurement))

            if not self.tracker.is_loggable(track):
                continue

            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
            proof_paths = self._save_defect_proof_images(frame, preprocessed, track, measurement, source_name)
            image_path = proof_paths["defect_crop"]

            self.db.insert_defect(
                session_id=self.session_id,
                roll_id=self.roll_id,
                frame_number=self.frame_number,
                track=track,
                measurement=measurement,
                timestamp=timestamp,
                image_path=image_path,
                proof_paths=proof_paths,
            )
            self.tracker.mark_logged(track)
            self.total_defects += 1
            self.total_points += measurement.points
            new_defect_logged = True

        points_per_100 = calculate_points_per_100_sq_yards(
            self.total_points,
            self.gsm,
            self.roll_weight_kg,
        )
        grade = grade_fabric(points_per_100)

        visualized = draw_industrial_overlay(
            frame=frame,
            regions=regions,
            defects=visible,
            fps=fps,
            roll_id=self.roll_id,
            session_id=self.session_id,
            total_points=self.total_points,
            fabric_grade=grade,
            config=self.config["visualization"],
        )

        if self.config["runtime"]["save_visualizations"]:
            self._save_visualization(visualized, source_name)

        if new_defect_logged or self.frame_number % 30 == 0:
            self._update_summary(report_path=None, qr_path=None, ended_at=None)
        return visualized, new_defect_logged

    def finalize(self) -> tuple[str, str]:
        defects = self.db.fetch_defects(self.session_id)
        points_per_100 = calculate_points_per_100_sq_yards(
            self.total_points,
            self.gsm,
            self.roll_weight_kg,
        )
        grade = grade_fabric(points_per_100)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        report_path, qr_path, json_path = generate_qr_report(
            report_dir=self.config["storage"]["report_dir"],
            session_id=self.session_id,
            roll_id=self.roll_id,
            gsm=self.gsm,
            roll_weight_kg=self.roll_weight_kg,
            total_defects=self.total_defects,
            total_points=self.total_points,
            points_per_100_sq_yards=points_per_100,
            final_grade=grade,
            timestamp=timestamp,
            defects=defects,
        )

        report_location = report_path
        qr_location = qr_path
        storage_provider_name = getattr(self.storage_provider, "provider_name", "local")
        upload_result = self.storage_provider.upload_report_bundle(
            report_path=report_path,
            qr_path=qr_path,
            json_path=json_path,
            proof_paths=self._collect_proof_paths(defects),
            started_at=self.started_at,
        )
        if upload_result is not None:
            report_path, qr_path, json_path = generate_qr_report(
                report_dir=self.config["storage"]["report_dir"],
                session_id=self.session_id,
                roll_id=self.roll_id,
                gsm=self.gsm,
                roll_weight_kg=self.roll_weight_kg,
                total_defects=self.total_defects,
                total_points=self.total_points,
                points_per_100_sq_yards=points_per_100,
                final_grade=grade,
                timestamp=timestamp,
                defects=defects,
                qr_text=upload_result.qr_text,
                report_url=upload_result.report_url,
                json_url=upload_result.json_url,
                storage_provider=upload_result.storage_provider,
                cloud_folder_url=upload_result.folder_url,
            )
            if hasattr(self.storage_provider, "update_report_links"):
                upload_result = self.storage_provider.update_report_links(
                    result=upload_result,
                    report_path=report_path,
                    qr_path=qr_path,
                    json_path=json_path,
                )
            report_location = upload_result.report_url
            qr_location = upload_result.qr_url
            self.cloud_folder_url = upload_result.folder_url
            storage_provider_name = upload_result.storage_provider

        self._update_summary(
            report_path=report_location,
            qr_path=qr_location,
            ended_at=timestamp,
            storage_provider=storage_provider_name,
            cloud_folder_url=self.cloud_folder_url,
        )
        self.db.close()
        return report_location, qr_location

    def _update_summary(
        self,
        report_path: str | None,
        qr_path: str | None,
        ended_at: str | None,
        storage_provider: str | None = None,
        cloud_folder_url: str | None = None,
    ) -> None:
        points_per_100 = calculate_points_per_100_sq_yards(
            self.total_points,
            self.gsm,
            self.roll_weight_kg,
        )
        self.db.update_summary(
            session_id=self.session_id,
            roll_id=self.roll_id,
            total_defects=self.total_defects,
            total_points=self.total_points,
            points_per_100_sq_yards=points_per_100,
            final_grade=grade_fabric(points_per_100),
            updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            report_path=report_path,
            qr_path=qr_path,
            ended_at=ended_at,
            storage_provider=storage_provider,
            cloud_folder_url=cloud_folder_url,
        )

    def _save_defect_proof_images(self, frame, preprocessed, track, measurement, source_name: str) -> dict[str, str]:
        x1, y1, x2, y2 = track.bbox
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            crop = frame

        output_dir = Path(self.config["storage"]["defect_image_dir"])
        safe_source = Path(source_name).stem.replace(" ", "_")[:40] or "frame"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        base = f"{self.session_id}_{safe_source}_{track.class_name}_{self.frame_number}_{timestamp}"

        crop_path = output_dir / f"{base}_01_defect_crop.jpg"
        original_path = output_dir / f"{base}_02_original_frame.jpg"
        annotated_path = output_dir / f"{base}_03_yolo_annotated.jpg"
        threshold_path = output_dir / f"{base}_04_opencv_threshold.jpg"
        mask_path = output_dir / f"{base}_05_mask_overlay.jpg"

        annotated = frame.copy()
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 230), 3)
        label = f"{track.class_name} {track.confidence:.2f} | {measurement.size_inch:.2f} in | {measurement.points} pt"
        cv2.rectangle(annotated, (x1, max(0, y1 - 32)), (min(w, x1 + 440), y1), (25, 25, 25), -1)
        cv2.putText(annotated, label, (x1 + 6, max(22, y1 - 9)), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (245, 245, 245), 2)

        threshold_bgr = cv2.cvtColor(preprocessed.threshold, cv2.COLOR_GRAY2BGR)
        cv2.rectangle(threshold_bgr, (x1, y1), (x2, y2), (0, 0, 230), 2)

        mask_overlay = frame.copy()
        mask_layer = np.zeros_like(frame)
        cv2.rectangle(mask_layer, (x1, y1), (x2, y2), (0, 0, 255), -1)
        cv2.addWeighted(mask_layer, 0.38, mask_overlay, 1.0, 0, dst=mask_overlay)
        cv2.rectangle(mask_overlay, (x1, y1), (x2, y2), (0, 0, 230), 3)

        cv2.imwrite(str(crop_path), crop)
        cv2.imwrite(str(original_path), frame)
        cv2.imwrite(str(annotated_path), annotated)
        cv2.imwrite(str(threshold_path), threshold_bgr)
        cv2.imwrite(str(mask_path), mask_overlay)

        return {
            "defect_crop": str(crop_path),
            "original_frame": str(original_path),
            "yolo_annotated": str(annotated_path),
            "opencv_threshold": str(threshold_path),
            "mask_overlay": str(mask_path),
        }

    def _save_visualization(self, frame, source_name: str) -> None:
        output_dir = Path(self.config["storage"]["report_dir"]) / "visualizations"
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_source = Path(source_name).stem.replace(" ", "_")[:40] or "frame"
        output_path = output_dir / f"{self.session_id}_{safe_source}_{self.frame_number:06d}.jpg"
        cv2.imwrite(str(output_path), frame)

    def _collect_proof_paths(self, defects: list[dict]) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for defect in defects:
            raw_paths = defect.get("proof_paths")
            proof_paths = raw_paths if isinstance(raw_paths, dict) else {}
            if not proof_paths and raw_paths:
                import json

                try:
                    proof_paths = json.loads(str(raw_paths))
                except json.JSONDecodeError:
                    proof_paths = {}
            for value in list(proof_paths.values()) + [defect.get("image_path")]:
                if value and value not in seen:
                    seen.add(str(value))
                    paths.append(str(value))
        return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KnitX industrial fabric inspection runtime")
    parser.add_argument("--config", default="config/knitx_config.yaml", help="Path to KnitX YAML config")
    parser.add_argument("--mode", choices=["image", "video", "camera"], help="Runtime mode")
    parser.add_argument("--source", help="Image file, image folder, or video file")
    parser.add_argument("--camera-index", type=int, help="Webcam/Pi camera index")
    parser.add_argument("--model", help="YOLO .pt model path")
    parser.add_argument("--roll", help="Roll ID")
    parser.add_argument("--gsm", type=float, help="Fabric GSM")
    parser.add_argument("--roll-weight", type=float, help="Roll weight in kg")
    parser.add_argument("--mm-per-pixel", type=float, help="Calibration value")
    parser.add_argument("--display", action="store_true", help="Force display window on")
    parser.add_argument("--no-display", action="store_true", help="Disable display window")
    parser.add_argument("--enable-class-remap", action="store_true", help="Enable configured class remap")
    parser.add_argument("--disable-class-remap", action="store_true", help="Disable configured class remap")
    parser.add_argument("--storage-provider", choices=["local", "google_drive"], help="Where final reports are saved")
    parser.add_argument("--drive-parent-folder-id", help="Existing Google Drive parent folder ID")
    parser.add_argument("--drive-parent-folder-name", help="Google Drive parent folder name to use or create")
    parser.add_argument("--drive-credentials-path", help="Google OAuth desktop client JSON path")
    parser.add_argument("--no-drive-create-parent-folder", action="store_false", dest="drive_create_parent_folder", help="Do not create the Drive parent folder if it is missing")
    parser.add_argument("--folder-mode", choices=["auto_date_order", "custom"], help="Cloud folder organization mode")
    parser.add_argument("--cloud-folder-name", help="Custom cloud folder name when --folder-mode custom is used")
    parser.add_argument("--disable-url-shortener", action="store_true", help="Use the Drive share link directly in the QR")
    parser.set_defaults(drive_create_parent_folder=None)
    return parser.parse_args()


def apply_cli_overrides(config: dict, args: argparse.Namespace) -> dict:
    if args.mode:
        config["runtime"]["mode"] = args.mode
    if args.source:
        config["runtime"]["source"] = args.source
    if args.camera_index is not None:
        config["runtime"]["camera_index"] = args.camera_index
    if args.model:
        config["model"]["path"] = str(Path(args.model).resolve())
    if args.roll:
        config["inspection"]["roll_id"] = args.roll
    if args.gsm is not None:
        config["inspection"]["gsm"] = args.gsm
    if args.roll_weight is not None:
        config["inspection"]["roll_weight_kg"] = args.roll_weight
    if args.mm_per_pixel is not None:
        config["calibration"]["mm_per_pixel"] = args.mm_per_pixel
    if args.display:
        config["runtime"]["display"] = True
    if args.no_display:
        config["runtime"]["display"] = False
    if args.enable_class_remap:
        config["class_remap"]["enabled"] = True
    if args.disable_class_remap:
        config["class_remap"]["enabled"] = False
    if args.storage_provider:
        config["storage"]["provider"] = args.storage_provider
    if args.folder_mode:
        config["storage"]["folder_mode"] = args.folder_mode
    if args.cloud_folder_name:
        config["storage"]["custom_folder_name"] = args.cloud_folder_name
    if args.disable_url_shortener:
        config["storage"]["shortener"] = "none"

    drive_config = config["storage"].setdefault("google_drive", {})
    if args.drive_parent_folder_id:
        drive_config["parent_folder_id"] = args.drive_parent_folder_id
    if args.drive_parent_folder_name:
        drive_config["parent_folder_name"] = args.drive_parent_folder_name
    if args.drive_credentials_path:
        drive_config["credentials_path"] = str(Path(args.drive_credentials_path).resolve())
    if args.drive_create_parent_folder is not None:
        drive_config["create_parent_folder"] = args.drive_create_parent_folder
    return config


def prompt_for_inspection_values(config: dict, args: argparse.Namespace) -> dict:
    if args.gsm is None:
        config["inspection"]["gsm"] = _prompt_positive_float("Fabric GSM")
    if args.roll_weight is None:
        config["inspection"]["roll_weight_kg"] = _prompt_positive_float("Roll weight in kg")
    return config


def _prompt_positive_float(label: str) -> float:
    while True:
        raw_value = input(f"Enter {label}: ").strip()
        try:
            value = float(raw_value)
        except ValueError:
            print(f"{label} must be a number.")
            continue
        if value <= 0:
            print(f"{label} must be greater than zero.")
            continue
        return value


def run_image_mode(runtime: KnitXRuntime, source: str, display: bool) -> None:
    if not source:
        raise ValueError("Image mode requires --source or runtime.source in config")

    image_paths = list(iter_image_paths(source))
    if not image_paths:
        raise FileNotFoundError(f"No images found at {source}")

    for image_path in image_paths:
        frame = cv2.imread(str(image_path))
        if frame is None:
            print(f"Skipping unreadable image: {image_path}")
            continue
        runtime.reset_tracker()
        visualized, _logged = runtime.process_frame(frame, str(image_path))
        if display:
            cv2.imshow(runtime.config["visualization"]["window_name"], visualized)
            cv2.waitKey(0)


def run_video_mode(runtime: KnitXRuntime, source: str, display: bool) -> None:
    if not source:
        raise ValueError("Video mode requires --source or runtime.source in config")
    capture = open_video(source)
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        visualized, _logged = runtime.process_frame(frame, source)
        if display:
            cv2.imshow(runtime.config["visualization"]["window_name"], visualized)
            if _stop_requested(runtime):
                break
    capture.release()


def run_camera_mode(runtime: KnitXRuntime, camera_index: int, display: bool) -> None:
    camera = ThreadedCamera(camera_index=camera_index).start()
    try:
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                continue
            visualized, _logged = runtime.process_frame(frame, f"camera_{camera_index}")
            if display:
                cv2.imshow(runtime.config["visualization"]["window_name"], visualized)
                if _stop_requested(runtime):
                    break
    finally:
        camera.stop()


def _stop_requested(runtime: KnitXRuntime) -> bool:
    key = cv2.waitKey(1) & 0xFF
    stop_key = str(runtime.config["runtime"].get("stop_key", "q"))
    return key == ord(stop_key[0]) or key == 27


def main() -> None:
    args = parse_args()
    config = apply_cli_overrides(load_config(args.config), args)
    config = prompt_for_inspection_values(config, args)
    ensure_runtime_dirs(config)

    mode = str(config["runtime"]["mode"])
    display = bool(config["runtime"]["display"])
    source = str(config["runtime"].get("source", ""))
    camera_index = int(config["runtime"].get("camera_index", 0))

    try:
        runtime = KnitXRuntime(config, mode=mode)
    except FileNotFoundError as exc:
        if config["storage"].get("provider") == "google_drive":
            drive_config = config["storage"].get("google_drive", {})
            credentials_path = drive_config.get("credentials_path", "config/google_drive_credentials.json")
            print("\nGoogle Drive setup is not complete.")
            print(f"Missing OAuth credentials file: {credentials_path}")
            print("Create a Google Cloud OAuth client with application type 'Desktop app'.")
            print("Download its JSON and either save it at the path above or pass:")
            print('  --drive-credentials-path "C:\\path\\to\\client_secret.json"')
            print("\nAfter that, run the same command again. A browser sign-in will open once.")
            raise SystemExit(2) from exc
        raise
    try:
        if mode == "image":
            run_image_mode(runtime, source, display)
        elif mode == "video":
            run_video_mode(runtime, source, display)
        elif mode == "camera":
            run_camera_mode(runtime, camera_index, display)
        else:
            raise ValueError(f"Unsupported mode: {mode}")
    finally:
        report_path, qr_path = runtime.finalize()
        if display:
            cv2.destroyAllWindows()

    print("\n========== KnitX Inspection Complete ==========")
    print(f"Session ID      : {runtime.session_id}")
    print(f"Roll ID         : {runtime.roll_id}")
    print(f"Total defects   : {runtime.total_defects}")
    print(f"Total points    : {runtime.total_points}")
    print(f"Report          : {report_path}")
    print(f"QR              : {qr_path}")
    if runtime.cloud_folder_url:
        print(f"Cloud folder    : {runtime.cloud_folder_url}")
    print("==============================================\n")


if __name__ == "__main__":
    main()
