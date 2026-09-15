
import cv2
import os
import time
import threading
import serial
from datetime import datetime
from ultralytics import YOLO

MODEL_PATH = "yolo11n.pt"
CAMERA_INDEX = 0
CONFIDENCE = 0.40
NIGHT_MODE = True
DETECTION_INTERVAL = 0.10
AUTO_CAPTURE_INTERVAL = 2
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
CAMERA_BUFFER_SIZE = 1
ARDUINO_PORT = "COM11"
BAUD_RATE = 9600

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
CAPTURE_FOLDER_NAME = "captures"
CAPTURE_FOLDER = os.path.join(STATIC_DIR, CAPTURE_FOLDER_NAME)

os.makedirs(CAPTURE_FOLDER, exist_ok=True)

current_user_id = None
current_user_lock = threading.Lock()

camera = None
camera_lock = threading.Lock()
frame_lock = threading.Lock()

latest_frame = None
camera_running = False
camera_thread = None

animals_was_detected = set()
last_capture_time = 0

detection_lock = threading.Lock()

latest_detection = {
    "detected": False,
    "animal": None,
    "confidence": 0.0,
    "image": "",
    "time": "",
    "event_id": "",
    "notification_id": None
}

detection_callback = None

arduino = None
arduino_lock = threading.Lock()


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

        user_folder = os.path.join(
            CAPTURE_FOLDER,
            f"user_{current_user_id}"
        )

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
        return None

    folder = os.path.join(
        CAPTURE_FOLDER,
        f"user_{user_id}"
    )

    os.makedirs(folder, exist_ok=True)

    return folder


print("--------------------------------")
print("Loading YOLO model...")
print("--------------------------------")

model = YOLO(MODEL_PATH)

print("YOLO model loaded successfully.")


animals = {
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "rat"
}


def set_detection_callback(callback):
    global detection_callback
    detection_callback = callback


def get_detection_status():
    with detection_lock:
        return latest_detection.copy()


def update_detection_status(
    detected=False,
    animal=None,
    confidence=0.0,
    image="",
    event_id="",
    notification_id=None
):
    global latest_detection

    with detection_lock:
        latest_detection = {
            "detected": bool(detected),
            "animal": animal,
            "confidence": float(confidence or 0),
            "image": image or "",
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event_id": event_id or "",
            "notification_id": notification_id
        }


def reset_detection_status():
    update_detection_status(
        detected=False,
        animal=None,
        confidence=0.0,
        image="",
        event_id="",
        notification_id=None
    )


def is_camera_running():
    return camera_running


def open_camera():
    global camera

    if camera is not None and camera.isOpened():
        return True

    print("Opening camera...")

    if os.name == "nt":
        camera = cv2.VideoCapture(
            CAMERA_INDEX,
            cv2.CAP_DSHOW
        )
    else:
        camera = cv2.VideoCapture(
            CAMERA_INDEX
        )

    if not camera.isOpened():
        print("Camera could not be opened.")
        camera = None
        return False

    camera.set(
        cv2.CAP_PROP_FRAME_WIDTH,
        CAMERA_WIDTH
    )

    camera.set(
        cv2.CAP_PROP_FRAME_HEIGHT,
        CAMERA_HEIGHT
    )

    camera.set(
        cv2.CAP_PROP_FPS,
        CAMERA_FPS
    )

    camera.set(
        cv2.CAP_PROP_BUFFERSIZE,
        CAMERA_BUFFER_SIZE
    )

    try:
        camera.set(
            cv2.CAP_PROP_AUTOFOCUS,
            1
        )
    except Exception:
        pass

    print("Camera opened successfully.")

    return True


def improve_night_image(frame):
    if frame is None:
        return frame

    try:
        lab = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2LAB
        )

        l, a, b = cv2.split(lab)

        clahe = cv2.createCLAHE(
            clipLimit=3.0,
            tileGridSize=(8, 8)
        )

        l = clahe.apply(l)

        enhanced = cv2.merge(
            (l, a, b)
        )

        enhanced = cv2.cvtColor(
            enhanced,
            cv2.COLOR_LAB2BGR
        )

        enhanced = cv2.convertScaleAbs(
            enhanced,
            alpha=1.2,
            beta=20
        )

        return enhanced

    except Exception:
        return frame


