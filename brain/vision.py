import threading
import time
import math
from collections import deque
import cv2
import numpy as np

PRESETS = {
    "red":    ((0,   120, 70),  (10,  255, 255)),
    "red2":   ((170, 120, 70),  (180, 255, 255)),
    "green":  ((40,  80,  60),  (85,  255, 255)),
    "blue":   ((95,  120, 60),  (130, 255, 255)),
    "yellow": ((20,  120, 120), (35,  255, 255)),
}

MODES = {"manual", "color", "person", "shadow"}

# Shadow/stealth state machine
SHADOW_FOLLOW   = "follow"    # target moving — follow at safe distance
SHADOW_HOLD     = "hold"      # target stopped — we stop
SHADOW_CONCEAL  = "conceal"   # target stopped — moving to cover
SHADOW_HIDDEN   = "hidden"    # behind cover, watching
SHADOW_LOST     = "lost"      # lost target, searching


class TargetIntel:
    """Learns and tracks everything about the target over time."""

    def __init__(self, max_history=300):
        self.positions = deque(maxlen=max_history)    # (time, cx, cy, area)
        self.velocities = deque(maxlen=max_history)   # (time, vx, vy)
        self.stop_zones = []   # [{x, y, count, total_time}] — places target stops often
        self.move_dirs = deque(maxlen=200)  # direction angles

        self.target_moving = False
        self.target_speed = 0.0
        self.target_vx = 0.0
        self.target_vy = 0.0
        self.time_stationary = 0.0
        self.time_moving = 0.0
        self.total_stops = 0
        self.avg_stop_duration = 0.0
        self.dominant_direction = None   # "left", "right", "toward", "away"
        self.first_seen = None
        self.last_seen = None
        self.times_lost = 0
        self._stationary_since = None
        self._MOVING_THRESHOLD = 3.0  # pixels/frame — below this = stopped

    def update(self, cx, cy, area, now):
        if self.first_seen is None:
            self.first_seen = now
        self.last_seen = now

        if len(self.positions) >= 2:
            pt, px, py, _ = self.positions[-1]
            dt = max(0.001, now - pt)
            vx = (cx - px) / dt
            vy = (cy - py) / dt
            speed = math.hypot(vx, vy)

            self.target_vx = vx
            self.target_vy = vy
            self.target_speed = speed
            self.velocities.append((now, vx, vy))

            was_moving = self.target_moving
            self.target_moving = speed > self._MOVING_THRESHOLD

            if self.target_moving:
                self.time_moving += dt
                angle = math.degrees(math.atan2(vy, vx))
                self.move_dirs.append(angle)
                if self._stationary_since is not None:
                    stop_dur = now - self._stationary_since
                    self.avg_stop_duration = (
                        (self.avg_stop_duration * max(1, self.total_stops - 1) + stop_dur)
                        / max(1, self.total_stops)
                    )
                    self._stationary_since = None
            else:
                self.time_stationary += dt
                if was_moving and not self.target_moving:
                    self.total_stops += 1
                    self._stationary_since = now
                    self._record_stop_zone(cx, cy)

            self._update_dominant_direction()

        self.positions.append((now, cx, cy, area))

    def target_lost(self):
        self.times_lost += 1
        self.target_moving = False
        self.target_speed = 0.0

    def predict_position(self, dt=0.5):
        """Predict where the target will be in dt seconds."""
        if len(self.positions) < 2:
            return None
        _, cx, cy, _ = self.positions[-1]
        return (cx + self.target_vx * dt, cy + self.target_vy * dt)

    def get_report(self):
        """Generate a human-readable intelligence report."""
        if not self.positions:
            return {"summary": "No target data collected", "details": {}}

        duration = (self.last_seen - self.first_seen) if self.first_seen and self.last_seen else 0
        total_time = self.time_moving + self.time_stationary
        moving_pct = round(self.time_moving / max(0.1, total_time) * 100, 1)

        behavior = "unpredictable"
        if moving_pct > 75:
            behavior = "highly mobile — rarely stops"
        elif moving_pct > 50:
            behavior = "moderately active — regular pauses"
        elif moving_pct > 25:
            behavior = "mostly stationary — brief movements"
        else:
            behavior = "stationary — minimal movement"

        summary_parts = []
        summary_parts.append(f"Tracked for {duration:.0f}s.")
        summary_parts.append(f"Moving {moving_pct}% of time — {behavior}.")
        if self.total_stops > 0:
            summary_parts.append(
                f"Stopped {self.total_stops} times, avg {self.avg_stop_duration:.1f}s each."
            )
        if self.dominant_direction:
            summary_parts.append(f"Tends to move {self.dominant_direction}.")
        if self.times_lost > 0:
            summary_parts.append(f"Lost visual {self.times_lost} time(s).")
        if self.stop_zones:
            top = sorted(self.stop_zones, key=lambda z: z["count"], reverse=True)[:3]
            zones = ", ".join(f"({z['x']},{z['y']})×{z['count']}" for z in top)
            summary_parts.append(f"Frequent stop zones: {zones}.")

        return {
            "summary": " ".join(summary_parts),
            "details": {
                "tracked_seconds": round(duration, 1),
                "moving_pct": moving_pct,
                "stationary_pct": round(100 - moving_pct, 1),
                "total_stops": self.total_stops,
                "avg_stop_duration": round(self.avg_stop_duration, 1),
                "times_lost": self.times_lost,
                "dominant_direction": self.dominant_direction,
                "behavior": behavior,
                "current_speed": round(self.target_speed, 1),
                "is_moving": self.target_moving,
                "stop_zones": self.stop_zones[:5],
            },
        }

    def _record_stop_zone(self, cx, cy, merge_radius=40):
        for z in self.stop_zones:
            if math.hypot(cx - z["x"], cy - z["y"]) < merge_radius:
                z["count"] += 1
                z["x"] = int((z["x"] * (z["count"] - 1) + cx) / z["count"])
                z["y"] = int((z["y"] * (z["count"] - 1) + cy) / z["count"])
                return
        self.stop_zones.append({"x": int(cx), "y": int(cy), "count": 1, "total_time": 0})

    def _update_dominant_direction(self):
        if len(self.move_dirs) < 10:
            self.dominant_direction = None
            return
        recent = list(self.move_dirs)[-50:]
        avg_angle = math.degrees(math.atan2(
            sum(math.sin(math.radians(a)) for a in recent) / len(recent),
            sum(math.cos(math.radians(a)) for a in recent) / len(recent),
        ))
        if -45 <= avg_angle <= 45:
            self.dominant_direction = "right"
        elif 45 < avg_angle <= 135:
            self.dominant_direction = "away"
        elif -135 <= avg_angle < -45:
            self.dominant_direction = "toward"
        else:
            self.dominant_direction = "left"

