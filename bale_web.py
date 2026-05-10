import os
import requests
from flask import Flask, request, jsonify

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    # fallback به خواندن از فایل (اختیاری)
    try:
        with open("token.txt", "r") as f:
            TOKEN = f.read().strip()
    except:
        TOKEN = None

if not TOKEN:
    raise ValueError("BOT_TOKEN not set")

app = Flask(__name__)

def send_message(chat_id, text):
    url = f"https://api.bale.ai/v1/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        print(f"Sent to {chat_id}: {resp.status_code} - {resp.text}")
        return resp.json()
    except Exception as e:
        print(f"Send error: {e}")
        return None

@app.route("/", methods=["POST"])
def webhook():
    try:
        update = request.get_json()
        print(f"Received update: {update}")  # مهم: کل درخواست را لاگ کن
        
        if not update:
            return "OK", 200
        
        # پیام معمولی
        if "message" in update:
            msg = update["message"]
            chat_id = msg["from"]["id"]
            text = msg.get("text", "")
            
            if text == "/start":
                send_message(chat_id, "سلام! ربات کار می‌کند. 🎉")
            else:
                send_message(chat_id, f"شما گفتید: {text}")
        
        # کال‌بک (دکمه) - برای تست ساده
        elif "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["from"]["id"]
            send_message(chat_id, "دکمه فشرده شد (فعلاً پاسخ ساده)")
        
        return "OK", 200
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return "Internal error", 500

@app.route("/", methods=["GET"])
def health():
    return "Bot is alive", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
