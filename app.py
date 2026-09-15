from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify
import mysql.connector
import os
import threading
import requests
import shutil
import atexit
import signal
from datetime import datetime

try:
    from app1 import (
        generate_frames,
        capture_image,
        start_camera,
        stop_camera,
        get_detection_status,
        is_camera_running,
        set_detection_callback,
        set_capture_user,
        set_esp32_ip,
        test_buzzer as app1_test_buzzer,
        buzzer_on as app1_buzzer_on,
        buzzer_off as app1_buzzer_off,
        check_esp32_status,
        cleanup as app1_cleanup,
        ESP32_IP,
        ESP32_STREAM_URL,
        ESP32_STATUS_URL,
        ESP32_BUZZER_ON_URL,
        ESP32_BUZZER_OFF_URL,
        ESP32_BUZZER_TEST_URL
    )
    print("--------------------------------")
    print("app1.py imported successfully")
    print(f"ESP32 Target: {ESP32_IP}")
    print(f"ESP32 Stream: {ESP32_STREAM_URL}")
    print("--------------------------------")
except Exception as error:
    print("--------------------------------")
    print("ERROR IMPORTING app1.py")
    print(error)
    print("--------------------------------")
    raise

app = Flask(__name__)
app.secret_key = "smart_farm_secret_key_2026"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

USER_CAPTURE_DIR = os.path.join(STATIC_DIR, "user_captures")
os.makedirs(USER_CAPTURE_DIR, exist_ok=True)

active_user_id = None
active_user_lock = threading.Lock()

# Telegram Settings
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8855181305:AAFBAYaKjQPhpzHwKy4RVS6HwqPfMFarTRA")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "6790813576")

# Database Configuration
DB_HOST = "127.0.0.1"
DB_USER = "root"
DB_PASSWORD = "admin"
DB_NAME = "smart_farm"
MAX_NOTIFICATIONS = 20

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

def create_database():
    connection = None
    cursor = None
    try:
        connection = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cursor = connection.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
        connection.commit()
        print("--------------------------------")
        print("DATABASE READY")
        print("Database:", DB_NAME)
        print("--------------------------------")
    except Exception as error:
        print("--------------------------------")
        print("DATABASE CREATION ERROR")
        print(error)
        print("--------------------------------")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def create_notifications_table():
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        query = """
        CREATE TABLE IF NOT EXISTS notifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            animal VARCHAR(100) NOT NULL,
            confidence DECIMAL(5,2) NOT NULL,
            image VARCHAR(500),
            detected_at DATETIME NOT NULL,
            INDEX idx_user_id (user_id),
            INDEX idx_detected_at (detected_at)
        )
        """
        cursor.execute(query)
        connection.commit()
        print("--------------------------------")
        print("NOTIFICATIONS TABLE READY")
        print("--------------------------------")
    except Exception as error:
        print("--------------------------------")
        print("NOTIFICATIONS TABLE ERROR:", error)
        print("--------------------------------")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def get_user_capture_directory(user_id):
    user_folder = os.path.join(USER_CAPTURE_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def create_user_image(source_image, user_id):
    if not source_image:
        return None
    try:
        source_image = str(source_image).replace("/", os.sep)
        if os.path.isabs(source_image):
            source_path = source_image
        elif source_image.startswith("static" + os.sep):
            source_path = os.path.join(BASE_DIR, source_image)
        else:
            source_path = os.path.join(STATIC_DIR, source_image)

        if not os.path.exists(source_path):
            return None

        user_directory = get_user_capture_directory(user_id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        extension = os.path.splitext(source_path)[1] or ".jpg"
        
        animal_name = "animal"
        source_filename = os.path.basename(source_path)
        if "_" in source_filename:
            first_part = source_filename.split("_")[0]
            if first_part:
                animal_name = first_part

        filename = f"{animal_name}_{timestamp}{extension}"
        destination_path = os.path.join(user_directory, filename)
        shutil.copy2(source_path, destination_path)
        return f"user_captures/{user_id}/{filename}"
    except Exception as error:
        print("USER IMAGE ERROR:", error)
        return None

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10
        )
        return response.ok
    except Exception as error:
        print("Telegram error:", error)
        return False

def send_telegram_photo(image_path, animal, confidence, detection_time):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not image_path:
        return False
    try:
        image_path = str(image_path).replace("/", os.sep)
        if os.path.isabs(image_path):
            absolute_path = image_path
        elif image_path.startswith("static" + os.sep):
            absolute_path = os.path.join(BASE_DIR, image_path)
        else:
            absolute_path = os.path.join(STATIC_DIR, image_path)

        if not os.path.exists(absolute_path):
            return False

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        caption = (
            "🚨 ANIMAL DETECTED\n\n"
            f"Animal: {str(animal).upper()}\n"
            f"Confidence: {float(confidence):.2f}%\n"
            f"Time: {detection_time}\n\n"
            "Smart Farm Assistant"
        )
        with open(absolute_path, "rb") as image_file:
            response = requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                files={"photo": image_file},
                timeout=20
            )
        return response.ok
    except Exception as error:
        print("Telegram photo error:", error)
        return False

