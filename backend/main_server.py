import argparse
import json
import os
import platform
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

import cv2
import numpy as np

# Import KnitX local project modules
from camera.camera_capture import ThreadedCamera
from database.sqlite_handler import InspectionDatabase
from main import KnitXRuntime, apply_cli_overrides
from utils.config_loader import ensure_runtime_dirs, load_config
from yolo.detector import Detection

# Global state lock and thread-safe variables
state_lock = threading.Lock()
is_running = False
is_paused = False
session_active = False

operator_name = "John Doe"
roll_id = "R-2026-0506"
batch_id = "B-1547"
gsm = 202.0
roll_weight_kg = 110.8

total_defects = 0
total_points = 0
hole_count = 0
needle_line_count = 0
quality_score = 100.0
points_per_100 = 0.0
fabric_grade = "ACCEPT"
session_time_seconds = 0
inference_latency = 0.0
gdrive_connected = False

latest_frame_jpeg = None
injected_defects_queue = []
active_defects_in_feed = []
logged_defects_list = []

runtime_instance = None
config_data = None
camera_capture = None

# A helper class for mock defect injection
class InjectedDefect:
    def __init__(self, defect_type, width=640):
        self.id = str(int(time.time() * 1000)) + str(np.random.randint(0, 100))
        self.defect_type = defect_type
        self.x = int(np.random.randint(80, width - 120))
        self.y = -50
        self.width = 40 if defect_type in ("Hole", "Oil Stain") else 24
        self.height = 38 if defect_type in ("Hole", "Oil Stain") else 80
        self.detected = False
        self.confidence = 98.4
        
        # Color in BGR
        if defect_type == "Hole":
            self.color = (50, 50, 239)      # Red
            self.points = 4
            self.size = 250.0
        elif defect_type == "Drop Stitch":
            self.color = (30, 220, 240)     # Yellow
            self.points = 3
            self.size = 180.0
        elif defect_type == "Oil Stain":
            self.color = (200, 240, 240)    # Light Yellow
            self.points = 1
            self.size = 20.0
        else: # Broken Yarn
            self.color = (60, 150, 250)     # Orange
            self.points = 2
            self.size = 65.0

def get_cpu_temp():
    if platform.system() == 'Linux':
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as fh:
                return float(fh.read().strip()) / 1000.0
        except Exception:
            pass
    return 35.0  # Stable baseline room temp on Windows

def get_cpu_load():
    try:
        import psutil
        return int(psutil.cpu_percent())
    except Exception:
        return 0

