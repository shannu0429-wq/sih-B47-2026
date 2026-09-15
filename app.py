from flask import Flask,render_template,request,redirect,url_for,session,Response,jsonify
import mysql.connector
import os
import threading
import requests
import shutil
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
        set_capture_user
    )
    print("--------------------------------")
    print("app1.py imported successfully")
    print("--------------------------------")
except Exception as error:
    print("--------------------------------")
    print("ERROR IMPORTING app1.py")
    print(error)
    print("--------------------------------")
    raise

app=Flask(__name__)

app.secret_key="smart_farm_secret_key_2026"

BASE_DIR=os.path.dirname(os.path.abspath(__file__))

STATIC_DIR=os.path.join(BASE_DIR,"static")

os.makedirs(STATIC_DIR,exist_ok=True)

USER_CAPTURE_DIR=os.path.join(STATIC_DIR,"user_captures")

os.makedirs(USER_CAPTURE_DIR,exist_ok=True)

active_user_id=None

active_user_lock=threading.Lock()

TELEGRAM_BOT_TOKEN=os.environ.get("TELEGRAM_BOT_TOKEN","")
TELEGRAM_CHAT_ID=os.environ.get("TELEGRAM_CHAT_ID","")

DB_HOST="127.0.0.1"
DB_USER="root"
DB_PASSWORD="admin"
DB_NAME="smart_farm"
MAX_NOTIFICATIONS=20

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )



def create_database():
    connection=None
    cursor=None
    try:
        connection=mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cursor=connection.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
        connection.commit()
        print("--------------------------------")
        print("DATABASE READY")
        print("Database:",DB_NAME)
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
    connection=None
    cursor=None
    try:
        connection=get_db_connection()
        cursor=connection.cursor()
        query="""
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
        print("NOTIFICATIONS TABLE ERROR")
        print(error)
        print("--------------------------------")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
            
def get_user_capture_directory(user_id):
    user_folder=os.path.join(USER_CAPTURE_DIR,str(user_id))
    os.makedirs(user_folder,exist_ok=True)
    return user_folder
def create_user_image(source_image,user_id):
    if not source_image:
        return None
    
    try:
        source_image=str(source_image).replace("/",os.sep)
        
        if os.path.isabs(source_image):
            source_path=source_image
        elif source_image.startswith("static"+os.sep):
            source_path=os.path.join(BASE_DIR,source_image)
        else:
            source_path=os.path.join(STATIC_DIR,source_image)
        if not os.path.exists(source_path):
            print("--------------------------------")
            print("SOURCE IMAGE NOT FOUND")
            print(source_path)
            print("--------------------------------")
            return None
        user_directory=get_user_capture_directory(user_id)
        timestamp=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        extension=os.path.splitext(source_path)[1]
        if not extension:
            extension=".jpg"
        animal_name="animal"
        source_filename=os.path.basename(source_path)
        if "_" in source_filename:
            first_part=source_filename.split("_")[0]
            if first_part:
                animal_name=first_part
        filename=f"{animal_name}_{timestamp}{extension}"
        destination_path=os.path.join(user_directory,filename)
        shutil.copy2(source_path,destination_path)
        web_path=f"user_captures/{user_id}/{filename}"
        print("--------------------------------")
        print("USER IMAGE CREATED")
        print("User:",user_id)
        print("Image:",web_path)
        print("--------------------------------")
        return web_path
    except Exception as error:
        print("--------------------------------")
        print("USER IMAGE ERROR")
        print(error)
        print("--------------------------------")
        return None
def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        print("Telegram bot token not configured.")
        return False
    if not TELEGRAM_CHAT_ID:
        print("Telegram chat ID not configured.")
        return False
    try:
        url="https://api.telegram.org/bot"+TELEGRAM_BOT_TOKEN+"/sendMessage"
        response=requests.post(
            url,
            data={
                "chat_id":TELEGRAM_CHAT_ID,
                "text":message
            },
            timeout=10
        )
        if response.ok:
            print("Telegram message sent.")
            return True
        print("Telegram message failed:",response.text)
        return False
    except Exception as error:
        print("Telegram error:",error)
        return False
def send_telegram_photo(image_path,animal,confidence,detection_time):
    if not TELEGRAM_BOT_TOKEN:
        return False
    if not TELEGRAM_CHAT_ID:
        return False
    if not image_path:
        return False
    try:
        image_path=str(image_path).replace("/",os.sep)
        if os.path.isabs(image_path):
            absolute_path=image_path
        elif image_path.startswith("static"+os.sep):
            absolute_path=os.path.join(BASE_DIR,image_path)
        else:
            absolute_path=os.path.join(STATIC_DIR,image_path)
        if not os.path.exists(absolute_path):
            print("Telegram image not found:",absolute_path)
            return False
        url="https://api.telegram.org/bot"+TELEGRAM_BOT_TOKEN+"/sendPhoto"
        caption=(
            "🚨 ANIMAL DETECTED\n\n"
            f"Animal: {str(animal).upper()}\n"
            f"Confidence: {float(confidence):.2f}%\n"
            f"Time: {detection_time}\n\n"
            "Smart Farm Assistant"
        )
        with open(absolute_path,"rb") as image_file:
            response=requests.post(
                url,
                data={
                    "chat_id":TELEGRAM_CHAT_ID,
                    "caption":caption
                },
                files={
                    "photo":image_file
                },
                timeout=20
            )
        if response.ok:
            print("Telegram photo sent.")
            return True
        print("Telegram photo failed:",response.text)
        return False
    except Exception as error:
        print("Telegram photo error:",error)
        return False
def save_detection_to_database(user_id,animal,confidence,image,detected_time):
    connection=None
    cursor=None
    try:
        connection=get_db_connection()
        cursor=connection.cursor()
        query="""
        INSERT INTO notifications
        (user_id,animal,confidence,image,detected_at)
        VALUES (%s,%s,%s,%s,%s)
        """
        cursor.execute(
            query,
            (
                user_id,
                animal,
                float(confidence),
                image,
                detected_time
            )
        )
        connection.commit()
        notification_id=cursor.lastrowid
        print("--------------------------------")
        print("DETECTION SAVED")
        print("ID:",notification_id)
        print("User:",user_id)
        print("Animal:",animal)
        print("Confidence:",f"{float(confidence):.2f}%")
        print("Image:",image)
        print("Time:",detected_time)
        print("--------------------------------")
        return notification_id
    except Exception as error:
        print("--------------------------------")
        print("DATABASE DETECTION ERROR")
        print(error)
        print("--------------------------------")
        return None
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
def detection_database_callback(animal,confidence,image_path,detected_time,event_id=None):
    global active_user_id
    with active_user_lock:
        user_id=active_user_id
    if user_id is None:
        print("--------------------------------")
        print("DETECTION RECEIVED")
        print("NO ACTIVE USER")
        print("--------------------------------")
        return None
    try:
        confidence_value=float(confidence)
        if confidence_value<=1:
            confidence_percentage=confidence_value*100
        else:
            confidence_percentage=confidence_value
    except Exception:
        confidence_percentage=0
    if not detected_time:
        detected_time=datetime.now()
    user_image=create_user_image(image_path,user_id)
    if user_image is None:
        print("Could not create user-specific image.")
        return None
    notification_id=save_detection_to_database(
        user_id=user_id,
        animal=animal,
        confidence=confidence_percentage,
        image=user_image,
        detected_time=detected_time
    )
    if notification_id:
        send_telegram_photo(
            user_image,
            animal,
            confidence_percentage,
            detected_time
        )
    return notification_id
try:
    set_detection_callback(detection_database_callback)
    print("--------------------------------")
    print("Detection callback connected")
    print("--------------------------------")
except Exception as error:
    print("--------------------------------")
    print("CALLBACK CONNECTION ERROR")
    print(error)
    print("--------------------------------")
def get_latest_notifications(user_id):
    connection=None
    cursor=None
    try:
        connection=get_db_connection()
        cursor=connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id,user_id,animal,confidence,image,detected_at
            FROM notifications
            WHERE user_id=%s
            ORDER BY detected_at DESC,id DESC
            LIMIT %s
            """,
            (user_id,MAX_NOTIFICATIONS)
        )
        rows=cursor.fetchall()
        result=[]
        for row in rows:
            detected_at=row["detected_at"]
            if detected_at:
                formatted_time=detected_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                formatted_time=""
            animal=row["animal"] or "Unknown"
            message="Animal detected: "+animal.upper()
            result.append({
                "id":row["id"],
                "user_id":row["user_id"],
                "animal":animal,
                "confidence":float(row["confidence"] or 0),
                "image":row["image"] or "",
                "image_path":row["image"] or "",
                "message":message,
                "detected_at":formatted_time,
                "created_at":formatted_time
            })
        return result
    except Exception as error:
        print("GET NOTIFICATIONS ERROR:",error)
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
@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        connection=None
        cursor=None
        try:
            connection=get_db_connection()
            cursor=connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT *
                FROM users
                WHERE username=%s
                AND password=%s
                """,
                (username,password)
            )
            user=cursor.fetchone()
            if user:
                session.clear()
                session["user_id"]=user["id"]
                session["username"]=user["username"]
                return redirect(url_for("index"))
            return """
            <script>
            alert("Invalid username or password");
            window.location.href="/login";
            </script>
            """
        except Exception as error:
            print("LOGIN ERROR:",error)
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
@app.route("/signup",methods=["GET","POST"])
def signup():
    if request.method=="POST":
        fullname=request.form.get("fullname","").strip()
        email=request.form.get("email","").strip()
        mobile=request.form.get("mobile","").strip()
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        connection=None
        cursor=None
        try:
            connection=get_db_connection()
            cursor=connection.cursor()
            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE username=%s
                OR email=%s
                """,
                (username,email)
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
                (fullname,email,mobile,username,password)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (
                    fullname,
                    email,
                    mobile,
                    username,
                    password
                )
            )
            connection.commit()
            return """
            <script>
            alert("Account created successfully");
            window.location.href="/login";
            </script>
            """
        except Exception as error:
            print("SIGNUP ERROR:",error)
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
    connection=None
    cursor=None
    try:
        connection=get_db_connection()
        cursor=connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM users
            WHERE id=%s
            """,
            (session["user_id"],)
        )
        user=cursor.fetchone()
        if user is None:
            session.clear()
            return redirect(url_for("login"))
        return render_template("profile.html",user=user)
    except Exception as error:
        print("PROFILE ERROR:",error)
        return "Database error",500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
@app.route("/delete-account",methods=["POST"])
def delete_account():
    global active_user_id
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id=session["user_id"]
    with active_user_lock:
        is_active_user=active_user_id==user_id
    if is_active_user:
        try:
            stop_camera()
        except Exception as error:
            print("STOP CAMERA ERROR:",error)
        with active_user_lock:
            active_user_id=None
    connection=None
    cursor=None
    try:
        connection=get_db_connection()
        cursor=connection.cursor()
        cursor.execute(
            """
            DELETE FROM notifications
            WHERE user_id=%s
            """,
            (user_id,)
        )
        cursor.execute(
            """
            DELETE FROM users
            WHERE id=%s
            """,
            (user_id,)
        )
        connection.commit()
        user_directory=os.path.join(USER_CAPTURE_DIR,str(user_id))
        if os.path.exists(user_directory):
            try:
                shutil.rmtree(user_directory)
            except Exception as error:
                print("IMAGE DIRECTORY DELETE ERROR:",error)
        session.clear()
        return """
        <script>
        alert("Account deleted successfully");
        window.location.href="/";
        </script>
        """
    except Exception as error:
        print("DELETE ACCOUNT ERROR:",error)
        return "Could not delete account",500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
@app.route("/logout")
def logout():
    global active_user_id
    if "user_id" in session:
        user_id=session["user_id"]
        with active_user_lock:
            is_active_user=active_user_id==user_id
        if is_active_user:
            try:
                stop_camera()
            except Exception as error:
                print("STOP CAMERA ERROR:",error)
            with active_user_lock:
                active_user_id=None
    session.clear()
    return redirect(url_for("login"))
@app.route("/camera")
def camera_page():
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id=session["user_id"]
    with active_user_lock:
        current_active_user=active_user_id
    camera_owned_by_user=current_active_user==user_id
    recent=get_latest_notifications(user_id)
    return render_template(
        "animal-detection.html",
        notifications=recent,
        camera_owned_by_user=camera_owned_by_user
    )
@app.route("/start_monitoring",methods=["POST"])
def start_monitoring():
    global active_user_id
    if "user_id" not in session:
        return jsonify({
            "success":False,
            "message":"Unauthorized. Please login."
        }),401
    user_id=session["user_id"]
    with active_user_lock:
        if active_user_id is not None and active_user_id!=user_id:
            return jsonify({
                "success":False,
                "message":"Camera is currently being used by another user."
            }),409
    try:
        set_capture_user(user_id)
        print("--------------------------------")
        print("CAPTURE USER SET")
        print("User:",user_id)
        print("--------------------------------")
    except Exception as error:
        print("--------------------------------")
        print("SET CAPTURE USER ERROR")
        print(error)
        print("--------------------------------")
    try:
        success=start_camera()
    except Exception as error:
        print("--------------------------------")
        print("START CAMERA EXCEPTION")
        print(error)
        print("--------------------------------")
        with active_user_lock:
            if active_user_id==user_id:
                active_user_id=None
        return jsonify({
            "success":False,
            "message":"Camera error: "+str(error)
        }),500
    if not success:
        with active_user_lock:
            if active_user_id==user_id:
                active_user_id=None
        print("--------------------------------")
        print("CAMERA START FAILED")
        print("User:",user_id)
        print("--------------------------------")
        return jsonify({
            "success":False,
            "message":"Could not start camera. Check camera connection, CAMERA_INDEX in app1.py, and camera permissions."
        }),500
    with active_user_lock:
        active_user_id=user_id
    print("--------------------------------")
    print("MONITORING STARTED")
    print("Active User:",user_id)
    print("--------------------------------")
    return jsonify({
        "success":True,
        "message":"Monitoring started successfully"
    })
@app.route("/stop_monitoring",methods=["POST"])
def stop_monitoring():
    global active_user_id
    if "user_id" not in session:
        return jsonify({
            "success":False,
            "message":"Unauthorized"
        }),401
    user_id=session["user_id"]
    with active_user_lock:
        if active_user_id!=user_id:
            return jsonify({
                "success":False,
                "message":"You are not the active monitoring user."
            }),403
    try:
        success=stop_camera()
    except Exception as error:
        print("STOP CAMERA ERROR:",error)
        success=False
    with active_user_lock:
        if active_user_id==user_id:
            active_user_id=None
    print("--------------------------------")
    print("MONITORING STOPPED")
    print("User:",user_id)
    print("--------------------------------")
    return jsonify({
        "success":bool(success),
        "message":"Monitoring stopped"
    })
@app.route("/monitoring_status")
def monitoring_status():
    if "user_id" not in session:
        return jsonify({"running":False}),401
    user_id=session["user_id"]
    with active_user_lock:
        owns_camera=active_user_id==user_id
    try:
        camera_running=is_camera_running()
    except Exception:
        camera_running=False
    return jsonify({
        "running":bool(camera_running and owns_camera)
    })
@app.route("/video_feed")
def video_feed():
    if "user_id" not in session:
        return "Unauthorized",401
    user_id=session["user_id"]
    with active_user_lock:
        owns_camera=active_user_id==user_id
    if not owns_camera:
        return "Camera is being used by another user.",403
    try:
        camera_running=is_camera_running()
    except Exception as error:
        print("CAMERA STATUS ERROR:",error)
        camera_running=False
    if not camera_running:
        return "Monitoring is not running.",400
    try:
        return Response(
            generate_frames(),
            mimetype="multipart/x-mixed-replace; boundary=frame"
        )
    except Exception as error:
        print("--------------------------------")
        print("VIDEO FEED ERROR")
        print(error)
        print("--------------------------------")
        return "Camera feed error: "+str(error),500
@app.route("/detection_status")
def detection_status():
    if "user_id" not in session:
        return jsonify({
            "detected":False,
            "message":"Unauthorized"
        }),401
    user_id=session["user_id"]
    with active_user_lock:
        owns_camera=active_user_id==user_id
    if not owns_camera:
        return jsonify({
            "detected":False,
            "animal":"",
            "confidence":0,
            "image":"",
            "time":"",
            "event_id":"",
            "notification_id":None
        })
    try:
        detection=get_detection_status()
    except Exception as error:
        print("DETECTION STATUS ERROR:",error)
        detection={}
    if not detection:
        detection={}
    try:
        confidence=float(detection.get("confidence",0))
    except Exception:
        confidence=0
    if confidence<=1:
        confidence_percentage=confidence*100
    else:
        confidence_percentage=confidence
    return jsonify({
        "detected":bool(detection.get("detected",False)),
        "animal":detection.get("animal",""),
        "confidence":round(confidence_percentage,2),
        "image":detection.get("image",""),
        "time":detection.get("time",""),
        "event_id":detection.get("event_id",""),
        "notification_id":detection.get("notification_id",None)
    })
@app.route("/get_notifications")
def get_notifications():
    if "user_id" not in session:
        return jsonify({
            "success":False,
            "notifications":[]
        }),401
    user_id=session["user_id"]
    notifications_data=get_latest_notifications(user_id)
    return jsonify({
        "success":True,
        "notifications":notifications_data
    })
@app.route("/get_monitoring_history")
def get_monitoring_history():
    if "user_id" not in session:
        return jsonify({
            "success":False,
            "history":[]
        }),401
    user_id=session["user_id"]
    return jsonify({
        "success":True,
        "history":get_latest_notifications(user_id)
    })
@app.route("/notifications")
def notifications():
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id=session["user_id"]
    recent=get_latest_notifications(user_id)
    return render_template(
        "notifications.html",
        notifications=recent
    )
@app.route("/clear_notifications",methods=["POST"])
def clear_notifications():
    if "user_id" not in session:
        return jsonify({
            "success":False,
            "message":"Unauthorized"
        }),401
    user_id=session["user_id"]
    connection=None
    cursor=None
    try:
        connection=get_db_connection()
        cursor=connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT image
            FROM notifications
            WHERE user_id=%s
            """,
            (user_id,)
        )
        image_rows=cursor.fetchall()
        cursor.execute(
            """
            DELETE FROM notifications
            WHERE user_id=%s
            """,
            (user_id,)
        )
        deleted_count=cursor.rowcount
        connection.commit()
        user_directory=os.path.join(USER_CAPTURE_DIR,str(user_id))
        if os.path.exists(user_directory):
            try:
                shutil.rmtree(user_directory)
                print("--------------------------------")
                print("USER HISTORY IMAGES DELETED")
                print("User:",user_id)
                print("--------------------------------")
            except Exception as image_error:
                print("--------------------------------")
                print("IMAGE HISTORY DELETE ERROR")
                print(image_error)
                print("--------------------------------")
        os.makedirs(user_directory,exist_ok=True)
        print("--------------------------------")
        print("NOTIFICATION HISTORY CLEARED")
        print("User:",user_id)
        print("Deleted records:",deleted_count)
        print("--------------------------------")
        return jsonify({
            "success":True,
            "message":"Notification history cleared successfully.",
            "deleted":deleted_count
        })
    except Exception as error:
        print("--------------------------------")
        print("CLEAR NOTIFICATIONS ERROR")
        print(error)
        print("--------------------------------")
        if connection:
            try:
                connection.rollback()
            except Exception:
                pass
        return jsonify({
            "success":False,
            "message":"Could not clear notification history."
        }),500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