def save_detection_to_database(user_id, animal, confidence, image, detected_time):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        query = """
        INSERT INTO notifications
        (user_id, animal, confidence, image, detected_at)
        VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(
            query,
            (user_id, animal, float(confidence), image, detected_time)
        )
        connection.commit()
        notification_id = cursor.lastrowid
        return notification_id
    except Exception as error:
        print("DATABASE DETECTION ERROR:", error)
        return None
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def detection_database_callback(animal, confidence, image_path, detected_time, event_id=None):
    global active_user_id
    with active_user_lock:
        user_id = active_user_id

    if user_id is None:
        return None

    try:
        confidence_value = float(confidence)
        if confidence_value <= 1.0:
            confidence_percentage = confidence_value * 100.0
        else:
            confidence_percentage = confidence_value
    except Exception:
        confidence_percentage = 0.0

    if not detected_time:
        detected_time = datetime.now()

    user_image = create_user_image(image_path, user_id)
    if user_image is None:
        user_image = image_path

    notification_id = save_detection_to_database(
        user_id=user_id,
        animal=animal,
        confidence=confidence_percentage,
        image=user_image,
        detected_time=detected_time
    )

    if notification_id:
        threading.Thread(
            target=send_telegram_photo,
            args=(user_image, animal, confidence_percentage, detected_time),
            daemon=True
        ).start()

    return notification_id

try:
    set_detection_callback(detection_database_callback)
    print("--------------------------------")
    print("Detection callback connected")
    print("--------------------------------")
except Exception as error:
    print("CALLBACK CONNECTION ERROR:", error)

def get_latest_notifications(user_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, user_id, animal, confidence, image, detected_at
            FROM notifications
            WHERE user_id=%s
            ORDER BY detected_at DESC, id DESC
            LIMIT %s
            """,
            (user_id, MAX_NOTIFICATIONS)
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            detected_at = row["detected_at"]
            formatted_time = detected_at.strftime("%Y-%m-%d %H:%M:%S") if detected_at else ""
            animal = row["animal"] or "Unknown"
            message = f"Animal detected: {animal.upper()}"
            result.append({
                "id": row["id"],
                "user_id": row["user_id"],
                "animal": animal,
                "confidence": float(row["confidence"] or 0),
                "image": row["image"] or "",
                "image_path": row["image"] or "",
                "message": message,
                "detected_at": formatted_time,
                "created_at": formatted_time
            })
        return result
    except Exception as error:
        return []
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/index/telugu.html")
def telugu():
    return render_template("telugu.html")

@app.route("/index/hindi.html")
def hindi():
    return render_template("hindi.html")

@app.route("/index/tamil.html")
def tamil():
    return render_template("tamil.html")

@app.route("/index/kannada.html")
def kannada():
    return render_template("kannada.html")

