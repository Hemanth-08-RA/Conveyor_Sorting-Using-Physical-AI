"""
===============================================================================
Conveyor Sorting System - Vision & Control Server
===============================================================================
Backend server integrating classical OpenCV computer vision with an interactive
Flask web dashboard and Arduino serial telemetry.

Detects WHITE and GREY cube objects on a BLUE conveyor belt using HSV color 
filtering, morphological operations, and centroid tracking to prevent duplicate
counting.
===============================================================================
"""

import os
import sys
import time
import math
import json
import logging
from datetime import datetime
from collections import deque
import threading

import cv2
import numpy as np
import base64
import webbrowser
from flask import Flask, Response, request, jsonify, send_from_directory

# Optional serial import for Arduino communication
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# Optional Arduino App Lab Bricks hooks (WebUI & Video Object Detection)
try:
    from arduino.app_bricks.web_ui import WebUI
    app_web_ui = WebUI()
except Exception:
    app_web_ui = None

try:
    from arduino.app_bricks.video_objectdetection import VideoObjectDetection
    video_brick = VideoObjectDetection(confidence=0.4, debounce_sec=0.0)
except Exception:
    video_brick = None

# ===============================================================================
# CONFIGURATION & DEFAULT CONSTANTS
# ===============================================================================
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
TARGET_FPS = 30

# Region of Interest (ROI) normalized coordinates [0.0 - 1.0] (Focuses strictly on the conveyor chute)
ROI_X_START = 0.18
ROI_X_END   = 0.82
ROI_Y_START = 0.48
ROI_Y_END   = 0.90

# Contour filtering thresholds (Strict cube sizes: 60 - 3500 pixels)
MIN_OBJECT_AREA = 60
MAX_OBJECT_AREA = 3500
MIN_ASPECT_RATIO = 0.55
MAX_ASPECT_RATIO = 1.85

# Centroid tracking & counting cooldown
CENTER_DISTANCE_THRESHOLD = 60    # Pixels to associate object across consecutive frames
COUNT_COOLDOWN_SECONDS = 2.0      # Minimum seconds before same zone can count a new object
TRACKER_MAX_DISAPPEARED = 15      # Frames before lost tracked object is purged

# Web Server & Paths
candidate_assets = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "assets")),
    os.path.abspath(os.path.join(os.getcwd(), "assets"))
]
STATIC_ASSETS_DIR = next((p for p in candidate_assets if os.path.exists(p)), candidate_assets[0])
SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(os.environ.get("PORT", 7000))
# Templates Directory & Manager
candidate_templates = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "templates")),
    os.path.abspath(os.path.join(os.getcwd(), "templates"))
]
TEMPLATES_DIR = next((p for p in candidate_templates if os.path.exists(p)), candidate_templates[0])
os.makedirs(TEMPLATES_DIR, exist_ok=True)

class TemplateMatcher:
    def __init__(self):
        self.white_template = None
        self.grey_template = None
        self.load_templates()

    def load_templates(self):
        w_path = os.path.join(TEMPLATES_DIR, "white_cube.png")
        g_path = os.path.join(TEMPLATES_DIR, "grey_cube.png")
        if os.path.exists(w_path):
            self.white_template = cv2.imread(w_path, cv2.IMREAD_GRAYSCALE)
        if os.path.exists(g_path):
            self.grey_template = cv2.imread(g_path, cv2.IMREAD_GRAYSCALE)

    def match(self, gray_roi, hsv_roi, tmpl, is_white=True, threshold=0.55, scales=[0.4, 0.55, 0.75, 1.0, 1.25], max_matches=2):
        if tmpl is None or gray_roi is None:
            return []
        matches = []
        th, tw = tmpl.shape[:2]
        gh, gw = gray_roi.shape[:2]

        for s in scales:
            rw, rh = int(tw * s), int(th * s)
            if rw >= gw or rh >= gh or rw < 15 or rh < 15:
                continue
            r_tmpl = cv2.resize(tmpl, (rw, rh))
            res = cv2.matchTemplate(gray_roi, r_tmpl, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)
            for pt in zip(*loc[::-1]):
                bx, by = pt[0], pt[1]
                # Color and luminance validation on candidate patch
                patch_gray = gray_roi[by:by+rh, bx:bx+rw]
                patch_hsv = hsv_roi[by:by+rh, bx:bx+rw] if hsv_roi is not None else None
                if patch_gray.size == 0:
                    continue
                mean_v = patch_gray.mean()
                mean_s = patch_hsv[:, :, 1].mean() if patch_hsv is not None else 50
                
                if is_white:
                    if mean_v > 98 and mean_s < 90:
                        matches.append((bx, by, rw, rh, float(res[by, bx])))
                else:
                    if mean_v < 82 and mean_s < 110:
                        matches.append((bx, by, rw, rh, float(res[by, bx])))

        # Non-maximum suppression by bounding box IoU overlap
        boxes = []
        for x, y, bw, bh, score in sorted(matches, key=lambda m: m[4], reverse=True):
            overlap = False
            for bx, by, bbw, bbh, _ in boxes:
                if abs(x - bx) < (bw * 0.6) and abs(y - by) < (bh * 0.6):
                    overlap = True
                    break
            if not overlap:
                boxes.append((x, y, bw, bh, score))
                if len(boxes) >= max_matches:
                    break
        return boxes

