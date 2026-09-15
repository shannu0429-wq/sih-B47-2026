import cv2
import os
import time
import threading
import requests
import atexit
import signal
import numpy as np
from datetime import datetime
from ultralytics import YOLO


ESP32_IP = "172.25.38.138"

ESP32_STREAM_URL = f"http://{ESP32_IP}:81/stream"

ESP32_STATUS_URL = f"http://{ESP32_IP}/status"
ESP32_BUZZER_ON_URL = f"http://{ESP32_IP}/buzzer/on"
ESP32_BUZZER_OFF_URL = f"http://{ESP32_IP}/buzzer/off"
ESP32_BUZZER_TEST_URL = f"http://{ESP32_IP}/buzzer/test"

def set_esp32_ip(new_ip: str):
    global ESP32_IP, ESP32_STREAM_URL, ESP32_STATUS_URL, ESP32_BUZZER_ON_URL, ESP32_BUZZER_OFF_URL, ESP32_BUZZER_TEST_URL
    ESP32_IP = str(new_ip).strip()
    ESP32_STREAM_URL = f"http://{ESP32_IP}:81/stream"
    ESP32_STATUS_URL = f"http://{ESP32_IP}/status"
    ESP32_BUZZER_ON_URL = f"http://{ESP32_IP}/buzzer/on"
    ESP32_BUZZER_OFF_URL = f"http://{ESP32_IP}/buzzer/off"
    ESP32_BUZZER_TEST_URL = f"http://{ESP32_IP}/buzzer/test"
    print(f"[ESP32] IP updated to: {ESP32_IP}")
    return ESP32_IP

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "yolo11n.pt")
CONFIDENCE_THRESHOLD = 0.35
YOLO_IMG_SIZE = 480
CAPTURE_INTERVAL = 2.0  
DETECTION_INTERVAL = 0.15 


ANIMAL_CLASSES = {
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe"
}

# =============================================================================
# DIRECTORY SETTINGS
# =============================================================================
STATIC_DIR = os.path.join(BASE_DIR, "static")
CAPTURE_FOLDER_NAME = "captures"
CAPTURE_FOLDER = os.path.join(STATIC_DIR, CAPTURE_FOLDER_NAME)
ROOT_CAPTURE_FOLDER = os.path.join(BASE_DIR, "captures")
os.makedirs(CAPTURE_FOLDER, exist_ok=True)
os.makedirs(ROOT_CAPTURE_FOLDER, exist_ok=True)

# =============================================================================
# ACTIVE USER MANAGEMENT
# =============================================================================
current_user_id = None
current_user_lock = threading.Lock()

def set_capture_user(user_id):
    global current_user_id
    with current_user_lock:
        if user_id is None:
            current_user_id = None
            return False
        try:
            current_user_id = int(user_id)
        except Exception:
            current_user_id = None
            return False
        user_folder = os.path.join(CAPTURE_FOLDER, f"user_{current_user_id}")
        os.makedirs(user_folder, exist_ok=True)
        print("--------------------------------")
        print("CAPTURE USER SET:", current_user_id)
        print("User folder:", user_folder)
        print("--------------------------------")
        return True

def get_capture_user():
    with current_user_lock:
        return current_user_id

def get_user_capture_folder():
    user_id = get_capture_user()
    if user_id is None:
        return CAPTURE_FOLDER
    folder = os.path.join(CAPTURE_FOLDER, f"user_{user_id}")
    os.makedirs(folder, exist_ok=True)
    return folder

# =============================================================================
# LOAD YOLO MODEL
# =============================================================================
print("--------------------------------")
print("Loading YOLO model from:", MODEL_PATH)
print("--------------------------------")
try:
    model = YOLO(MODEL_PATH)
    print("YOLO model loaded successfully.")
except Exception as e:
    print("ERROR LOADING YOLO MODEL:", e)
    model = None

# =============================================================================
# THREADING & STREAM STATE
# =============================================================================
camera_running = False
camera_connected = False
camera_thread = None
frame_lock = threading.Lock()
latest_raw_frame = None

last_capture_time = 0
first_animal_detected = False

detection_lock = threading.Lock()
latest_detection = {
    "monitoring": False,
    "camera_connected": False,
    "status": "Monitoring stopped",
    "detected": False,
    "animal": None,
    "confidence": 0.0,
    "buzzer": False,
    "image": "",
    "time": "",
    "event_id": "",
    "notification_id": None
}

detection_callback = None

def set_detection_callback(callback):
    global detection_callback
    detection_callback = callback