@app.route("/index/marati.html")
def marathi():
    return render_template("marati.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM users
                WHERE username=%s
                AND password=%s
                """,
                (username, password)
            )
            user = cursor.fetchone()
            if user:
                session.clear()
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                return redirect(url_for("index"))
            return """
            <script>
            alert("Invalid username or password");
            window.location.href="/login";
            </script>
            """
        except Exception as error:
            print("LOGIN ERROR:", error)
            return """
            <script>
            alert("Database connection error");
            window.location.href="/login";
            </script>
            """
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip()
        mobile = request.form.get("mobile", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        connection = None
        cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE username=%s
                OR email=%s
                """,
                (username, email)
            )
            if cursor.fetchone():
                return """
                <script>
                alert("Username or email already exists");
                window.location.href="/signup";
                </script>
                """
            cursor.execute(
                """
                INSERT INTO users
                (fullname, email, mobile, username, password)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (fullname, email, mobile, username, password)
            )
            connection.commit()
            return """
            <script>
            alert("Account created successfully");
            window.location.href="/login";
            </script>
            """
        except Exception as error:
            print("SIGNUP ERROR:", error)
            return """
            <script>
            alert("Could not create account");
            window.location.href="/signup";
            </script>
            """
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
    return render_template("signup.html")

@app.route("/index")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("index.html")

@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM users
            WHERE id=%s
            """,
            (session["user_id"],)
        )
        user = cursor.fetchone()
        if user is None:
            session.clear()
            return redirect(url_for("login"))
        return render_template("profile.html", user=user)
    except Exception as error:
        print("PROFILE ERROR:", error)
        return "Database error", 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route("/delete-account", methods=["POST"])
def delete_account():
    global active_user_id
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id = session["user_id"]
    with active_user_lock:
        is_active_user = active_user_id == user_id
    if is_active_user:
        try:
            stop_camera()
        except Exception as error:
            print("STOP CAMERA ERROR:", error)
        with active_user_lock:
            active_user_id = None
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("DELETE FROM notifications WHERE user_id=%s", (user_id,))
        cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
        connection.commit()
        user_directory = os.path.join(USER_CAPTURE_DIR, str(user_id))
        if os.path.exists(user_directory):
            try:
                shutil.rmtree(user_directory)
            except Exception:
                pass
        session.clear()
        return """
        <script>
        alert("Account deleted successfully");
        window.location.href="/";
        </script>
        """
    except Exception as error:
        print("DELETE ACCOUNT ERROR:", error)
        return "Could not delete account", 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route("/logout")
def logout():
    global active_user_id
    if "user_id" in session:
        user_id = session["user_id"]
        with active_user_lock:
            is_active_user = active_user_id == user_id
        if is_active_user:
            try:
                stop_camera()
            except Exception as error:
                print("STOP CAMERA ERROR:", error)
            with active_user_lock:
                active_user_id = None
    session.clear()
    return redirect(url_for("login"))

@app.route("/camera")
def camera_page():
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id = session["user_id"]
    with active_user_lock:
        current_active_user = active_user_id
    camera_owned_by_user = current_active_user == user_id
    recent = get_latest_notifications(user_id)
    return render_template(
        "animal-detection.html",
        notifications=recent,
        camera_owned_by_user=camera_owned_by_user,
        esp32_ip=ESP32_IP
    )

@app.route("/start_monitoring", methods=["POST"])
def start_monitoring():
    global active_user_id
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "message": "Unauthorized. Please login."
        }), 401
    
    user_id = session["user_id"]
    with active_user_lock:
        if active_user_id is not None and active_user_id != user_id:
            return jsonify({
                "success": False,
                "message": "Camera is currently being used by another user."
            }), 409
    
    try:
        set_capture_user(user_id)
    except Exception as error:
        print("SET CAPTURE USER ERROR:", error)
    
    if is_camera_running():
        with active_user_lock:
            active_user_id = user_id
        return jsonify({
            "success": True,
            "message": "Monitoring is already active."
        })
    
    try:
        success = start_camera()
    except Exception as error:
        print("START CAMERA EXCEPTION:", error)
        with active_user_lock:
            if active_user_id == user_id:
                active_user_id = None
        return jsonify({
            "success": False,
            "message": f"Camera error: {error}"
        }), 500
    
    if not success:
        with active_user_lock:
            if active_user_id == user_id:
                active_user_id = None
        return jsonify({
            "success": False,
            "message": "Could not connect to ESP32-CAM stream. Check if ESP32 is powered and connected to WiFi."
        }), 500
    
    with active_user_lock:
        active_user_id = user_id
        
    print("--------------------------------")
    print("MONITORING STARTED SUCCESSFULLY")
    print("Active User:", user_id)
    print("--------------------------------")
    return jsonify({
        "success": True,
        "message": "Monitoring started successfully"
    })

