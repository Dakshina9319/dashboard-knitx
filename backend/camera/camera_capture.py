from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterator

import cv2


class ThreadedCamera:
    def __init__(self, camera_index: int | str = 0, width: int = 640, height: int = 480) -> None:
        if isinstance(camera_index, str):
            # For remote Wi-Fi network streams (MJPEG, RTSP, etc.)
            self.capture = cv2.VideoCapture(camera_index)
        else:
            self.capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
            if not self.capture.isOpened():
                self.capture = cv2.VideoCapture(camera_index)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.grabbed, self.frame = self.capture.read()
        self.stopped = False
        self.lock = threading.Lock()

    def start(self) -> "ThreadedCamera":
        thread = threading.Thread(target=self._update, daemon=True)
        thread.start()
        return self

    def _update(self) -> None:
        while not self.stopped:
            grabbed, frame = self.capture.read()
            with self.lock:
                self.grabbed = grabbed
                self.frame = frame

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, None
            return self.grabbed, self.frame.copy()

    def stop(self) -> None:
        self.stopped = True
        self.capture.release()


def iter_image_paths(source: str) -> Iterator[Path]:
    path = Path(source)
    if path.is_file():
        yield path
        return

    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
    for image_path in sorted(path.rglob("*")):
        if image_path.suffix.lower() in image_exts:
            yield image_path


def open_video(source: str) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video source: {source}")
    return capture
