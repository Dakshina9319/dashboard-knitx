#!/usr/bin/env python3
"""
KnitX Wi-Fi Camera Streamer for Raspberry Pi 5
This script captures the camera feed on the Raspberry Pi 5 and streams it over Wi-Fi
as a standard HTTP MJPEG stream. The heavy AI backend running on your developer PC
can connect to this stream to run YOLO defect detection.

Usage:
  python3 pi_camera_streamer.py --port 5001 --camera 0
"""

import argparse
import cv2
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

# Thread-safe global frame buffer
frame_lock = threading.Lock()
latest_frame = None


class CameraGrabber(threading.Thread):
    def __init__(self, camera_source=0, width=640, height=480):
        super().__init__()
        self.camera_source = camera_source
        self.width = width
        self.height = height
        self.stopped = False
        self.daemon = True

    def run(self):
        global latest_frame
        print(f"[CAMERA] Initializing camera source '{self.camera_source}'...")
        
        # Try to open camera
        cap = cv2.VideoCapture(self.camera_source)
        if not cap.isOpened():
            print(f"[ERROR] Failed to open camera source '{self.camera_source}'!")
            print("Please ensure your camera is connected and recognized by the system.")
            sys.exit(1)

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        print("[CAMERA] Stream capture started successfully.")
        
        while not self.stopped:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            # Encode frame as JPEG
            ret_encode, jpeg_bytes = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ret_encode:
                with frame_lock:
                    latest_frame = jpeg_bytes.tobytes()
            
            # Throttle slightly to conserve Pi CPU (limit to ~30 FPS)
            time.sleep(0.03)

        cap.release()

    def stop(self):
        self.stopped = True


class StreamingHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Override to suppress default HTTP logging in terminal
        pass

    def do_GET(self):
        global latest_frame
        if self.path == '/video_feed':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()

            print(f"[STREAM] New client connected from {self.client_address[0]}")
            while True:
                with frame_lock:
                    frame_data = latest_frame

                if frame_data is not None:
                    try:
                        self.wfile.write(b'--frame\r\n')
                        self.wfile.write(b'Content-Type: image/jpeg\r\n')
                        self.wfile.write(f"Content-Length: {len(frame_data)}\r\n\r\n".encode())
                        self.wfile.write(frame_data)
                        self.wfile.write(b'\r\n')
                    except Exception:
                        # Client disconnected
                        break
                time.sleep(0.03)
            print(f"[STREAM] Client disconnected: {self.client_address[0]}")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Use /video_feed to access the camera stream.")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description="KnitX Raspberry Pi Camera Streamer")
    parser.add_argument("--port", type=int, default=5001, help="Port to stream on (default: 5001)")
    parser.add_argument("--camera", type=str, default="0", help="Camera index or device node (default: 0)")
    parser.add_argument("--width", type=int, default=640, help="Camera width (default: 640)")
    parser.add_argument("--height", type=int, default=480, help="Camera height (default: 480)")
    args = parser.parse_args()

    # Parse camera index if it is an integer
    camera_src = args.camera
    if camera_src.isdigit():
        camera_src = int(camera_src)

    # Start the camera capture thread
    grabber = CameraGrabber(camera_source=camera_src, width=args.width, height=args.height)
    grabber.start()

    # Start the HTTP server
    server = ThreadedHTTPServer(('0.0.0.0', args.port), StreamingHandler)
    print("\n=======================================================")
    print("      KnitX Raspberry Pi Camera Streamer (Wi-Fi)")
    print("=======================================================")
    print(f" Streaming Port : {args.port}")
    print(f" Camera Source  : {camera_src}")
    print(f" Resolution     : {args.width}x{args.height}")
    print(f" Access URL     : http://<raspberry_pi_ip>:{args.port}/video_feed")
    print("=======================================================\n")
    print("[SERVER] Listening for incoming video stream connections...")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down streamer server cleanly...")
        grabber.stop()
        print("[SERVER] Off.")


if __name__ == '__main__':
    main()