@app.route("/stop_monitoring", methods=["POST"])
def stop_monitoring():
    global active_user_id
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401
    
    user_id = session["user_id"]
    with active_user_lock:
        if active_user_id != user_id and active_user_id is not None:
            return jsonify({
                "success": False,
                "message": "You are not the active monitoring user."
            }), 403
    
    try:
        success = stop_camera()
    except Exception as error:
        print("STOP CAMERA ERROR:", error)
        success = False
        
    with active_user_lock:
        if active_user_id == user_id:
            active_user_id = None
            
    print("--------------------------------")
    print("MONITORING STOPPED")
    print("User:", user_id)
    print("--------------------------------")
    return jsonify({
        "success": bool(success),
        "message": "Monitoring stopped"
    })

@app.route("/monitoring_status")
def monitoring_status():
    if "user_id" not in session:
        return jsonify({"running": False}), 401
    user_id = session["user_id"]
    with active_user_lock:
        owns_camera = active_user_id == user_id
    try:
        camera_running = is_camera_running()
    except Exception:
        camera_running = False
    return jsonify({
        "running": bool(camera_running and owns_camera)
    })

@app.route("/video_feed")
def video_feed():
    if "user_id" not in session:
        return "Unauthorized", 401
    user_id = session["user_id"]
    with active_user_lock:
        owns_camera = active_user_id == user_id
    if not owns_camera:
        return "Camera is being used by another user.", 403
    
    try:
        camera_running = is_camera_running()
    except Exception:
        camera_running = False
        
    if not camera_running:
        return "Monitoring is not running.", 400
        
    try:
        return Response(
            generate_frames(),
            mimetype="multipart/x-mixed-replace; boundary=frame"
        )
    except Exception as error:
        print("VIDEO FEED ERROR:", error)
        return f"Camera feed error: {error}", 500

@app.route("/detection_status")
def detection_status():
    if "user_id" not in session:
        return jsonify({
            "monitoring": False,
            "camera_connected": False,
            "detected": False,
            "status": "Unauthorized"
        }), 401
        
    user_id = session["user_id"]
    with active_user_lock:
        owns_camera = active_user_id == user_id
        
    if not owns_camera:
        return jsonify({
            "monitoring": False,
            "camera_connected": False,
            "status": "Not active user",
            "detected": False,
            "animal": None,
            "confidence": 0.0,
            "buzzer": False,
            "image": "",
            "time": "",
            "event_id": "",
            "notification_id": None
        })
        
    try:
        detection = get_detection_status()
    except Exception as error:
        print("DETECTION STATUS ERROR:", error)
        detection = {}
        
    return jsonify(detection)

@app.route("/get_notifications")
def get_notifications():
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "notifications": []
        }), 401
    user_id = session["user_id"]
    notifications_data = get_latest_notifications(user_id)
    return jsonify({
        "success": True,
        "notifications": notifications_data
    })

@app.route("/get_monitoring_history")
def get_monitoring_history():
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "history": []
        }), 401
    user_id = session["user_id"]
    return jsonify({
        "success": True,
        "history": get_latest_notifications(user_id)
    })

@app.route("/notifications")
def notifications():
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id = session["user_id"]
    recent = get_latest_notifications(user_id)
    return render_template(
        "notifications.html",
        notifications=recent
    )