def get_detection_status():
    with detection_lock:
        return latest_detection.copy()

def update_detection_status(
    monitoring=True,
    connected=True,
    status="No animal detected",
    detected=False,
    animal=None,
    confidence=0.0,
    buzzer=False,
    image="",
    event_id="",
    notification_id=None
):
    global latest_detection
    with detection_lock:
        latest_detection = {
            "monitoring": bool(monitoring),
            "camera_connected": bool(connected),
            "status": status,
            "detected": bool(detected),
            "animal": animal,
            "confidence": float(confidence or 0.0),
            "buzzer": bool(buzzer),
            "image": image or "",
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event_id": event_id or "",
            "notification_id": notification_id
        }

def reset_detection_status():
    update_detection_status(
        monitoring=camera_running,
        connected=camera_connected,
        status="No animal detected" if camera_running else "Monitoring stopped",
        detected=False,
        animal=None,
        confidence=0.0,
        buzzer=False,
        image="",
        event_id="",
        notification_id=None
    )

def is_camera_running():
    return camera_running

# =============================================================================
# THREAD-SAFE BUZZER CONTROLLER
# =============================================================================
buzzer_lock = threading.Lock()
buzzer_is_on = False
last_buzzer_keepalive = 0

def send_esp32_buzzer_request(url):
    """Send non-blocking or short-timeout HTTP request to ESP32 Port 80."""
    try:
        resp = requests.get(url, timeout=1.0)
        return resp.ok
    except Exception as err:
        # ESP32 might be unreachable
        return False

def set_buzzer_state(target_state: bool, force: bool = False):
    """
    Thread-safe buzzer control logic.
    - HIGH = ON, LOW = OFF
    - Keeps buzzer ON with periodic keepalive to avoid ESP32 watchdog cutoff (~1.2s)
    - Sends OFF only when buzzer is currently ON (no continuous spam)
    """
    global buzzer_is_on, last_buzzer_keepalive
    current_time = time.time()
    
    with buzzer_lock:
        if target_state:
            # Animal detected: Turn ON or send keepalive
            if not buzzer_is_on or force or (current_time - last_buzzer_keepalive >= 1.2):
                threading.Thread(
                    target=send_esp32_buzzer_request,
                    args=(ESP32_BUZZER_ON_URL,),
                    daemon=True
                ).start()
                buzzer_is_on = True
                last_buzzer_keepalive = current_time
        else:
            # No animal: Turn OFF only if currently marked ON or forced
            if buzzer_is_on or force:
                threading.Thread(
                    target=send_esp32_buzzer_request,
                    args=(ESP32_BUZZER_OFF_URL,),
                    daemon=True
                ).start()
                buzzer_is_on = False
                last_buzzer_keepalive = 0

def buzzer_on():
    set_buzzer_state(True, force=True)
    return True

def buzzer_off():
    set_buzzer_state(False, force=True)
    return True

def test_buzzer():
    try:
        resp = requests.get(ESP32_BUZZER_TEST_URL, timeout=2.0)
        return resp.ok
    except Exception:
        return False

def check_esp32_status():
    """Check if ESP32 Port 80 is reachable."""
    try:
        resp = requests.get(ESP32_STATUS_URL, timeout=1.5)
        if resp.ok:
            try:
                data = resp.json()
                return {"reachable": True, "data": data}
            except Exception:
                return {"reachable": True, "data": resp.text}
        return {"reachable": False, "status_code": resp.status_code}
    except Exception as err:
        return {"reachable": False, "error": str(err)}