# Background thread loop that reads from the camera or simulates the conveyor scroll
def frame_processing_loop(camera_idx):
    global latest_frame_jpeg, is_running, is_paused, runtime_instance, session_active
    global total_defects, total_points, hole_count, needle_line_count, quality_score
    global points_per_100, fabric_grade, session_time_seconds, inference_latency
    global injected_defects_queue, active_defects_in_feed, logged_defects_list

    scroll_offset = 0.0
    last_tick_time = time.time()
    
    # Try to open actual hardware camera indices
    webcam = None
    try:
        # Check if actual camera can be started
        webcam = ThreadedCamera(camera_index=camera_idx).start()
        print(f"[SYSTEM] Hardware camera index {camera_idx} successfully initialized.")
    except Exception as e:
        print(f"[SYSTEM] Hardware camera index {camera_idx} not found. Falling back to synthetic virtual scrolling feed. ({e})")

    while True:
        loop_start = time.time()
        
        # 1. State check inside lock
        with state_lock:
            active = is_running
            paused = is_paused
            session = session_active
            injected_to_spawn = list(injected_defects_queue)
            injected_defects_queue.clear()
            
        # Spawn any pending injected defects
        for dtype in injected_to_spawn:
            active_defects_in_feed.append(InjectedDefect(dtype))
            print(f"[PIPELINE] Mock target '{dtype}' injected into frame processing stream.")

        # Read or generate next frame
        raw_frame = None
        is_hardware_feed = False
        if webcam is not None:
            ok, frame = webcam.read()
            if ok and frame is not None:
                raw_frame = frame
                is_hardware_feed = True

        if raw_frame is None:
            # Generate simulated gray conveyor belt texture
            scroll_offset += 2.2
            if scroll_offset >= 40:
                scroll_offset = 0.0
            raw_frame = np.ones((480, 640, 3), dtype=np.uint8) * 15 # Dark Slate slate-900 (15, 15, 15)
            
            # Draw mechanical knit vertical grid curves
            for x in range(0, 640, 20):
                for y in range(-40, 520, 20):
                    wave_y = int(y + scroll_offset)
                    cv2.ellipse(raw_frame, (x + 10, wave_y), (6, 4), 0, 0, 180, (28, 28, 28), 1)

        h, w = raw_frame.shape[:2]

        # Draw active scrolling injected defects onto the frame
        for sim_def in active_defects_in_feed:
            sim_def.y += 4
            # Draw defect colored indicator on the frame
            cv2.rectangle(
                raw_frame, 
                (sim_def.x, sim_def.y), 
                (sim_def.x + sim_def.width, sim_def.y + sim_def.height), 
                sim_def.color, 
                -1
            )

        # Remove defects that scrolled off-screen
        active_defects_in_feed = [d for d in active_defects_in_feed if d.y < h]

        visualized_frame = None
        
        # Process frame if active and running
        if session and active and not paused:
            # Increment session timer
            now = time.time()
            if now - last_tick_time >= 1.0:
                session_time_seconds += 1
                last_tick_time = now

            start_proc = time.time()
            if runtime_instance is not None:
                # 2. Intercept YOLO detector to inject mock detections if active defects exist
                orig_detect = runtime_instance.detector.detect
                
                def mocked_detect(frame):
                    # Call actual YOLO
                    detections = orig_detect(frame)
                    # Merge any simulated injected defects that passed the central line
                    for sim_def in active_defects_in_feed:
                        if sim_def.y >= int(h / 2) and not sim_def.detected:
                            # Convert class indices matching config mapping
                            class_id = 2 if sim_def.defect_type == "Hole" else 1
                            detections.append(Detection(
                                bbox=(sim_def.x, sim_def.y, sim_def.x + sim_def.width, sim_def.y + sim_def.height),
                                confidence=sim_def.confidence,
                                class_id=class_id,
                                class_name=sim_def.defect_type
                            ))
                            sim_def.detected = True
                    return detections
                
                # Apply temporary mock injection
                runtime_instance.detector.detect = mocked_detect
                
                try:
                    # Run KnitX processing pipeline
                    visualized, new_defect = runtime_instance.process_frame(raw_frame, f"camera_0")
                    visualized_frame = visualized
                    
                    if new_defect:
                        # Re-fetch recorded defects inside lock to synchronize metrics
                        defects = runtime_instance.db.fetch_defects(runtime_instance.session_id)
                        with state_lock:
                            logged_defects_list = []
                            total_defects = len(defects)
                            total_points = 0
                            hole_count = 0
                            needle_line_count = 0
                            
                            for d in defects:
                                dtype = d["defect_type"]
                                pts = d["points"]
                                total_points += pts
                                if dtype == "Hole":
                                    hole_count += 1
                                else:
                                    needle_line_count += 1
                                
                                logged_defects_list.append({
                                    "id": str(d["id"]),
                                    "type": dtype,
                                    "size": d["size_inch"] * 25.4, # mm
                                    "x": float(d["bbox_x1"]),
                                    "y": float(d["bbox_y1"]),
                                    "time": d["timestamp"].split()[-1],
                                    "points": pts,
                                    "sync": "LOCAL ONLY" if not gdrive_connected else "SYNCED"
                                })
                            
                            # Quality score calculations
                            quality_score = max(0.0, min(100.0, 100.0 - (total_points / 40.0 * 100.0)))
                            points_per_100 = (total_points * gsm * 0.083) / roll_weight_kg
                            fabric_grade = "ACCEPT" if points_per_100 <= 20 else ("SECOND QUALITY" if points_per_100 <= 40 else "REJECT")
                finally:
                    # Restore original detector
                    runtime_instance.detector.detect = orig_detect

            inference_latency = (time.time() - start_proc) * 1000.0
        else:
            # Render standby overlays if stopped/paused/unconfigured
            visualized_frame = raw_frame.copy()
            overlay_txt = "SYSTEM READY" if session else "OPERATOR LOGIN REQUIRED"
            if paused:
                overlay_txt = "INSPECTION PAUSED"
            
            cv2.rectangle(visualized_frame, (0, 0), (640, 48), (20, 20, 20), -1)
            cv2.putText(
                visualized_frame, 
                f"[KNITX] {overlay_txt}", 
                (20, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 
                0.6, 
                (0, 240, 0) if session else (0, 0, 240), 
                2
            )
            inference_latency = 0.0
            
            # Keep timer tick consistent
            last_tick_time = time.time()

        # Encode visualized frame as JPEG to push to MJPEG stream
        ok, encoded = cv2.imencode('.jpg', visualized_frame)
        if ok:
            latest_frame_jpeg = encoded.tobytes()

        # Target ~25 FPS to conserve Pi CPU overhead
        elapsed = time.time() - loop_start
        sleep_time = max(0.001, 0.04 - elapsed)
        time.sleep(sleep_time)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class KnitXBridgeHandler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        global latest_frame_jpeg, is_running, is_paused, session_active
        global total_defects, total_points, hole_count, needle_line_count, quality_score
        global points_per_100, fabric_grade, session_time_seconds, inference_latency
        global logged_defects_list, gdrive_connected

        if self.path == '/video_feed':
            # Establish high-performance MJPEG feed stream
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()

            while True:
                frame_data = latest_frame_jpeg
                if frame_data is not None:
                    try:
                        self.wfile.write(b'--frame\r\n')
                        self.wfile.write(b'Content-Type: image/jpeg\r\n')
                        self.wfile.write(f"Content-Length: {len(frame_data)}\r\n\r\n".encode())
                        self.wfile.write(frame_data)
                        self.wfile.write(b'\r\n')
                    except Exception:
                        break
                time.sleep(0.04)

        elif self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            # Package session details
            status = {
                "isRunning": is_running,
                "isPaused": is_paused,
                "sessionActive": session_active,
                "operator": operator_name,
                "rollId": roll_id,
                "batchId": batch_id,
                "gsm": gsm,
                "rollWeight": roll_weight_kg,
                "totalDefects": total_defects,
                "totalPoints": total_points,
                "holeCount": hole_count,
                "needleLineCount": needle_line_count,
                "qualityScore": quality_score,
                "pointsPer100": points_per_100,
                "grade": fabric_grade,
                "sessionTime": session_time_seconds,
                "cpuLoad": get_cpu_load(),
                "cpuTemp": get_cpu_temp(),
                "inferenceLatency": inference_latency,
                "gdriveConnected": gdrive_connected
            }
            self.wfile.write(json.dumps(status).encode())

        elif self.path == '/api/defects':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            with state_lock:
                defs = list(logged_defects_list)
            self.wfile.write(json.dumps(defs).encode())

        elif self.path.startswith('/api/report/pdf'):
            global runtime_instance, config_data
            if runtime_instance is None:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"No active session or runtime.")
                return

            session_id = runtime_instance.session_id
            report_dir = config_data["storage"]["report_dir"]
            pdf_file = Path(report_dir) / f"{session_id}_inspection_report.pdf"

            if not pdf_file.exists():
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"PDF report file not found yet. Please STOP the inspection to finalize and generate the report.")
                return

            try:
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Content-Disposition', f'attachment; filename="{session_id}_inspection_report.pdf"')
                self.send_header('Content-Length', str(pdf_file.stat().st_size))
                self.end_headers()

                with open(pdf_file, 'rb') as f:
                    self.wfile.write(f.read())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error serving PDF: {e}".encode())

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global is_running, is_paused, session_active, runtime_instance
        global operator_name, roll_id, batch_id, gsm, roll_weight_kg
        global total_defects, total_points, hole_count, needle_line_count, quality_score
        global points_per_100, fabric_grade, session_time_seconds, logged_defects_list
        global injected_defects_queue, config_data

        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')

        if self.path == '/api/config':
            try:
                data = json.loads(post_data)
                
                with state_lock:
                    operator_name = data.get("operator", "John Doe")
                    roll_id = data.get("roll_id", "R-2026-0506")
                    batch_id = data.get("batch_id", "B-1547")
                    gsm = float(data.get("gsm", 202.0))
                    roll_weight_kg = float(data.get("roll_weight_kg", 110.8))

                    # Reset metrics fully for the new session
                    total_defects = 0
                    total_points = 0
                    hole_count = 0
                    needle_line_count = 0
                    quality_score = 100.0
                    points_per_100 = 0.0
                    fabric_grade = "ACCEPT"
                    session_time_seconds = 0
                    logged_defects_list = []
                    
                    # Apply configurations to KnitX config overrides
                    config_data["inspection"]["roll_id"] = roll_id
                    config_data["inspection"]["gsm"] = gsm
                    config_data["inspection"]["roll_weight_kg"] = roll_weight_kg
                    config_data["inspection"]["operator"] = operator_name
                    config_data["inspection"]["machine_id"] = "PI5_LINE_01"

                    # Instantiate clean runtime session
                    if runtime_instance is not None:
                        try:
                            runtime_instance.db.close()
                        except Exception:
                            pass
                    runtime_instance = KnitXRuntime(config_data, mode="camera")
                    session_active = True
                
                print(f"[OAUTH] Session Configured successfully: Roll {roll_id} under Operator {operator_name}.")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "session_id": runtime_instance.session_id}).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())

        elif self.path == '/api/control':
            try:
                data = json.loads(post_data)
                action = data.get("action")
                print(f"[CONTROL] Received HMI operational action: {action}")
                
                with state_lock:
                    if action == "start":
                        is_running = True
                        is_paused = False
                    elif action == "pause":
                        is_paused = True
                    elif action == "stop":
                        is_running = False
                        is_paused = False
                        if runtime_instance is not None:
                            runtime_instance.finalize()
                            session_active = False
                    elif action == "reset":
                        is_running = False
                        is_paused = False
                        total_defects = 0
                        total_points = 0
                        hole_count = 0
                        needle_line_count = 0
                        quality_score = 100.0
                        points_per_100 = 0.0
                        fabric_grade = "ACCEPT"
                        session_time_seconds = 0
                        logged_defects_list = []
                        if runtime_instance is not None:
                            try:
                                runtime_instance.db.close()
                            except Exception:
                                pass
                            runtime_instance = KnitXRuntime(config_data, mode="camera")
                    elif action == "save":
                        if runtime_instance is not None:
                            runtime_instance.finalize()
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())

        elif self.path == '/api/inject':
            try:
                data = json.loads(post_data)
                dtype = data.get("type", "Hole")
                
                with state_lock:
                    injected_defects_queue.append(dtype)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())

        else:
            self.send_response(404)
            self.end_headers()