def connect_arduino():
    global arduino

    with arduino_lock:

        if arduino is not None:

            try:
                if arduino.is_open:
                    return True
            except Exception:
                pass

        try:

            arduino = serial.Serial(
                ARDUINO_PORT,
                BAUD_RATE,
                timeout=1
            )

            time.sleep(2)

            print("--------------------------------")
            print("ARDUINO CONNECTED")
            print("Port:", ARDUINO_PORT)
            print("--------------------------------")

            return True

        except Exception as error:

            print("--------------------------------")
            print("ARDUINO CONNECTION FAILED")
            print("Port:", ARDUINO_PORT)
            print("Error:", error)
            print("--------------------------------")

            arduino = None

            return False


def send_arduino_command(command):
    global arduino

    with arduino_lock:

        if arduino is None:
            return False

        try:

            if arduino.is_open:

                arduino.write(
                    (command + "\n").encode()
                )

                arduino.flush()

                print(
                    "Arduino command sent:",
                    command
                )

                return True

        except Exception as error:

            print(
                "Arduino communication error:",
                error
            )

            try:
                arduino.close()
            except Exception:
                pass

            arduino = None

        return False


def camera_reader():
    global latest_frame
    global camera_running

    print("Camera reader started.")

    while camera_running:

        with camera_lock:

            if (
                camera is None
                or
                not camera.isOpened()
            ):
                time.sleep(0.05)
                continue

            success, frame = camera.read()

        if not success:

            time.sleep(0.01)
            continue

        with frame_lock:
            latest_frame = frame

    print("Camera reader stopped.")


def start_camera():
    global camera_running
    global camera_thread
    global animals_was_detected
    global last_capture_time

    if camera_running:
        return True

    if get_capture_user() is None:

        print(
            "ERROR: No active user selected."
        )

        return False

    if not open_camera():
        return False

    connect_arduino()

    animals_was_detected = set()
    last_capture_time = 0

    reset_detection_status()

    camera_running = True

    camera_thread = threading.Thread(
        target=camera_reader,
        daemon=True
    )

    camera_thread.start()

    time.sleep(0.3)

    print("--------------------------------")
    print("MONITORING STARTED")
    print("User:", get_capture_user())
    print("--------------------------------")

    return True


def get_camera_frame():
    with frame_lock:

        if latest_frame is None:
            return None

        return latest_frame.copy()


def draw_detection(
    frame,
    x1,
    y1,
    x2,
    y2,
    name,
    confidence
):
    cv2.rectangle(
        frame,
        (x1, y1),
        (x2, y2),
        (0, 255, 0),
        3
    )

    percentage = confidence * 100

    label = (
        f"{name.upper()} "
        f"{percentage:.1f}%"
    )

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.65
    thickness = 2

    (
        text_width,
        text_height
    ), baseline = cv2.getTextSize(
        label,
        font,
        font_scale,
        thickness
    )

    label_y = max(
        y1,
        text_height + 10
    )

    cv2.rectangle(
        frame,
        (
            x1,
            label_y - text_height - 10
        ),
        (
            x1 + text_width + 12,
            label_y + baseline
        ),
        (0, 255, 0),
        -1
    )

    cv2.putText(
        frame,
        label,
        (
            x1 + 6,
            label_y - 3
        ),
        font,
        font_scale,
        (0, 0, 0),
        thickness
    )


def detect_animals(frame):

    try:

        if NIGHT_MODE:

            detection_frame = (
                improve_night_image(frame)
            )

        else:

            detection_frame = frame.copy()

        results = model.predict(
            detection_frame,
            conf=CONFIDENCE,
            imgsz=416,
            verbose=False,
            device="cpu"
        )

        currently_detected = set()

        boxes = []

        best_animal = None
        best_confidence = 0.0

        for result in results:

            if result.boxes is None:
                continue

            for box in result.boxes:

                try:

                    class_id = int(
                        box.cls[0]
                    )

                    confidence = float(
                        box.conf[0]
                    )

                    name = model.names[
                        class_id
                    ]

                    if name not in animals:
                        continue

                    currently_detected.add(
                        name
                    )

                    x1, y1, x2, y2 = map(
                        int,
                        box.xyxy[0].tolist()
                    )

                    boxes.append(
                        (
                            x1,
                            y1,
                            x2,
                            y2,
                            name,
                            confidence
                        )
                    )

                    if confidence > best_confidence:

                        best_confidence = (
                            confidence
                        )

                        best_animal = name

                except Exception as error:

                    print(
                        "Detection processing error:",
                        error
                    )

        return (
            detection_frame,
            currently_detected,
            boxes,
            best_animal,
            best_confidence
        )

    except Exception as error:

        print(
            "YOLO ERROR:",
            error
        )

        return (
            frame,
            set(),
            [],
            None,
            0.0
        )