@app.route("/clear_notifications", methods=["POST"])
def clear_notifications():
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401
    user_id = session["user_id"]
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("DELETE FROM notifications WHERE user_id=%s", (user_id,))
        deleted_count = cursor.rowcount
        connection.commit()
        user_directory = os.path.join(USER_CAPTURE_DIR, str(user_id))
        if os.path.exists(user_directory):
            try:
                shutil.rmtree(user_directory)
            except Exception:
                pass
        os.makedirs(user_directory, exist_ok=True)
        return jsonify({
            "success": True,
            "message": "Notification history cleared successfully.",
            "deleted": deleted_count
        })
    except Exception as error:
        print("CLEAR NOTIFICATIONS ERROR:", error)
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        return jsonify({
            "success": False,
            "message": "Could not clear notification history."
        }), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route("/capture")
def capture():
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id = session["user_id"]
    with active_user_lock:
        owns_camera = active_user_id == user_id
    if not owns_camera:
        return """
        <script>
        alert("Start monitoring before capturing an image.");
        window.location.href="/camera";
        </script>
        """
    try:
        filename = capture_image()
    except Exception as error:
        print("CAPTURE ERROR:", error)
        return """
        <script>
        alert("Camera capture failed.");
        window.location.href="/camera";
        </script>
        """
    if filename is None:
        return """
        <script>
        alert("Could not capture image.");
        window.location.href="/camera";
        </script>
        """
    recent = get_latest_notifications(user_id)
    return render_template(
        "animal-detection.html",
        captured_image=filename,
        notifications=recent,
        camera_owned_by_user=True,
        esp32_ip=ESP32_IP
    )


@app.route("/test_buzzer", methods=["GET", "POST"])
def test_buzzer():
    success = app1_test_buzzer()
    return jsonify({
        "success": bool(success),
        "message": "Buzzer test sent to ESP32" if success else "ESP32 Buzzer test failed"
    })

@app.route("/buzzer_on", methods=["GET", "POST"])
def buzzer_on():
    success = app1_buzzer_on()
    return jsonify({
        "success": bool(success),
        "message": "Manual buzzer ON command sent" if success else "ESP32 Buzzer ON failed"
    })

@app.route("/buzzer_off", methods=["GET", "POST"])
def buzzer_off():
    success = app1_buzzer_off()
    return jsonify({
        "success": bool(success),
        "message": "Manual buzzer OFF command sent" if success else "ESP32 Buzzer OFF failed"
    })

@app.route("/esp32_test", methods=["GET", "POST"])
def esp32_test():
    result = check_esp32_status()
    return jsonify(result)

@app.route("/test_telegram")
def test_telegram():
    if "user_id" not in session:
        return jsonify({"success": False}), 401
    success = send_telegram_message(
        "🌱 Smart Farm Assistant\n\nTelegram connection is working successfully."
    )
@app.route("/set_esp32_ip", methods=["POST"])
def set_esp32_ip_route():
    data = request.get_json() or {}
    new_ip = data.get("ip", "").strip()
    if not new_ip:
        return jsonify({"success": False, "message": "IP address is required"}), 400
    updated_ip = set_esp32_ip(new_ip)
    return jsonify({
        "success": True,
        "ip": updated_ip,
        "message": f"ESP32 target IP updated to {updated_ip}"
    })

def initialize_application():
    print()
    print("==========================================")
    print("       SMART FARM ASSISTANT - ESP32       ")
    print("==========================================")
    create_database()
    create_notifications_table()
    os.makedirs(STATIC_DIR, exist_ok=True)
    os.makedirs(USER_CAPTURE_DIR, exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "captures"), exist_ok=True)
    print("Database:", DB_NAME)
    print("User image directory:", USER_CAPTURE_DIR)
    print(f"ESP32-CAM Control: {ESP32_STATUS_URL}")
    print(f"ESP32-CAM Stream:  {ESP32_STREAM_URL}")
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        print("Telegram: Configured")
    else:
        print("Telegram: Not configured")
    print("==========================================")


atexit.register(app1_cleanup)

if __name__ == "__main__":
    initialize_application()
    print()
    print("==========================================")
    print("FLASK SERVER STARTING")
    print("==========================================")
    print("Website:         http://127.0.0.1:5000")
    print("Camera:          http://127.0.0.1:5000/camera")
    print("Notifications:   http://127.0.0.1:5000/notifications")
    print("==========================================")
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True
    )