def main():
    global config_data
    parser = argparse.ArgumentParser(description="KnitX HMI Integration Bridge Server")
    parser.add_argument("--config", default="config/knitx_config.yaml", help="Path to config file")
    parser.add_argument("--port", type=int, default=5000, help="Bridge server HTTP port")
    parser.add_argument("--camera", type=int, default=0, help="Camera index to use")
    args = parser.parse_args()

    # Load and resolve default config files
    config_data = load_config(args.config)
    ensure_runtime_dirs(config_data)

    print("\n=======================================================")
    print("      KnitX Edge-AI Inspection Integration Bridge")
    print("=======================================================")
    print(f" Port number    : {args.port}")
    print(f" Camera index   : {args.camera}")
    print(f" Model path     : {config_data['model']['path']}")
    print(f" Bounding size  : {config_data['model']['image_size']}px")
    print(f" Environment    : {config_data['project']['environment']}")
    print("=======================================================\n")

    # Start frame processing background worker thread
    proc_thread = threading.Thread(target=frame_processing_loop, args=(args.camera,), daemon=True)
    proc_thread.start()

    # Launch multi-threaded bridge HTTP server
    server = ThreadingHTTPServer(('0.0.0.0', args.port), KnitXBridgeHandler)
    print(f"[BRIDGE] HMI integration server listening at http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[BRIDGE] Server shut down cleanly.")


if __name__ == "__main__":
    main()