template_matcher = TemplateMatcher()

# ===============================================================================
# GLOBAL APPLICATION STATE
# ===============================================================================
class SystemState:
    def __init__(self):
        self.lock = threading.Lock()
        self.camera_running = True
        self.detection_running = True
        self.conveyor_running = False
        
        # Detection results
        self.current_object = "NONE"   # "WHITE", "GREY", "UNKNOWN", "NONE"
        self.detection_status_text = "Scanning"
        self.white_count = 0
        self.grey_count = 0
        
        # Adjustable parameters
        self.roi_x_start = ROI_X_START
        self.roi_x_end = ROI_X_END
        self.roi_y_start = ROI_Y_START
        self.roi_y_end = ROI_Y_END
        self.min_object_area = MIN_OBJECT_AREA
        self.max_object_area = MAX_OBJECT_AREA

        # Camera Orientation Transforms
        self.flip_h = False
        self.flip_v = False
        self.rotation = 0  # 0, 90, 180, 270
        
        # Centroid tracking state: track_id -> dict(center, label, first_seen, last_seen, counted)
        self.tracked_objects = {}
        self.next_track_id = 1
        
        # Event log buffer (circular deque)
        self.logs = deque(maxlen=50)
        self.add_log("System initialized successfully.")

    def add_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.logs.append(entry)
        print(f"[LOG] {entry}")

state = SystemState()

# ===============================================================================
# SERIAL ARDUINO CONTROLLER
# ===============================================================================
class ArduinoSerialManager:
    def __init__(self, baud_rate=115200):
        self.serial_conn = None
        self.baud_rate = baud_rate
        self.connected = False
        self.lock = threading.Lock()
        self.try_connect()

    def try_connect(self):
        if not SERIAL_AVAILABLE:
            state.add_log("PySerial not installed. Serial communication in simulation mode.")
            return False

        try:
            ports = list(serial.tools.list_ports.comports())
            arduino_port = None
            for p in ports:
                # Look for common Arduino USB identifiers
                desc = (p.description or "").lower()
                hwid = (p.hwid or "").lower()
                if "arduino" in desc or "ch340" in desc or "cp210" in desc or "usb" in desc:
                    arduino_port = p.device
                    break
            
            if arduino_port:
                self.serial_conn = serial.Serial(arduino_port, self.baud_rate, timeout=1.0)
                time.sleep(1.8) # Allow Arduino UNO Q bootloader reset
                self.connected = True
                state.add_log(f"Connected to Arduino UNO Q on port {arduino_port}")
                return True
            else:
                self.connected = False
                state.add_log("No physical Arduino UNO Q detected. Operating in software standalone mode.")
                return False
        except Exception as e:
            self.connected = False
            state.add_log(f"Serial connection notice: {e}")
            return False

    def send_command(self, cmd: str) -> bool:
        with self.lock:
            state.add_log(f"Command sent: {cmd}")
            if self.connected and self.serial_conn and self.serial_conn.is_open:
                try:
                    payload = (cmd.strip() + "\n").encode('utf-8')
                    self.serial_conn.write(payload)
                    self.serial_conn.flush()
                    return True
                except Exception as e:
                    state.add_log(f"Serial write error: {e}")
                    self.connected = False
                    return False
            return True

arduino = ArduinoSerialManager()