# =============================================================================
# MJPEG STREAM READER (PORT 81)
# =============================================================================
def mjpeg_stream_reader():
    """
    Connects to ESP32 Port 81 MJPEG stream using requests with stream=True.
    Finds JPEG start (FF D8) and end (FF D9) delimiters and decodes frames.
    Continuously reconnects if the connection drops.
    """
    global latest_raw_frame, camera_running, camera_connected
    
    print("--------------------------------")
    print(f"Connecting to ESP32 Stream: {ESP32_STREAM_URL}")
    print("--------------------------------")
    
    while camera_running:
        try:
            response = requests.get(ESP32_STREAM_URL, stream=True, timeout=5.0)
            if not response.ok:
                print(f"ESP32 Stream HTTP Error: {response.status_code}. Reconnecting in 1s...")
                camera_connected = False
                time.sleep(1.0)
                continue
            
            camera_connected = True
            print("ESP32 MJPEG Stream Connected successfully!")
            
            bytes_buffer = bytes()
            for chunk in response.iter_content(chunk_size=4096):
                if not camera_running:
                    break
                
                if not chunk:
                    continue
                
                bytes_buffer += chunk
                
                # Look for JPEG Start of Image (SOI) and End of Image (EOI)
                a = bytes_buffer.find(b"\xff\xd8")
                b = bytes_buffer.find(b"\xff\xd9")
                
                if a != -1 and b != -1:
                    if b > a:
                        jpg_data = bytes_buffer[a:b + 2]
                        bytes_buffer = bytes_buffer[b + 2:]
                        
                        # Decode JPEG frame
                        try:
                            frame = cv2.imdecode(np.frombuffer(jpg_data, dtype=np.uint8), cv2.IMREAD_COLOR)
                            if frame is not None and frame.size > 0:
                                with frame_lock:
                                    latest_raw_frame = frame
                                camera_connected = True
                        except Exception as decode_err:
                            pass
                    else:
                        # Corrupted order, advance buffer to start
                        bytes_buffer = bytes_buffer[a:]
                        
        except Exception as conn_err:
            camera_connected = False
            # Buzzer must be silent if camera disconnects
            set_buzzer_state(False)
            if camera_running:
                # Brief wait before retry
                time.sleep(1.0)
                
    camera_connected = False
    print("ESP32 MJPEG Stream Reader Stopped.")

def get_camera_frame():
    with frame_lock:
        if latest_raw_frame is None:
            return None
        return latest_raw_frame.copy()