# Priority scoring weights
W_CONFIDENCE = 0.25
W_SIZE = 0.35
W_CENTER = 0.25
W_SELECTED = 0.15  # bonus for user-selected target


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _score_detection(det, frame_w, frame_h, selected_idx=None, det_idx=0):
    """Score a detection for target priority.
    Higher score = higher priority."""
    bbox = det["bbox"]
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    conf = det.get("confidence", 0)

    # Confidence score: direct
    s_conf = conf

    # Size score: prefer medium-large targets, normalize to frame area
    frame_area = max(1, frame_w * frame_h)
    area_frac = area / frame_area
    s_size = min(1.0, area_frac * 10)  # 10% of frame = 1.0

    # Center proximity: prefer targets near horizontal center
    dist_from_center = abs(cx - frame_w / 2) / (frame_w / 2)
    s_center = 1.0 - dist_from_center

    # User selection bonus
    s_selected = 1.0 if (selected_idx is not None and det_idx == selected_idx) else 0.0

    score = (W_CONFIDENCE * s_conf + W_SIZE * s_size +
             W_CENTER * s_center + W_SELECTED * s_selected)
    return round(score, 4)


class Vision:
    def __init__(self, cam_url, motors):
        self.cam_url = cam_url
        self.motors = motors

        self.mode = "manual"
        self.color = "red"
        self.kp = 0.30
        self.ki = 0.02
        self.kd = 0.15
        self.base_speed = 150
        self.target_area = 15000

        # PID internal state
        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_time = 0.0
        self._max_integral = 5000

        # Search behavior
        self._lost_frames = 0
        self._last_error_sign = 0
        self._search_speed = 80
        self._LOST_THRESHOLD = 10
        self._SEARCH_FLIP = 60

        # Telemetry
        self._pid_out = {"error": 0, "p": 0, "i": 0, "d": 0, "turn": 0, "fwd": 0}
        self._search_state = "idle"
        self._yolo_error = None
        self._rssi = None
        self._rssi_time = 0.0

        # User target selection
        self._selected_idx = None
        self._selected_xy = None

        # Obstacle avoidance
        self._obstacle_dist = None
        self._obstacle_cam = False
        self._obstacle_stop_dist = 15
        self._obstacle_slow_dist = 40

        # Shadow mode state
        self._shadow_state = SHADOW_LOST
        self._shadow_safe_area = 8000   # target area to maintain (= safe distance)
        self._shadow_hold_time = 0.0    # how long we've been holding
        self._cover_objects = []        # detected non-target objects for hiding
        self._cover_target = None       # (cx, cy) of object we're hiding behind

        # Target intelligence
        self.intel = TargetIntel()

        # Scene description
        self._scene_desc = ""
        self._scene_time = 0.0
        self._scene_interval = 2.0  # seconds between scene updates

        self.status = {
            "mode": self.mode,
            "color": self.color,
            "target": None,
            "detections": [],
            "fps": 0.0,
            "running": False,
            "search_state": "idle",
            "pid": self._pid_out,
            "rssi": None,
            "obstacle_dist": None,
            "obstacle_cam": False,
            "shadow_state": "idle",
            "intel": None,
            "stream_url": self.cam_url,
        }

        self._stop = False
        self._thread = None
        self._yolo = None
        self._lock = threading.Lock()

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode}")
        with self._lock:
            self.mode = mode
            self._integral = 0.0
            self._prev_error = 0.0
            self._prev_time = 0.0
            self._lost_frames = 0
            self._search_state = "idle"
            self._selected_idx = None
            self._selected_xy = None
            self._shadow_state = SHADOW_LOST
            self._shadow_hold_time = 0.0
            self._cover_target = None
            if mode == "shadow":
                self.intel = TargetIntel()
            self.motors.drive(0, 0)

    def set_color(self, preset):
        if preset not in PRESETS:
            raise ValueError(f"unknown color: {preset}")
        with self._lock:
            self.color = preset

    def manual_drive(self, left, right):
        if self.mode == "manual":
            self.motors.drive(left, right)

    def select_target(self, index=None, x=None, y=None):
        """User selects a target by detection index or click (x,y) in frame coords."""
        with self._lock:
            if index is not None:
                self._selected_idx = int(index)
                self._selected_xy = None
            elif x is not None and y is not None:
                self._selected_xy = (int(x), int(y))
                self._selected_idx = None
            else:
                self._selected_idx = None
                self._selected_xy = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        self.motors.stop()

    def _get_yolo(self):
        # Lazy import — ultralytics pulls torch, don't load unless used.
        if self._yolo is None:
            from ultralytics import YOLO
            self._yolo = YOLO("yolov8n.pt")
        return self._yolo

    def _loop(self):
        cap = cv2.VideoCapture(self.cam_url)
        self.status["running"] = cap.isOpened()
        t_last = time.time()
        fail_count = 0
        FAIL_RECONNECT_THRESHOLD = 30  # ~1s at 30fps of bad reads

        while not self._stop:
            ok, frame = cap.read()
            if not ok:
                fail_count += 1
                self.status["running"] = False
                if fail_count >= FAIL_RECONNECT_THRESHOLD:
                    self.motors.drive(0, 0)
                    try:
                        cap.release()
                    except Exception:
                        pass
                    time.sleep(1.0)
                    cap = cv2.VideoCapture(self.cam_url)
                    self.status["running"] = cap.isOpened()
                    fail_count = 0
                else:
                    time.sleep(0.05)
                continue
            fail_count = 0

            h, w = frame.shape[:2]
            target, detections = None, []

            if self.mode == "color":
                target, detections = self._track_color(frame)
            elif self.mode in ("person", "shadow"):
                try:
                    target, detections = self._track_person(frame)
                    self._yolo_error = None
                except Exception as e:
                    target, detections = None, []
                    self._yolo_error = f"{type(e).__name__}: {e}"

            # Camera-based obstacle detection: look for large objects in bottom third
            self._obstacle_cam = self._detect_obstacle_cam(frame)

            # Ultrasonic obstacle distance
            now_t = time.time()
            if now_t - self._rssi_time > 2:
                self._rssi = self.motors.rssi()
                self._obstacle_dist = self.motors.distance()
                self._rssi_time = now_t

            # Obstacle speed modifier
            obstacle_factor = 1.0
            obstacle_blocked = False
            if self._obstacle_dist is not None:
                if self._obstacle_dist <= self._obstacle_stop_dist:
                    obstacle_factor = 0.0
                    obstacle_blocked = True
                elif self._obstacle_dist <= self._obstacle_slow_dist:
                    obstacle_factor = (self._obstacle_dist - self._obstacle_stop_dist) / (
                        self._obstacle_slow_dist - self._obstacle_stop_dist
                    )
            if self._obstacle_cam and not obstacle_blocked:
                obstacle_factor = min(obstacle_factor, 0.3)

            if self.mode in ("color", "person", "shadow"):
                if target:
                    cx, _cy, area = target
                    error = cx - w // 2

                    # Update target intelligence
                    self.intel.update(cx, _cy, area, time.time())

                    if self._lost_frames > 0:
                        self._integral = 0.0
                        self._prev_time = 0.0
                    self._lost_frames = 0
                    self._last_error_sign = 1 if error >= 0 else -1

                    now_pid = time.time()
                    dt_pid = max(1e-3, (now_pid - self._prev_time) if self._prev_time > 0 else 0.033)
                    self._prev_time = now_pid

                    self._integral += error * dt_pid
                    self._integral = _clamp(self._integral, -self._max_integral, self._max_integral)
                    derivative = (error - self._prev_error) / dt_pid
                    self._prev_error = error

                    p_term = self.kp * error
                    i_term = self.ki * self._integral
                    d_term = self.kd * derivative
                    turn = p_term + i_term + d_term

                    # Adaptive speed
                    area_ratio = area / max(1, self.target_area)
                    speed_factor = _clamp(1.0 - area_ratio, -0.5, 1.0)
                    forward = self.base_speed * speed_factor

                    # === SHADOW MODE LOGIC ===
                    if self.mode == "shadow":
                        forward, turn = self._shadow_logic(
                            frame, target, detections, forward, turn, w, h, dt_pid
                        )
                    # === END SHADOW ===

                    # Apply obstacle avoidance
                    if obstacle_blocked:
                        forward = 0
                    else:
                        forward *= obstacle_factor

                    left = _clamp(forward + turn, -255, 255)
                    right = _clamp(forward - turn, -255, 255)
                    self.motors.drive(left, right)

                    self._pid_out = {
                        "error": round(error, 1), "p": round(p_term, 1),
                        "i": round(i_term, 1), "d": round(d_term, 1),
                        "turn": round(turn, 1), "fwd": round(forward, 1),
                    }
                    self._search_state = "locked"
                else:
                    self._lost_frames += 1
                    self._prev_error = 0.0
                    self.intel.target_lost()
                    if self.mode == "shadow":
                        self._shadow_state = SHADOW_LOST

                    if self._lost_frames > self._LOST_THRESHOLD:
                        direction = self._last_error_sign or 1
                        cycles = (self._lost_frames - self._LOST_THRESHOLD) // self._SEARCH_FLIP
                        if cycles % 2 == 1:
                            direction *= -1
                        spd = self._search_speed * direction
                        self.motors.drive(spd, -spd)
                        self._search_state = "searching"
                    else:
                        self.motors.drive(0, 0)
                        self._search_state = "acquiring"

            if self.mode == "manual":
                self._search_state = "idle"
                # Obstacle avoidance in manual mode too
                if obstacle_blocked:
                    self.motors.drive(0, 0)

            # Update scene description periodically
            self._describe_scene(frame)

            now = time.time()
            dt = max(1e-3, now - t_last)
            t_last = now

            # Compact intel snapshot for status
            intel_snap = None
            if self.mode in ("person", "shadow"):
                if self.intel.positions:
                    r = self.intel.get_report()
                    intel_snap = {
                        "summary": r["summary"],
                        "is_moving": r["details"].get("is_moving", False),
                        "speed": r["details"].get("current_speed", 0),
                        "moving_pct": r["details"].get("moving_pct", 0),
                        "total_stops": r["details"].get("total_stops", 0),
                        "behavior": r["details"].get("behavior", ""),
                        "direction": r["details"].get("dominant_direction"),
                        "stop_zones": r["details"].get("stop_zones", [])[:3],
                    }
                else:
                    if self._yolo_error:
                        summary = f"YOLO error: {self._yolo_error}"
                    else:
                        summary = "Acquiring target — no person detected yet"
                    intel_snap = {
                        "summary": summary,
                        "is_moving": False,
                        "speed": 0,
                        "moving_pct": 0,
                        "total_stops": 0,
                        "behavior": "acquiring",
                        "direction": None,
                        "stop_zones": [],
                    }

            self.status = {
                "mode": self.mode,
                "color": self.color,
                "target": (
                    {"x": target[0], "y": target[1], "area": int(target[2])}
                    if target else None
                ),
                "detections": detections,
                "fps": round(1.0 / dt, 1),
                "running": True,
                "frame_w": w,
                "frame_h": h,
                "search_state": self._search_state,
                "pid": self._pid_out,
                "rssi": self._rssi,
                "obstacle_dist": self._obstacle_dist,
                "obstacle_cam": self._obstacle_cam,
                "shadow_state": self._shadow_state if self.mode == "shadow" else "idle",
                "intel": intel_snap,
                "stream_url": self.cam_url,
                "scene": self._scene_desc,
            }

        cap.release()
        self.status["running"] = False

    def _track_color(self, frame):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        if self.color in ("red", "red2"):
            lo1, hi1 = PRESETS["red"]
            lo2, hi2 = PRESETS["red2"]
            mask = cv2.inRange(hsv, np.array(lo1), np.array(hi1)) | \
                   cv2.inRange(hsv, np.array(lo2), np.array(hi2))
        else:
            lower, upper = PRESETS[self.color]
            mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, []
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
        h, w = frame.shape[:2]
        detections = []
        for i, c in enumerate(contours):
            area = cv2.contourArea(c)
            if area < 500:
                continue
            x, y, w_, h_ = cv2.boundingRect(c)
            detections.append({
                "label": self.color,
                "confidence": round(min(1.0, area / 30000.0), 3),
                "bbox": [int(x), int(y), int(x + w_), int(y + h_)],
                "is_target": False,
            })

        # Resolve user selection by click proximity
        selected = self._resolve_selected(detections, w, h)

        # Score and pick best target
        primary = None
        if detections:
            best_i = self._pick_best(detections, w, h, selected)
            detections[best_i]["is_target"] = True
            d = detections[best_i]
            cx = (d["bbox"][0] + d["bbox"][2]) // 2
            cy = (d["bbox"][1] + d["bbox"][3]) // 2
            area = (d["bbox"][2] - d["bbox"][0]) * (d["bbox"][3] - d["bbox"][1])
            primary = (cx, cy, area)

        return primary, detections

    def _track_person(self, frame):
        yolo = self._get_yolo()
        # class 0 == person in COCO
        results = yolo(frame, classes=[0], verbose=False)[0]
        if len(results.boxes) == 0:
            return None, []
        boxes = results.boxes.xyxy.cpu().numpy()
        confs = results.boxes.conf.cpu().numpy()
        h, w = frame.shape[:2]
        detections = []
        for i, (box, conf) in enumerate(zip(boxes, confs)):
            x1, y1, x2, y2 = box
            detections.append({
                "label": "person",
                "confidence": round(float(conf), 3),
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                "is_target": False,
            })

        # Resolve user selection by click proximity
        selected = self._resolve_selected(detections, w, h)

        # Score and pick best target
        best_i = self._pick_best(detections, w, h, selected)
        detections[best_i]["is_target"] = True
        d = detections[best_i]
        x1, y1, x2, y2 = d["bbox"]
        primary = (int((x1 + x2) / 2), int((y1 + y2) / 2),
                   float((x2 - x1) * (y2 - y1)))
        return primary, detections

    def _describe_scene(self, frame):
        """Run YOLO with all COCO classes and build a text description."""
        now = time.time()
        if now - self._scene_time < self._scene_interval:
            return
        self._scene_time = now

        yolo = self._get_yolo()
        results = yolo(frame, verbose=False)[0]
        if len(results.boxes) == 0:
            self._scene_desc = "Nothing detected in view."
            return

        names = results.names  # {0: 'person', 1: 'bicycle', ...}
        classes = results.boxes.cls.cpu().numpy().astype(int)
        confs = results.boxes.conf.cpu().numpy()

        # Count objects by class (only confident detections)
        counts = {}
        for cls_id, conf in zip(classes, confs):
            if conf < 0.35:
                continue
            label = names.get(cls_id, f"object_{cls_id}")
            counts[label] = counts.get(label, 0) + 1

        if not counts:
            self._scene_desc = "Nothing clearly visible."
            return

        # Build description
        parts = []
        for label, count in sorted(counts.items(), key=lambda x: -x[1]):
            if count == 1:
                parts.append(f"1 {label}")
            else:
                parts.append(f"{count} {label}s")

        self._scene_desc = "Detected: " + ", ".join(parts) + "."

    def _resolve_selected(self, detections, frame_w, frame_h):
        """If user clicked on the video, find the detection closest to that point."""
        if self._selected_idx is not None and self._selected_idx < len(detections):
            return self._selected_idx
        if self._selected_xy is not None and detections:
            sx, sy = self._selected_xy
            best_i, best_d = None, float("inf")
            for i, det in enumerate(detections):
                cx = (det["bbox"][0] + det["bbox"][2]) / 2
                cy = (det["bbox"][1] + det["bbox"][3]) / 2
                d = (cx - sx) ** 2 + (cy - sy) ** 2
                if d < best_d:
                    best_d = d
                    best_i = i
            if best_i is not None:
                self._selected_idx = best_i
                self._selected_xy = None
                return best_i
        return None

    def _pick_best(self, detections, frame_w, frame_h, selected_idx=None):
        """Pick the best target using priority scoring."""
        best_i, best_score = 0, -1
        for i, det in enumerate(detections):
            s = _score_detection(det, frame_w, frame_h, selected_idx, i)
            det["score"] = s
            if s > best_score:
                best_score = s
                best_i = i
        return best_i

    def _shadow_logic(self, frame, target, detections, forward, turn, w, h, dt):
        """Shadow mode state machine: follow → hold → conceal → hidden."""
        cx, cy, area = target
        intel = self.intel

        # Maintain safer following distance in shadow mode
        safe_area = self._shadow_safe_area
        area_ratio = area / max(1, safe_area)

        if intel.target_moving:
            # Target is moving — follow at safe distance
            self._shadow_state = SHADOW_FOLLOW
            self._shadow_hold_time = 0.0
            self._cover_target = None
            # Reduce speed to stay farther back
            speed_factor = _clamp(1.0 - area_ratio, -0.3, 0.7)
            forward = self.base_speed * 0.6 * speed_factor
        else:
            # Target has stopped
            if self._shadow_state == SHADOW_FOLLOW:
                self._shadow_state = SHADOW_HOLD
                self._shadow_hold_time = 0.0

            if self._shadow_state == SHADOW_HOLD:
                # Stop immediately
                forward = 0
                turn = 0
                self._shadow_hold_time += dt

                # After holding for 1.5s, look for cover
                if self._shadow_hold_time > 1.5:
                    cover = self._find_cover(frame, detections, w, h)
                    if cover:
                        self._cover_target = cover
                        self._shadow_state = SHADOW_CONCEAL
                    else:
                        # No cover found — just slowly back away
                        if area_ratio > 0.8:
                            forward = -self.base_speed * 0.3
                        else:
                            forward = 0
                        self._shadow_state = SHADOW_HIDDEN

            elif self._shadow_state == SHADOW_CONCEAL:
                # Move toward cover object
                if self._cover_target:
                    cover_cx, cover_cy = self._cover_target
                    cover_error = cover_cx - w // 2
                    turn = self.kp * cover_error * 0.7
                    # Move forward slowly toward cover
                    forward = self.base_speed * 0.35
                    # Check if we're roughly aligned with cover
                    if abs(cover_error) < w * 0.08:
                        self._shadow_state = SHADOW_HIDDEN
                else:
                    self._shadow_state = SHADOW_HIDDEN

            elif self._shadow_state == SHADOW_HIDDEN:
                # Stay put — just maintain orientation toward target
                forward = 0
                turn = turn * 0.15  # minimal correction to keep watching

        return forward, turn

    def _find_cover(self, frame, target_dets, w, h):
        """Find a non-target object in the scene to hide behind.
        Uses YOLO to detect all objects; picks one that's to the side of the target."""
        try:
            yolo = self._get_yolo()
            results = yolo(frame, verbose=False)[0]
            if len(results.boxes) == 0:
                return None

            boxes = results.boxes.xyxy.cpu().numpy()
            classes = results.boxes.cls.cpu().numpy()

            # Get target bbox center
            target_det = next((d for d in target_dets if d.get("is_target")), None)
            if not target_det:
                return None
            t_cx = (target_det["bbox"][0] + target_det["bbox"][2]) / 2
            t_cy = (target_det["bbox"][1] + target_det["bbox"][3]) / 2

            best_cover = None
            best_score = -1

            for box, cls_id in zip(boxes, classes):
                if int(cls_id) == 0:  # skip persons
                    continue
                x1, y1, x2, y2 = box
                cover_area = (x2 - x1) * (y2 - y1)
                if cover_area < 2000:  # too small to hide behind
                    continue

                cover_cx = (x1 + x2) / 2
                cover_cy = (y1 + y2) / 2

                # Score: prefer objects between us (center) and the target,
                # and objects that are large enough to occlude
                dist_to_center = abs(cover_cx - w / 2)
                size_score = min(1.0, cover_area / (w * h * 0.05))
                # Prefer objects on the same horizontal band as target
                vertical_proximity = 1.0 - abs(cover_cy - t_cy) / h
                score = size_score * 0.5 + vertical_proximity * 0.3 + (1.0 - dist_to_center / (w / 2)) * 0.2

                if score > best_score:
                    best_score = score
                    best_cover = (int(cover_cx), int(cover_cy))

            return best_cover
        except Exception:
            return None

    def _detect_obstacle_cam(self, frame):
        """Detect large objects in the bottom third of the frame as potential obstacles."""
        h, w = frame.shape[:2]
        bottom = frame[h * 2 // 3:, :]
        gray = cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = edges.sum() / (255.0 * edges.size)
        return edge_density > 0.12