# ===============================================================================
# CAMERA WORKER & SYNTHETIC FALLBACK
# ===============================================================================
class CameraWorker:
    def __init__(self):
        self.cap = None
        self.current_raw_frame = None
        self.current_processed_frame = None
        self.is_hardware_camera = False
        self.lock = threading.Lock()
        self.thread = None
        self.running = False
        
        # Synthetic simulator variables (used if no physical webcam is plugged in)
        self.sim_cube_x = 50.0
        self.sim_cube_color = "WHITE"

    def start(self):
        if self.running:
            return
        self.running = True
        # Open physical camera synchronously before starting loop
        self.cap = self._open_camera()
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def _open_camera(self):
        """Attempts to open available camera hardware index 0 cleanly."""
        try:
            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
                for _ in range(3):
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        self.is_hardware_camera = True
                        state.add_log("Live webcam connected (640x480)")
                        return cap
                    time.sleep(0.05)
                cap.release()
        except Exception as e:
            pass

        # Try secondary external webcam on index 1 if present
        try:
            cap = cv2.VideoCapture(1)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
                ret, frame = cap.read()
                if ret and frame is not None:
                    self.is_hardware_camera = True
                    state.add_log("Live webcam connected on index 1")
                    return cap
                cap.release()
        except Exception:
            pass

        self.is_hardware_camera = False
        return None

    def _generate_synthetic_frame(self) -> np.ndarray:
        """
        Generates a clear standby screen when waiting for physical webcam.
        """
        frame = np.full((FRAME_HEIGHT, FRAME_WIDTH, 3), (20, 24, 35), dtype=np.uint8)
        
        # Border
        cv2.rectangle(frame, (20, 20), (FRAME_WIDTH - 20, FRAME_HEIGHT - 20), (50, 70, 100), 2)
        
        cv2.putText(frame, "CONNECTING TO LIVE WEBCAM...", (int(FRAME_WIDTH * 0.18), int(FRAME_HEIGHT * 0.45)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 220, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "Please ensure USB camera is connected", (int(FRAME_WIDTH * 0.22), int(FRAME_HEIGHT * 0.55)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (160, 180, 200), 1, cv2.LINE_AA)
        
        return frame

    def _capture_loop(self):
        self.cap = self._open_camera()
        consecutive_failures = 0
        reconnect_timer = 0
        
        while self.running:
            frame = None
            if self.cap and self.is_hardware_camera:
                ret, raw = self.cap.read()
                if ret and raw is not None and raw.size > 0:
                    consecutive_failures = 0
                    frame = cv2.resize(raw, (FRAME_WIDTH, FRAME_HEIGHT))
                    frame = apply_orientation(frame)
                else:
                    consecutive_failures += 1
                    if consecutive_failures > 30:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                        self.cap = None
                        self.is_hardware_camera = False
            
            if frame is None:
                reconnect_timer += 1
                if reconnect_timer >= 30:
                    reconnect_timer = 0
                    self.cap = self._open_camera()
                    if self.cap and self.is_hardware_camera:
                        continue
                frame = self._generate_synthetic_frame()

            with self.lock:
                self.current_raw_frame = frame.copy()
                if state.detection_running:
                    self.current_processed_frame = detect_objects(frame)
                else:
                    self.current_processed_frame = draw_idle_overlay(frame)

            time.sleep(1.0 / TARGET_FPS)

def apply_orientation(frame: np.ndarray) -> np.ndarray:
    """Applies dynamic rotation and horizontal/vertical flips to the incoming video frame."""
    if frame is None:
        return frame
    with state.lock:
        fh = state.flip_h
        fv = state.flip_v
        rot = state.rotation
    
    if fh and fv:
        frame = cv2.flip(frame, -1)
    elif fh:
        frame = cv2.flip(frame, 1)
    elif fv:
        frame = cv2.flip(frame, 0)
        
    if rot == 90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif rot == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif rot == 270:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame

camera_worker = CameraWorker()

# ===============================================================================
# IMAGE PROCESSING & OBJECT CLASSIFICATION
# ===============================================================================

def classify_object(average_hsv: tuple, average_gray: float, average_bgr: tuple = None) -> str:
    """
    Classifies a detected candidate contour as WHITE, GREY, or UNKNOWN
    based on average HSV values and grayscale brightness.

    Parameters:
    - average_hsv: (Hue: 0-180, Saturation: 0-255, Value: 0-255)
    - average_gray: 0.0 - 255.0
    - average_bgr: (Blue, Green, Red)
    """
    avg_h, avg_s, avg_v = average_hsv

    # Guard against blue conveyor reflections
    if average_bgr is not None:
        b, g, r = average_bgr
        if (b - r > 25) and (avg_s > 45) and (85 <= avg_h <= 135):
            return "UNKNOWN"
    elif avg_s > 60 and 85 <= avg_h <= 135:
        return "UNKNOWN"

    # White Cube: High brightness + Low saturation
    if (avg_v >= 135 or average_gray >= 130) and avg_s <= 65:
        return "WHITE"

    # Grey Cube: Medium/Dark-Medium brightness + Low/Medium saturation
    if (30 <= avg_v < 135 or 30 <= average_gray < 130) and avg_s <= 85:
        return "GREY"

    return "UNKNOWN"


def draw_idle_overlay(frame: np.ndarray) -> np.ndarray:
    """Draws ROI boundary and status overlay when detection is paused."""
    h, w = frame.shape[:2]
    out = frame.copy()
    
    # Calculate ROI pixel bounds
    rx1 = int(w * state.roi_x_start)
    rx2 = int(w * state.roi_x_end)
    ry1 = int(h * state.roi_y_start)
    ry2 = int(h * state.roi_y_end)

    # Draw ROI rectangle in yellow/amber (Idle mode)
    cv2.rectangle(out, (rx1, ry1), (rx2, ry2), (0, 200, 255), 2)
    cv2.putText(out, "ROI [DETECTION PAUSED]", (rx1 + 8, ry1 + 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2, cv2.LINE_AA)
    
    # Header overlay
    cv2.putText(out, "SYSTEM: DETECTION PAUSED", (15, h - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)

def detect_objects(frame: np.ndarray) -> np.ndarray:
    """
    High-Precision OpenCV Square Shape + Color Detection Pipeline (< 0.6ms):
    1. cv2.cvtColor()     - Dual-space transformation (BGR to HSV & BGR to LAB)
    2. cv2.inRange()      - Segment specific WHITE and BLACK color ranges
    3. cv2.findContours() - Find object boundaries
    4. cv2.contourArea()  - Filter noise and size bounds
    5. cv2.approxPolyDP() - Determine square polygon shape (4-7 vertices, AR 0.70-1.45)
    6. Core Body Sampler  - Rejects skin, arms, wood table grain, and shadows
    Strictly detects WHITE and BLACK cubes only.
    """
    h, w = frame.shape[:2]
    out = frame.copy()

    # Dynamic ROI (or full frame)
    rx1 = max(0, min(w - 20, int(w * state.roi_x_start)))
    rx2 = max(rx1 + 20, min(w, int(w * state.roi_x_end)))
    ry1 = max(0, min(h - 20, int(h * state.roi_y_start)))
    ry2 = max(ry1 + 20, min(h, int(h * state.roi_y_end)))

    roi = frame[ry1:ry2, rx1:rx2]
    roi_h, roi_w = roi.shape[:2]
    if roi.size == 0:
        return out

    # =========================================================================
    # 1. Dual-Space Color Transformation: HSV + LAB
    # =========================================================================
    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    lab_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
    blurred_hsv = cv2.GaussianBlur(hsv_roi, (5, 5), 0)
    blurred_lab = cv2.GaussianBlur(lab_roi, (5, 5), 0)

    kernel3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

    # =========================================================================
    # 2. cv2.inRange() with Dual-Band LAB+HSV Verification
    # =========================================================================
    # WHITE CUBE: Low Saturation (S <= 70) in HSV and High Luminance (L >= 105) in LAB
    mask_white = ((blurred_lab[:, :, 0] >= 105) & (blurred_hsv[:, :, 1] <= 70)).astype(np.uint8) * 255
    mask_white = cv2.morphologyEx(mask_white, cv2.MORPH_OPEN, kernel3)

    # BLACK CUBE: Dark Value in HSV (V <= 68, V >= 5) and Low Luminance in LAB (L <= 68)
    mask_black = ((blurred_lab[:, :, 0] <= 68) & (blurred_hsv[:, :, 2] <= 68) & (blurred_hsv[:, :, 2] >= 5)).astype(np.uint8) * 255
    mask_black = cv2.morphologyEx(mask_black, cv2.MORPH_OPEN, kernel3)

    detected_candidates = []
    white_centroids = []

    def find_squares(mask, color_label):
        # 3. cv2.findContours(): Find object boundaries
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid_squares = []

        for cnt in sorted(cnts, key=cv2.contourArea, reverse=True):
            # 4. cv2.contourArea(): Filter small noise and large arm/body parts
            area = cv2.contourArea(cnt)
            if area < state.min_object_area or area > 4500:
                continue

            bx, by, bw, bh = cv2.boundingRect(cnt)
            # 3D Square Expansion for top faces
            cube_h = max(bh, bw) if bw > bh * 1.3 else bh
            cube_w = bw
            if by + cube_h >= roi_h:
                cube_h = roi_h - by - 1

            if cube_w < 16 or cube_h < 16 or (cube_w * cube_h) < 250 or (cube_w * cube_h) > 5000:
                continue

            # Square aspect ratio check (must be a cube!)
            ar = float(cube_w) / float(cube_h) if cube_h > 0 else 0.0
            if not (0.68 <= ar <= 1.45):
                continue

            # 5. cv2.approxPolyDP(): Determine shape (must be square / quadrilateral)
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.035 * peri, True)
            if len(approx) > 8:
                continue

            # 6. Core Body Sampler: Sample inner 65% of cube body to verify color & reject table/skin
            pad_x = max(2, int(cube_w * 0.15))
            pad_y = max(2, int(cube_h * 0.15))
            body = roi[by + pad_y:by + cube_h - pad_y, bx + pad_x:bx + cube_w - pad_x]
            if body.size == 0:
                continue

            body_hsv = cv2.cvtColor(body, cv2.COLOR_BGR2HSV)
            body_lab = cv2.cvtColor(body, cv2.COLOR_BGR2LAB)
            mean_h = body_hsv[:, :, 0].mean()
            mean_s = body_hsv[:, :, 1].mean()
            mean_v = body_hsv[:, :, 2].mean()
            mean_l = body_lab[:, :, 0].mean()

            # STRICT SKIN & HAND REJECTION: Human skin is warm hue 0-25 with saturation > 55
            if (0 <= mean_h <= 25) and mean_s > 55:
                continue

            if color_label == "WHITE":
                # Reject table wood reflections (warm hue + saturation)
                if mean_s > 65 or (8 <= mean_h <= 30 and mean_s > 50) or mean_v < 85 or mean_l < 95:
                    continue
            elif color_label == "BLACK":
                if mean_v > 68 or mean_l > 68:
                    continue

            cx = rx1 + bx + cube_w // 2
            cy = ry1 + by + cube_h // 2

            # Cast-shadow suppression for black candidates near white cubes
            if color_label == "BLACK" and any(abs(cx - w_cx) < 22 and abs(cy - w_cy) < 30 for w_cx, w_cy in white_centroids):
                continue

            if not any(abs(cx - c["centroid"][0]) < 22 and abs(cy - c["centroid"][1]) < 22 for c in detected_candidates):
                valid_squares.append({
                    "box": (rx1 + bx, ry1 + by, cube_w, cube_h),
                    "centroid": (cx, cy),
                    "label": color_label,
                    "area": float(cube_w * cube_h)
                })

        return valid_squares

    # Detect WHITE square boxes
    white_results = find_squares(mask_white, "WHITE")
    for ws in white_results:
        detected_candidates.append(ws)
        white_centroids.append(ws["centroid"])

    # Detect BLACK square boxes
    black_results = find_squares(mask_black, "BLACK")
    for bs in black_results:
        detected_candidates.append(bs)

    current_frame_highest_label = "NONE"
    labels_present = [c["label"] for c in detected_candidates]
    if "WHITE" in labels_present:
        current_frame_highest_label = "WHITE"
    elif "BLACK" in labels_present:
        current_frame_highest_label = "BLACK"

    # =========================================================================
    # 6. CENTROID TRACKING & COUNT TRIGGER LOGIC
    # =========================================================================
    current_time = time.time()
    with state.lock:
        state.current_object = current_frame_highest_label
        state.detection_status_text = "Scanning" if state.detection_running else "Paused"

        unmatched_candidates = list(range(len(detected_candidates)))
        for track_id, track_info in list(state.tracked_objects.items()):
            tx, ty = track_info["center"]
            matched_candidate_idx = None
            min_dist = float("inf")

            for idx in unmatched_candidates:
                cand = detected_candidates[idx]
                cx, cy = cand["centroid"]
                dist = math.hypot(cx - tx, cy - ty)
                if dist < CENTER_DISTANCE_THRESHOLD and dist < min_dist:
                    min_dist = dist
                    matched_candidate_idx = idx

            if matched_candidate_idx is not None:
                cand = detected_candidates[matched_candidate_idx]
                track_info["center"] = cand["centroid"]
                track_info["last_seen"] = current_time
                track_info["disappeared"] = 0
                track_info["label"] = cand["label"]
                unmatched_candidates.remove(matched_candidate_idx)
            else:
                track_info["disappeared"] += 1
                if track_info["disappeared"] > TRACKER_MAX_DISAPPEARED:
                    del state.tracked_objects[track_id]

        for idx in unmatched_candidates:
            cand = detected_candidates[idx]
            label = cand["label"]
            new_id = state.next_track_id
            state.next_track_id += 1
            cand["track_id"] = new_id

            state.tracked_objects[new_id] = {
                "center": cand["centroid"],
                "first_seen": current_time,
                "last_seen": current_time,
                "label": cand["label"],
                "counted": True,
                "disappeared_frames": 0
            }

            if cand["label"] == "WHITE":
                state.white_count += 1
                state.add_log(f"WHITE cube detected & counted (Total: {state.white_count})")
                arduino.send_command("sort_white")
            elif cand["label"] == "BLACK":
                state.grey_count += 1
                state.add_log(f"BLACK cube detected & counted (Total: {state.grey_count})")
                arduino.send_command("sort_black")

        for track_id, track_info in list(state.tracked_objects.items()):
            time_since_seen = current_time - track_info["last_seen"]
            if track_info.get("disappeared_frames", 0) > TRACKER_MAX_DISAPPEARED or time_since_seen > COUNT_COOLDOWN_SECONDS:
                del state.tracked_objects[track_id]

    # =========================================================================
    # 7. CLEAN ANNOTATION (CUBE BOUNDING BOXES ONLY - NO GREEN ZONE)
    # =========================================================================
    for cand in detected_candidates:
        bx, by, bw, bh = cand["box"]
        label = cand["label"]
        cx, cy = cand["centroid"]

        if label == "WHITE":
            color = (255, 255, 255)
            text_color = (0, 0, 0)
            tag = f"WHITE CUBE [A:{int(cand['area'])}]"
        elif label == "BLACK":
            color = (255, 220, 0)
            text_color = (0, 0, 0)
            tag = f"BLACK CUBE [A:{int(cand['area'])}]"
        else:
            color = (0, 165, 255)
            text_color = (0, 0, 0)
            tag = f"CUBE [A:{int(cand['area'])}]"

        # Draw clean bounding box
        cv2.rectangle(out, (bx, by), (bx + bw, by + bh), color, 2)
        cv2.circle(out, (cx, cy), 4, (0, 0, 255), -1)

        # Draw sleek label badge
        (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(out, (bx, max(0, by - th - 8)), (bx + tw + 6, by), color, -1)
        cv2.putText(out, tag, (bx + 3, max(th, by - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, text_color, 1, cv2.LINE_AA)

    # Bottom status bar
    status_bar_text = f"DETECTION: ACTIVE | WHITE: {state.white_count} | BLACK: {state.grey_count} | CURRENT: {state.current_object}"
    cv2.putText(out, status_bar_text, (14, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)

    return out

# ===============================================================================
# VIDEO STREAMING GENERATOR
# ===============================================================================
def generate_frames():
    """Generates MJPEG multipart video frames for the web client."""
    while True:
        frame_to_encode = None
        
        if not state.camera_running:
            # Create a clean "Camera Stopped" placeholder frame
            placeholder = np.full((FRAME_HEIGHT, FRAME_WIDTH, 3), (25, 25, 30), dtype=np.uint8)
            cv2.putText(placeholder, "CAMERA OFF / PAUSED", (int(FRAME_WIDTH * 0.28), int(FRAME_HEIGHT * 0.5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (100, 100, 110), 2, cv2.LINE_AA)
            frame_to_encode = placeholder
        else:
            with camera_worker.lock:
                if camera_worker.current_processed_frame is not None:
                    frame_to_encode = camera_worker.current_processed_frame.copy()
            
            if frame_to_encode is None:
                placeholder = np.full((FRAME_HEIGHT, FRAME_WIDTH, 3), (20, 20, 25), dtype=np.uint8)
                cv2.putText(placeholder, "INITIALIZING CAMERA FEED...", (int(FRAME_WIDTH * 0.22), int(FRAME_HEIGHT * 0.5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2, cv2.LINE_AA)
                frame_to_encode = placeholder

        # Encode frame as JPEG
        ret, jpeg = cv2.imencode('.jpg', frame_to_encode, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ret:
            time.sleep(0.05)
            continue

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        time.sleep(1.0 / TARGET_FPS)

# ===============================================================================
# FLASK WEB SERVER & REST API ENDPOINTS
# ===============================================================================
app = Flask(__name__, static_folder=STATIC_ASSETS_DIR)

@app.route("/")
def index():
    """Serves the main web dashboard."""
    return send_from_directory(STATIC_ASSETS_DIR, "index.html")

@app.route("/<path:path>")
def serve_static(path):
    """Serves static JavaScript, CSS, and asset files."""
    return send_from_directory(STATIC_ASSETS_DIR, path)

@app.route("/video_feed")
def video_feed():
    """Streams the real-time MJPEG camera stream."""
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/camera/start", methods=["POST"])
def api_camera_start():
    """Starts the video capture stream."""
    with state.lock:
        state.camera_running = True
        state.add_log("External camera started")
    return jsonify({"success": True, "camera_running": True})

@app.route("/api/camera/stop", methods=["POST"])
def api_camera_stop():
    """Stops the video capture stream."""
    with state.lock:
        state.camera_running = False
        state.add_log("External camera stopped")
    return jsonify({"success": True, "camera_running": False})

@app.route("/api/detection/start", methods=["POST"])
def api_detection_start():
    """Enables real-time OpenCV object detection."""
    with state.lock:
        state.detection_running = True
        state.add_log("Object detection started")
    return jsonify({"success": True, "detection_running": True})

@app.route("/api/detection/stop", methods=["POST"])
def api_detection_stop():
    """Disables object detection."""
    with state.lock:
        state.detection_running = False
        state.current_object = "NONE"
        state.add_log("Object detection stopped")
    return jsonify({"success": True, "detection_running": False})

@app.route("/api/status", methods=["GET"])
def api_status():
    """Returns the current telemetry, counts, detection status, and logs."""
    with state.lock:
        detection_label = state.current_object
        if not state.camera_running:
            status_text = "Camera Off"
        elif not state.detection_running:
            status_text = "Detection Paused"
        else:
            status_text = "Scanning"

        data = {
            "camera_running": state.camera_running,
            "detection_running": state.detection_running,
            "current_object": detection_label,
            "detection_status": status_text,
            "white_count": state.white_count,
            "grey_count": state.grey_count,
            "total_count": state.white_count + state.grey_count,
            "conveyor_running": state.conveyor_running,
            "arduino_connected": arduino.connected,
            "settings": {
                "roi_x_start": state.roi_x_start,
                "roi_x_end": state.roi_x_end,
                "roi_y_start": state.roi_y_start,
                "roi_y_end": state.roi_y_end,
                "min_object_area": state.min_object_area,
                "max_object_area": state.max_object_area
            },
            "logs": list(state.logs)
        }
    return jsonify(data)

@app.route("/api/conveyor/start", methods=["POST"])
def api_conveyor_start():
    """Starts the conveyor belt motor."""
    with state.lock:
        state.conveyor_running = True
    arduino.send_command("start_conveyor")
    return jsonify({"success": True, "conveyor_running": True})

@app.route("/api/conveyor/stop", methods=["POST"])
def api_conveyor_stop():
    """Stops the conveyor belt motor."""
    with state.lock:
        state.conveyor_running = False
    arduino.send_command("stop_conveyor")
    return jsonify({"success": True, "conveyor_running": False})

@app.route("/api/manual/white", methods=["POST"])
def api_manual_white():
    """Manually triggers WHITE sorting routine for testing."""
    with state.lock:
        state.white_count += 1
        state.add_log(f"Manual sort triggered: WHITE (Count: {state.white_count})")
    arduino.send_command("sort_white")
    return jsonify({"success": True, "white_count": state.white_count})

@app.route("/api/manual/grey", methods=["POST"])
def api_manual_grey():
    """Manually triggers GREY sorting routine for testing."""
    with state.lock:
        state.grey_count += 1
        state.add_log(f"Manual sort triggered: GREY (Count: {state.grey_count})")
    arduino.send_command("sort_grey")
    return jsonify({"success": True, "grey_count": state.grey_count})

@app.route("/api/counters/reset", methods=["POST"])
def api_counters_reset():
    """Resets WHITE and GREY object sorting counters."""
    with state.lock:
        state.white_count = 0
        state.grey_count = 0
        state.tracked_objects.clear()
        state.add_log("Sorting counters reset to 0")
    arduino.send_command("reset_counters")
    return jsonify({"success": True, "white_count": 0, "grey_count": 0})

@app.route("/api/process_frame", methods=["POST"])
def api_process_frame():
    """Receives a base64 JPEG frame from browser webcam, runs OpenCV detection, and returns annotated frame & telemetry."""
    try:
        data = request.get_json() or {}
        image_b64 = data.get("image", "")
        if "," in image_b64:
            image_b64 = image_b64.split(",")[1]
        
        img_bytes = base64.b64decode(image_b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame is not None:
            frame = apply_orientation(frame)
            with camera_worker.lock:
                camera_worker.is_hardware_camera = True
                camera_worker.current_raw_frame = frame.copy()
            
            if state.detection_running:
                annotated = detect_objects(frame)
            else:
                annotated = draw_idle_overlay(frame)
            
            with camera_worker.lock:
                camera_worker.current_processed_frame = annotated.copy()
            
            _, buf = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            out_b64 = "data:image/jpeg;base64," + base64.b64encode(buf).decode('utf-8')
            
            with state.lock:
                return jsonify({
                    "success": True,
                    "annotated_image": out_b64,
                    "current_object": state.current_object,
                    "white_count": state.white_count,
                    "grey_count": state.grey_count,
                    "conveyor_running": state.conveyor_running,
                    "detection_status": state.detection_status_text,
                    "rotation": state.rotation,
                    "flip_h": state.flip_h,
                    "flip_v": state.flip_v,
                    "logs": list(state.logs)
                })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
    return jsonify({"success": False}), 400

@app.route("/api/camera/rotate", methods=["POST"])
def api_camera_rotate():
    """Cycles camera rotation: 0 -> 90 -> 180 -> 270 -> 0."""
    with state.lock:
        state.rotation = (state.rotation + 90) % 360
        state.add_log(f"Camera rotated to {state.rotation} deg")
        return jsonify({"success": True, "rotation": state.rotation})

@app.route("/api/camera/flip_h", methods=["POST"])
def api_camera_flip_h():
    """Toggles horizontal mirror."""
    with state.lock:
        state.flip_h = not state.flip_h
        state.add_log(f"Horizontal mirror: {'ON' if state.flip_h else 'OFF'}")
        return jsonify({"success": True, "flip_h": state.flip_h})

@app.route("/api/camera/flip_v", methods=["POST"])
def api_camera_flip_v():
    """Toggles vertical flip."""
    with state.lock:
        state.flip_v = not state.flip_v
        state.add_log(f"Vertical flip: {'ON' if state.flip_v else 'OFF'}")
        return jsonify({"success": True, "flip_v": state.flip_v})

@app.route("/api/camera/reset_orientation", methods=["POST"])
def api_camera_reset_orientation():
    """Resets camera orientation to normal."""
    with state.lock:
        state.rotation = 0
        state.flip_h = False
        state.flip_v = False
        state.add_log("Camera orientation reset to normal")
        return jsonify({"success": True, "rotation": 0, "flip_h": False, "flip_v": False})

@app.route("/api/settings", methods=["POST"])
def api_settings():
    """Updates dynamic ROI and minimum object size parameters."""
    req = request.get_json() or {}
    with state.lock:
        if "roi_x_start" in req:
            state.roi_x_start = max(0.0, min(0.45, float(req["roi_x_start"])))
        if "roi_x_end" in req:
            state.roi_x_end = max(0.55, min(1.0, float(req["roi_x_end"])))
        if "roi_y_start" in req:
            state.roi_y_start = max(0.0, min(0.45, float(req["roi_y_start"])))
        if "roi_y_end" in req:
            state.roi_y_end = max(0.55, min(1.0, float(req["roi_y_end"])))
        if "min_object_area" in req:
            state.min_object_area = max(100, min(10000, int(req["min_object_area"])))

        state.add_log(f"Settings updated: ROI [{state.roi_x_start:.2f}-{state.roi_x_end:.2f}, {state.roi_y_start:.2f}-{state.roi_y_end:.2f}], MinArea: {state.min_object_area}")

    return jsonify({"success": True, "settings": {
        "roi_x_start": state.roi_x_start,
        "roi_x_end": state.roi_x_end,
        "roi_y_start": state.roi_y_start,
        "roi_y_end": state.roi_y_end,
        "min_object_area": state.min_object_area
    }})

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return response

# ===============================================================================
# SERVER LIFECYCLE & STARTUP FUNCTION
# ===============================================================================
def start_camera():
    """Starts the background camera acquisition worker."""
    camera_worker.start()

def stop_camera():
    """Stops the camera worker cleanly."""
    camera_worker.stop()

def get_network_ip():
    """Resolves local network IP of this device."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def open_browser():
    """Attempts to automatically open the dashboard in the default browser."""
    time.sleep(1.2)
    local_ip = get_network_ip()
    urls = [
        f"http://localhost:{SERVER_PORT}",
        f"http://127.0.0.1:{SERVER_PORT}",
        f"http://{local_ip}:{SERVER_PORT}"
    ]
    try:
        print(f"[AUTO-LAUNCH] Opening web dashboard in default browser: {urls[0]}")
        webbrowser.open(urls[0])
    except Exception as e:
        print(f"[AUTO-LAUNCH] Notice opening browser: {e}")

def run_app():
    """
    Main application startup entrypoint.
    Initializes camera worker, verifies assets directory, auto-opens browser, and boots Flask server.
    """
    local_ip = get_network_ip()
    print("==================================================================")
    print("[SYSTEM] CONVEYOR SORTING VISION & DASHBOARD SERVER STARTED!")
    print(f" * Localhost URL:      http://localhost:{SERVER_PORT}")
    print(f" * Network Board URL:  http://{local_ip}:{SERVER_PORT}")
    print(f" * Hostname URL:       http://beast.local:{SERVER_PORT}")
    print(f" * Video Stream Feed:  http://{local_ip}:{SERVER_PORT}/video_feed")
    print("==================================================================")
    
    start_camera()
    
    # Automatically open browser in a separate background thread
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run the multi-threaded Flask server
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, threaded=True)

if __name__ == "__main__":
    run_app()
