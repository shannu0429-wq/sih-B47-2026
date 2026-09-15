import requests
import os
from datetime import datetime


# =====================================================
# TELEGRAM SETTINGS
# =====================================================

TELEGRAM_BOT_TOKEN = "8855181305:AAFBAYaKjQPhpzHwKy4RVS6HwqPfMFarTRA"

TELEGRAM_CHAT_ID = "6790813576"


# =====================================================
# TELEGRAM API
# =====================================================

TELEGRAM_API_URL = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
)


# =====================================================
# CHECK CONFIGURATION
# =====================================================

def telegram_configured():

    return (
        TELEGRAM_BOT_TOKEN
        and TELEGRAM_CHAT_ID
        and TELEGRAM_BOT_TOKEN != "PUT_YOUR_NEW_BOT_TOKEN_HERE"
    )


# =====================================================
# SEND MESSAGE
# =====================================================

def send_telegram_message(message):

    if not telegram_configured():

        print("Telegram is not configured")

        return False

    try:

        response = requests.post(

            f"{TELEGRAM_API_URL}/sendMessage",

            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },

            timeout=10
        )

        result = response.json()

        if response.ok and result.get("ok"):

            print("Telegram message sent successfully")

            return True

        print(
            "Telegram message failed:",
            result
        )

        return False

    except Exception as error:

        print(
            "Telegram connection error:",
            error
        )

        return False


# =====================================================
# SEND ANIMAL ALERT
# =====================================================

def send_animal_alert(
    animal,
    confidence,
    detection_time=None
):

    if detection_time is None:

        detection_time = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    try:

        confidence = float(confidence)

    except:

        confidence = 0.0

    message = (
        "🚨 ANIMAL DETECTED 🚨\n\n"
        f"🐾 Animal: {animal}\n"
        f"🎯 Confidence: {confidence:.1f}%\n"
        f"🕐 Time: {detection_time}\n\n"
        "🌾 Smart Farm Alert\n"
        "⚠️ Please check your farm immediately."
    )

    return send_telegram_message(message)


# =====================================================
# SEND PHOTO + ALERT
# =====================================================

def send_telegram_photo(
    image_path,
    animal,
    confidence,
    detection_time=None
):

    if not telegram_configured():

        print("Telegram is not configured")

        return False

    if not image_path:

        return send_animal_alert(
            animal,
            confidence,
            detection_time
        )

    if not os.path.exists(image_path):

        print(
            "Image not found:",
            image_path
        )

        return send_animal_alert(
            animal,
            confidence,
            detection_time
        )

    if detection_time is None:

        detection_time = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    try:

        confidence = float(confidence)

    except:

        confidence = 0.0

    caption = (
        "🚨 ANIMAL DETECTED 🚨\n\n"
        f"🐾 Animal: {animal}\n"
        f"🎯 Confidence: {confidence:.1f}%\n"
        f"🕐 Time: {detection_time}\n\n"
        "🌾 Smart Farm Alert\n"
        "⚠️ Please check your farm immediately."
    )

    try:

        with open(
            image_path,
            "rb"
        ) as photo:

            response = requests.post(

                f"{TELEGRAM_API_URL}/sendPhoto",

                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption
                },

                files={
                    "photo": photo
                },

                timeout=20
            )

        result = response.json()

        if response.ok and result.get("ok"):

            print(
                "Telegram photo sent successfully"
            )

            return True

        print(
            "Telegram photo failed:",
            result
        )

        return False

    except Exception as error:

        print(
            "Telegram photo error:",
            error
        )

        return False


# =====================================================
# TEST BOT
# =====================================================

def test_telegram():

    if not telegram_configured():

        print(
            "Telegram configuration is missing"
        )

        return False

    try:

        response = requests.get(

            f"{TELEGRAM_API_URL}/getMe",

            timeout=10
        )

        result = response.json()

        if response.ok and result.get("ok"):

            bot = result["result"]

            print(
                "================================"
            )

            print(
                "Telegram connected successfully"
            )

            print(
                "Bot:",
                bot.get("username")
            )

            print(
                "Chat ID:",
                TELEGRAM_CHAT_ID
            )

            print(
                "================================"
            )

            return True

        print(
            "Telegram connection failed:",
            result
        )

        return False

    except Exception as error:

        print(
            "Telegram connection error:",
            error
        )

        return False


# =====================================================
# TEST
# =====================================================

if __name__ == "__main__":

    test_telegram()

    send_telegram_message(
        "🌾 Smart Farm Telegram connection successful!"
    )