def process_new_animal(
    animal,
    confidence,
    image_path,
    event_id
):
    detection_time = (
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print("--------------------------------")
    print("ANIMAL CAPTURE EVENT")
    print("User:", get_capture_user())
    print("Animal:", animal)
    print(
        "Confidence:",
        f"{confidence * 100:.1f}%"
    )
    print("Image:", image_path)
    print("Time:", detection_time)
    print("--------------------------------")

    update_detection_status(
        detected=True,
        animal=animal,
        confidence=confidence * 100,
        image=image_path,
        event_id=event_id,
        notification_id=None
    )

    if detection_callback is not None:

        try:

            notification_id = (
                detection_callback(
                    animal,
                    confidence,
                    image_path,
                    detection_time,
                    event_id
                )
            )

            update_detection_status(
                detected=True,
                animal=animal,
                confidence=confidence * 100,
                image=image_path,
                event_id=event_id,
                notification_id=notification_id
            )

        except Exception as error:

            print(
                "Detection callback error:",
                error
            )


def save_detected_animal_image(
    animal,
    animal_confidence,
    save_frame
):
    user_folder = (
        get_user_capture_folder()
    )

    if user_folder is None:

        print(
            "No user folder available."
        )

        return

    user_id = get_capture_user()

    timestamp = (
        datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )
    )

    filename = (
        f"{animal}_{timestamp}.jpg"
    )

    filepath = os.path.join(
        user_folder,
        filename
    )

    success = cv2.imwrite(
        filepath,
        save_frame,
        [
            cv2.IMWRITE_JPEG_QUALITY,
            90
        ]
    )

    if not success:

        print(
            "Failed to save image:",
            filepath
        )

        return

    web_path = (
        f"{CAPTURE_FOLDER_NAME}/"
        f"user_{user_id}/"
        f"{filename}"
    )

    event_id = (
        f"{animal}_{timestamp}"
    )

    print("--------------------------------")
    print("IMAGE SAVED")
    print("User:", user_id)
    print("Animal:", animal)
    print(
        "Confidence:",
        f"{animal_confidence * 100:.1f}%"
    )
    print("Image:", web_path)
    print("--------------------------------")

    process_new_animal(
        animal,
        animal_confidence,
        web_path,
        event_id
    )


