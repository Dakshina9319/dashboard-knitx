from __future__ import annotations

import time
from dataclasses import dataclass

from yolo.detector import Detection


@dataclass
class TrackedDefect:
    track_id: int
    bbox: tuple[int, int, int, int]
    confidence: float
    class_id: int
    class_name: str
    hits: int = 1
    lost: int = 0
    last_logged_at: float = 0.0


class DefectTracker:
    def __init__(
        self,
        iou_threshold: float = 0.30,
        max_lost: int = 5,
        min_hits: int = 3,
        cooldown_seconds: float = 3.0,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.max_lost = max_lost
        self.min_hits = min_hits
        self.cooldown_seconds = cooldown_seconds
        self.tracks: dict[int, TrackedDefect] = {}
        self.next_id = 1

    @staticmethod
    def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if intersection == 0:
            return 0.0
        area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
        area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
        return intersection / float(area_a + area_b - intersection)

    def update(self, detections: list[Detection]) -> list[TrackedDefect]:
        matched_track_ids: set[int] = set()

        for detection in detections:
            best_track_id = None
            best_iou = self.iou_threshold

            for track_id, track in self.tracks.items():
                if track.class_id != detection.class_id:
                    continue
                overlap = self.iou(track.bbox, detection.bbox)
                if overlap > best_iou:
                    best_iou = overlap
                    best_track_id = track_id

            if best_track_id is None:
                track_id = self.next_id
                self.next_id += 1
                self.tracks[track_id] = TrackedDefect(
                    track_id=track_id,
                    bbox=detection.bbox,
                    confidence=detection.confidence,
                    class_id=detection.class_id,
                    class_name=detection.class_name,
                )
                matched_track_ids.add(track_id)
            else:
                track = self.tracks[best_track_id]
                track.bbox = detection.bbox
                track.confidence = max(track.confidence, detection.confidence)
                track.hits += 1
                track.lost = 0
                matched_track_ids.add(best_track_id)

        for track_id in list(self.tracks.keys()):
            if track_id not in matched_track_ids:
                self.tracks[track_id].lost += 1
                if self.tracks[track_id].lost > self.max_lost:
                    del self.tracks[track_id]

        return [track for track in self.tracks.values() if track.hits >= self.min_hits]

    def is_loggable(self, track: TrackedDefect) -> bool:
        now = time.time()
        return (now - track.last_logged_at) >= self.cooldown_seconds

    def mark_logged(self, track: TrackedDefect) -> None:
        if track.track_id in self.tracks:
            self.tracks[track.track_id].last_logged_at = time.time()
