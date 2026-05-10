import os
import logging
import sys
from flask import Flask, request, jsonify
import requests

# تنظیم لاگینگ برای دیدن خروجی در Render
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    try:
        with open("token.txt", "r") as f:
            TOKEN = f.read().strip()
    except:
        pass

if not TOKEN:
    raise ValueError("BOT_TOKEN not found")

app = Flask(__name__)

def send_message(chat_id, text):
    url = f"https://api.bale.ai/v1/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        logging.info(f"Send to {chat_id}: {resp.status_code} - {resp.text[:200]}")
        return resp.json()
    except Exception as e:
        logging.error(f"Send error: {e}")
        return None

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = request.get_json(force=True)
        logging.info(f"WEBHOOK RECEIVED: {update}")
        
        if not update:
            return "OK", 200
        
        # پیام متنی
        if "message" in update:
            msg = update["message"]
            chat_id = msg["from"]["id"]
            text = msg.get("text", "")
            logging.info(f"Message from {chat_id}: {text}")
            
            if text == "/start":
                send_message(chat_id, "✅ ربات با موفقیت کار می‌کند!")
            else:
                send_message(chat_id, f"شما نوشتید: {text}")
        
        # دکمه (callback)
        elif "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["from"]["id"]
            logging.info(f"Callback from {chat_id}: {cb.get('data')}")
            send_message(chat_id, "دکمه فشرده شد (فعلاً پاسخ ساده)")
        
        return "OK", 200
    except Exception as e:
        logging.error(f"Webhook exception: {e}", exc_info=True)
        return "Internal error", 500

@app.route("/", methods=["GET"])
def home():
    return "Bale bot is alive", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