@app.route("/capture")
def capture():
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id=session["user_id"]
    with active_user_lock:
        owns_camera=active_user_id==user_id
    if not owns_camera:
        return """
        <script>
        alert("Start monitoring before capturing an image.");
        window.location.href="/camera";
        </script>
        """
    try:
        filename=capture_image()
    except Exception as error:
        print("--------------------------------")
        print("CAPTURE ERROR")
        print(error)
        print("--------------------------------")
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
    recent=get_latest_notifications(user_id)
    return render_template(
        "animal-detection.html",
        captured_image=filename,
        notifications=recent,
        camera_owned_by_user=True
    )
@app.route("/test_telegram")
def test_telegram():
    if "user_id" not in session:
        return jsonify({"success":False}),401
    success=send_telegram_message(
        "🌱 Smart Farm Assistant\n\nTelegram connection is working successfully."
    )
    return jsonify({"success":success})
def initialize_application():
    print()
    print("==========================================")
    print("       SMART FARM ASSISTANT")
    print("==========================================")
    create_database()
    create_notifications_table()
    os.makedirs(STATIC_DIR,exist_ok=True)
    os.makedirs(USER_CAPTURE_DIR,exist_ok=True)
    print("Database:",DB_NAME)
    print("User image directory:",USER_CAPTURE_DIR)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        print("Telegram: Configured")
    else:
        print("Telegram: Not configured")
    print("==========================================")
if __name__=="__main__":
    initialize_application()
    print()
    print("==========================================")
    print("FLASK SERVER STARTING")
    print("==========================================")
    print("Website:")
    print("http://127.0.0.1:5000")
    print()
    print("Camera:")
    print("http://127.0.0.1:5000/camera")
    print()
    print("Notifications:")
    print("http://127.0.0.1:5000/notifications")
    print()
    print("Notifications API:")
    print("http://127.0.0.1:5000/get_notifications")
    print()
    print("Clear History API:")
    print("POST /clear_notifications")
    print()
    print("==========================================")
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True
    )