def generate_frames():
    global animals_was_detected
    global last_capture_time

    if not camera_running:
        return

    last_detection_time = 0

    last_boxes = []

    last_detected = set()

    last_best_animal = None

    last_best_confidence = 0.0

    while camera_running:

        frame = get_camera_frame()

        if frame is None:

            time.sleep(0.01)
            continue

        current_time = time.time()

        if (
            current_time
            - last_detection_time
        ) >= DETECTION_INTERVAL:

            last_detection_time = (
                current_time
            )

            (
                detection_frame,
                currently_detected,
                boxes,
                best_animal,
                best_confidence
            ) = detect_animals(frame)

            last_boxes = boxes

            last_detected = (
                currently_detected
            )

            last_best_animal = (
                best_animal
            )

            last_best_confidence = (
                best_confidence
            )

            new_animals = (
                currently_detected
                -
                animals_was_detected
            )

            if new_animals:

                for animal in sorted(
                    new_animals
                ):

                    send_arduino_command(
                        "A:"
                        +
                        animal.upper()
                    )

                print("--------------------------------")
                print("NEW ANIMAL DETECTED")
                print("User:", get_capture_user())
                print(
                    "Detected:",
                    ", ".join(
                        sorted(new_animals)
                    )
                )
                print("--------------------------------")

                last_capture_time = 0

            if currently_detected:

                if (
                    current_time
                    - last_capture_time
                ) >= AUTO_CAPTURE_INTERVAL:

                    save_frame = (
                        detection_frame.copy()
                    )

                    for box_data in boxes:

                        (
                            x1,
                            y1,
                            x2,
                            y2,
                            name,
                            confidence
                        ) = box_data

                        draw_detection(
                            save_frame,
                            x1,
                            y1,
                            x2,
                            y2,
                            name,
                            confidence
                        )

                    for animal in sorted(
                        currently_detected
                    ):

                        animal_confidence = 0.0

                        for box_data in boxes:

                            (
                                bx1,
                                by1,
                                bx2,
                                by2,
                                bname,
                                bconfidence
                            ) = box_data

                            if (
                                bname == animal
                                and
                                bconfidence
                                > animal_confidence
                            ):

                                animal_confidence = (
                                    bconfidence
                                )

                        if animal_confidence == 0:

                            animal_confidence = (
                                best_confidence
                            )

                        save_detected_animal_image(
                            animal,
                            animal_confidence,
                            save_frame
                        )

                    last_capture_time = (
                        current_time
                    )

            if (
                not currently_detected
                and
                animals_was_detected
            ):

                print("--------------------------------")
                print("ANIMAL GONE")
                print("--------------------------------")

                send_arduino_command(
                    "N"
                )

                reset_detection_status()

                last_capture_time = 0

            animals_was_detected = (
                currently_detected.copy()
            )

        if NIGHT_MODE:

            display_frame = (
                improve_night_image(frame)
            )

        else:

            display_frame = frame.copy()

        for box_data in last_boxes:

            (
                x1,
                y1,
                x2,
                y2,
                name,
                confidence
            ) = box_data

            draw_detection(
                display_frame,
                x1,
                y1,
                x2,
                y2,
                name,
                confidence
            )

        if last_detected:

            detected_text = ", ".join(
                sorted(last_detected)
            )

            status_text = (
                "ANIMAL: "
                +
                detected_text.upper()
            )

            cv2.putText(
                display_frame,
                status_text,
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

        else:

            cv2.putText(
                display_frame,
                "NO ANIMAL DETECTED",
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2
            )

        if NIGHT_MODE:

            cv2.putText(
                display_frame,
                "NIGHT MODE",
                (15, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                2
            )

        with arduino_lock:

            arduino_connected = (
                arduino is not None
                and
                arduino.is_open
            )

        if arduino_connected:

            arduino_text = (
                "ARDUINO: CONNECTED"
            )

            arduino_color = (
                255,
                255,
                255
            )

        else:

            arduino_text = (
                "ARDUINO: NOT CONNECTED"
            )

            arduino_color = (
                0,
                0,
                255
            )

        cv2.putText(
            display_frame,
            arduino_text,
            (15, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            arduino_color,
            2
        )

        success, buffer = cv2.imencode(
            ".jpg",
            display_frame,
            [
                cv2.IMWRITE_JPEG_QUALITY,
                80
            ]
        )

        if not success:
            continue

        frame_bytes = (
            buffer.tobytes()
        )

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: "
            +
            str(
                len(frame_bytes)
            ).encode()
            +
            b"\r\n\r\n"
            +
            frame_bytes
            +
            b"\r\n"
        )

        time.sleep(0.005)


def capture_image():

    if not camera_running:
        return None

    if get_capture_user() is None:
        return None

    frame = get_camera_frame()

    if frame is None:
        return None

    if NIGHT_MODE:

        frame = improve_night_image(
            frame
        )

    user_folder = (
        get_user_capture_folder()
    )

    if user_folder is None:
        return None

    user_id = get_capture_user()

    timestamp = (
        datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )
    )

    filename = (
        f"capture_{timestamp}.jpg"
    )

    filepath = os.path.join(
        user_folder,
        filename
    )

    success = cv2.imwrite(
        filepath,
        frame,
        [
            cv2.IMWRITE_JPEG_QUALITY,
            90
        ]
    )

    if not success:

        print(
            "Manual image save failed."
        )

        return None

    print("--------------------------------")
    print("MANUAL CAPTURE")
    print("User:", user_id)
    print("Image:", filepath)
    print("--------------------------------")

    return (
        f"{CAPTURE_FOLDER_NAME}/"
        f"user_{user_id}/"
        f"{filename}"
    )


def stop_camera():
    global camera_running
    global camera
    global latest_frame
    global animals_was_detected
    global last_capture_time

    print("Stopping camera...")

    camera_running = False

    animals_was_detected = set()

    last_capture_time = 0

    send_arduino_command("N")

    if camera_thread is not None:

        try:

            if (
                camera_thread.is_alive()
                and
                camera_thread
                is not threading.current_thread()
            ):

                camera_thread.join(
                    timeout=1
                )

        except Exception:
            pass

    with camera_lock:

        if camera is not None:

            try:
                camera.release()
            except Exception:
                pass

            camera = None

    with frame_lock:

        latest_frame = None

    reset_detection_status()

    print("Camera stopped.")

    return True


def cleanup():
    global arduino

    print("Cleaning up...")

    stop_camera()

    with arduino_lock:

        if arduino is not None:

            try:

                if arduino.is_open:

                    arduino.write(
                        b"N\n"
                    )

                    arduino.flush()

                    time.sleep(0.2)

                    arduino.close()

            except Exception as error:

                print(
                    "Arduino cleanup error:",
                    error
                )

            finally:

                arduino = None