# =============================================================================
# IMAGE CAPTURE HELPER
# =============================================================================
def save_detection_capture(animal, confidence, annotated_frame):
    r"""
    Saves detection image with bounding box in:
    1. C:\Review3\captures\<animal>_<YYYYMMDD>_<HHMMSS>_<conf>.jpg
    2. C:\Review3\static\user_captures\<user_id>\<animal>_<YYYYMMDD>_<HHMMSS>_<conf>.jpg
    Also triggers database notification callback and Telegram alerts.
    """
    user_id = get_capture_user()
    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    conf_int = int(round(confidence * 100))
    filename = f"{animal}_{timestamp_str}_{conf_int}.jpg"
    
    # Save to root captures directory
    root_filepath = os.path.join(ROOT_CAPTURE_FOLDER, filename)
    try:
        cv2.imwrite(root_filepath, annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    except Exception as e:
        print("Root capture save error:", e)
        
    # Save to user capture directory in static
    user_folder = get_user_capture_folder()
    user_filepath = os.path.join(user_folder, filename)
    try:
        cv2.imwrite(user_filepath, annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    except Exception as e:
        print("User capture save error:", e)
        
    web_relative_path = f"user_captures/{user_id}/{filename}" if user_id else f"captures/{filename}"
    event_id = f"{animal}_{now.strftime('%Y%m%d_%H%M%S_%f')}"
    detection_time = now.strftime("%Y-%m-%d %H:%M:%S")
    
    print("--------------------------------")
    print("DETECTION IMAGE CAPTURED")
    print(f"Animal: {animal.upper()} ({confidence * 100:.1f}%)")
    print(f"File: {filename}")
    print(f"Time: {detection_time}")
    print("--------------------------------")
    
    notification_id = None
    if detection_callback is not None:
        try:
            notification_id = detection_callback(
                animal=animal,
                confidence=confidence * 100,
                image_path=user_filepath,
                detected_time=now,
                event_id=event_id
            )
        except Exception as callback_err:
            print("Detection callback error:", callback_err)
            
    update_detection_status(
        monitoring=True,
        connected=True,
        status=f"ANIMAL DETECTED: {animal.upper()}",
        detected=True,
        animal=animal,
        confidence=confidence * 100,
        buzzer=True,
        image=web_relative_path,
        event_id=event_id,
        notification_id=notification_id
    )

def capture_image():
    """Manual Capture trigger from UI."""
    if not camera_running:
        return None
    
    frame = get_camera_frame()
    if frame is None:
        return None
    
    user_id = get_capture_user()
    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S_%f")
    filename = f"manual_{timestamp_str}.jpg"
    
    user_folder = get_user_capture_folder()
    filepath = os.path.join(user_folder, filename)
    cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    
    return f"user_captures/{user_id}/{filename}" if user_id else f"captures/{filename}"

# =============================================================================
# DRAWING VISUALIZATIONS
# =============================================================================
def draw_red_bounding_box(frame, x1, y1, x2, y2, name, confidence):
    """Draw red bounding box (0, 0, 255) with label."""
    # Red box in BGR is (0, 0, 255)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
    
    percentage = confidence * 100
    label = f"{name.upper()} {percentage:.1f}%"
    
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.65
    thickness = 2
    
    (text_w, text_h), baseline = cv2.getTextSize(label, font, font_scale, thickness)
    label_y = max(y1, text_h + 10)
    
    # Red background for label header
    cv2.rectangle(
        frame,
        (x1, label_y - text_h - 8),
        (x1 + text_w + 10, label_y + baseline),
        (0, 0, 255),
        -1
    )
    
    # White text inside red badge
    cv2.putText(
        frame,
        label,
        (x1 + 5, label_y - 3),
        font,
        font_scale,
        (255, 255, 255),
        thickness
    )

def draw_top_status_banner(frame, animal_detected, best_animal=None, best_confidence=0.0, is_connected=True):
    """Draws top status banner on video frame."""
    h, w = frame.shape[:2]
    
    # Semi-transparent overlay at top
    overlay = frame.copy()
    banner_height = 42
    
    if not is_connected:
        bg_color = (0, 0, 180)  # Dark Red
        text = "ESP32 CAMERA DISCONNECTED | RECONNECTING..."
    elif animal_detected:
        bg_color = (0, 0, 200)  # Bright Red
        conf_pct = best_confidence * 100
        text = f"ANIMAL DETECTED: {best_animal.upper()} {conf_pct:.1f}% | BUZZER: ON"
    else:
        bg_color = (30, 30, 30)  # Dark Charcoal
        text = "NO ANIMAL | BUZZER: OFF"
        
    cv2.rectangle(overlay, (0, 0), (w, banner_height), bg_color, -1)
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)
    
    # Text
    cv2.putText(
        frame,
        text,
        (15, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2
    )
    
    # ESP32 status tag in top right
    status_tag = "ESP32: 10.16.153.134"
    cv2.putText(
        frame,
        status_tag,
        (w - 230, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.50,
        (200, 255, 200) if is_connected else (100, 100, 255),
        1
    )

# =============================================================================
# YOLO DETECTION ENGINE
# =============================================================================
def run_yolo_detection(frame):
    """Runs YOLO11n on input frame, filtered for configured animal classes."""
    if model is None or frame is None:
        return set(), [], None, 0.0
    
    try:
        results = model.predict(
            frame,
            conf=CONFIDENCE_THRESHOLD,
            imgsz=YOLO_IMG_SIZE,
            verbose=False,
            device="cpu"
        )
        
        detected_animals = set()
        boxes = []
        best_animal = None
        best_confidence = 0.0
        
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                try:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    cls_name = model.names[cls_id].lower()
                    
                    if cls_name not in ANIMAL_CLASSES:
                        continue
                    
                    detected_animals.add(cls_name)
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    boxes.append((x1, y1, x2, y2, cls_name, conf))
                    
                    if conf > best_confidence:
                        best_confidence = conf
                        best_animal = cls_name
                except Exception:
                    pass
                
        return detected_animals, boxes, best_animal, best_confidence
    except Exception as err:
        print("YOLO Prediction Error:", err)
        return set(), [], None, 0.0

# =============================================================================
# MJPEG GENERATOR FOR /video_feed
# =============================================================================
def generate_frames():
    """
    Main generator yielding MJPEG multipart frames to the Flask website.
    Runs YOLO detection, draws red bounding boxes, triggers buzzer, and saves captures.
    """
    global last_capture_time, first_animal_detected
    
    if not camera_running:
        return
    
    last_yolo_time = 0
    last_boxes = []
    last_detected = set()
    last_best_animal = None
    last_best_confidence = 0.0
    
    while camera_running:
        raw_frame = get_camera_frame()
        
        if raw_frame is None:
            # Generate placeholder frame when waiting for stream
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(
                placeholder,
                "CONNECTING TO ESP32-CAM...",
                (120, 240),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 200, 255),
                2
            )
            cv2.putText(
                placeholder,
                f"Stream URL: {ESP32_STREAM_URL}",
                (120, 280),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (180, 180, 180),
                1
            )
            draw_top_status_banner(placeholder, False, is_connected=False)
            ret, buf = cv2.imencode(".jpg", placeholder, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ret:
                frame_bytes = buf.tobytes()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n\r\n"
                    + frame_bytes + b"\r\n"
                )
            time.sleep(0.1)
            continue
        
        display_frame = raw_frame.copy()
        current_time = time.time()
        
        # Run YOLO periodically
        if (current_time - last_yolo_time) >= DETECTION_INTERVAL:
            last_yolo_time = current_time
            detected_animals, boxes, best_animal, best_conf = run_yolo_detection(raw_frame)
            
            last_boxes = boxes
            last_detected = detected_animals
            last_best_animal = best_animal
            last_best_confidence = best_conf
            
            if detected_animals:
                # ANIMAL DETECTED -> BUZZER ON
                set_buzzer_state(True)
                
                # Check for capture: immediate on first detection, or every 2 seconds
                should_capture = False
                if not first_animal_detected:
                    should_capture = True
                    first_animal_detected = True
                    last_capture_time = current_time
                elif (current_time - last_capture_time) >= CAPTURE_INTERVAL:
                    should_capture = True
                    last_capture_time = current_time
                    
                if should_capture:
                    # Create annotated capture frame
                    capture_frame = raw_frame.copy()
                    for b in boxes:
                        draw_red_bounding_box(capture_frame, b[0], b[1], b[2], b[3], b[4], b[5])
                    draw_top_status_banner(capture_frame, True, best_animal, best_conf, camera_connected)
                    
                    # Background save
                    threading.Thread(
                        target=save_detection_capture,
                        args=(best_animal, best_conf, capture_frame),
                        daemon=True
                    ).start()
                else:
                    update_detection_status(
                        monitoring=True,
                        connected=True,
                        status=f"ANIMAL DETECTED: {best_animal.upper()}",
                        detected=True,
                        animal=best_animal,
                        confidence=best_conf * 100,
                        buzzer=True
                    )
            else:
                # NO ANIMAL -> BUZZER OFF
                set_buzzer_state(False)
                first_animal_detected = False
                update_detection_status(
                    monitoring=True,
                    connected=True,
                    status="No animal detected",
                    detected=False,
                    animal=None,
                    confidence=0.0,
                    buzzer=False
                )
        
        # Render bounding boxes onto live display frame
        for b in last_boxes:
            draw_red_bounding_box(display_frame, b[0], b[1], b[2], b[3], b[4], b[5])
            
        # Draw top status banner
        draw_top_status_banner(
            display_frame,
            bool(last_detected),
            last_best_animal,
            last_best_confidence,
            camera_connected
        )
        
        # Encode and stream
        success, buffer = cv2.imencode(".jpg", display_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not success:
            continue
            
        frame_bytes = buffer.tobytes()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n\r\n"
            + frame_bytes + b"\r\n"
        )
        
        time.sleep(0.005)

# =============================================================================
# CAMERA CONTROL (START / STOP)
# =============================================================================
def start_camera():
    """Starts the ESP32-CAM stream reader and detection loop."""
    global camera_running, camera_thread, first_animal_detected, last_capture_time
    
    if camera_running:
        return True
    
    print("--------------------------------")
    print("STARTING MONITORING...")
    print("--------------------------------")
    
    first_animal_detected = False
    last_capture_time = 0
    camera_running = True
    
    # CRITICAL: Buzzer must start silent (OFF)
    set_buzzer_state(False, force=True)
    reset_detection_status()
    
    camera_thread = threading.Thread(
        target=mjpeg_stream_reader,
        daemon=True
    )
    camera_thread.start()
    
    time.sleep(0.2)
    return True

def stop_camera():
    """Stops stream reader, detection loop, and immediately turns buzzer OFF."""
    global camera_running, camera_connected, latest_raw_frame, first_animal_detected
    
    print("--------------------------------")
    print("STOPPING MONITORING...")
    print("--------------------------------")
    
    camera_running = False
    camera_connected = False
    first_animal_detected = False
    
    # CRITICAL: Immediately send Buzzer OFF to ESP32
    set_buzzer_state(False, force=True)
    
    with frame_lock:
        latest_raw_frame = None
        
    reset_detection_status()
    print("Monitoring stopped successfully.")
    return True

# =============================================================================
# CLEANUP & SHUTDOWN SAFETY HANDLERS
# =============================================================================
def cleanup():
    """Ensures buzzer is turned OFF and stream stopped on application exit."""
    print()
    print("==========================================")
    print("CLEANUP: Ensuring ESP32 Buzzer is OFF...")
    print("==========================================")
    stop_camera()
    try:
        requests.get(ESP32_BUZZER_OFF_URL, timeout=1.5)
        print("ESP32 Buzzer turned OFF successfully.")
    except Exception:
        pass

atexit.register(cleanup)

def signal_handler(sig, frame):
    cleanup()
    os._exit(0)

try:
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
except Exception:
    pass