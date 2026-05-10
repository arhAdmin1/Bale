import os
import json
import logging
from flask import Flask, request, jsonify
import requests

# ----- تنظیمات پایه -----
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    try:
        with open("token.txt", "r") as f:
            TOKEN = f.read().strip()
    except:
        pass

if not TOKEN:
    raise ValueError("BOT_TOKEN not set")

ADMIN_IDS = {1246154254}  # آیدی عددی خودتان
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# ----- تابع ارسال پیام استاندارد (مشابه curl) -----
def send_message(chat_id, text):
    url = f"https://api.bale.ai/bot{TOKEN}/sendMessage"
    headers = {'Content-Type': 'application/json'}
    payload = json.dumps({"chat_id": chat_id, "text": text})
    try:
        response = requests.post(url, headers=headers, data=payload)
        logging.info(f"send_message to {chat_id}: {response.status_code} - {response.text}")
        return response.json()
    except Exception as e:
        logging.error(f"send_message error: {e}")
        return None

# ----- Endpoint وب‌هوک (فقط برای دریافت و پاسخ ساده) -----
@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    logging.info(f"Webhook received: {update}")
    if update and "message" in update:
        chat_id = update["message"]["from"]["id"]
        text = update["message"].get("text", "")
        if text == "/start":
            send_message(chat_id, "ربات با موفقیت کار می‌کند!")
        else:
            send_message(chat_id, f"شما نوشتید: {text}")
    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "Bale bot is alive", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
