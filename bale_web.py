import os
import sys
import time
import json
import logging
import requests
import re
import math
import tempfile
import shutil
import subprocess
import threading
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from pathlib import Path
import yt_dlp

# ========== تنظیمات مستقیم (Hardcoded) ==========
BOT_TOKEN = "1331646419:g8990tyskTERZDtqi0AnyaV5eIIqiCA6vlI"
ADMIN_IDS = [1246154254]
DATABASE_URL = "postgresql+psycopg://neondb_owner:npg_PdDIhBH93tCQ@ep-bitter-scene-apv1qffc-pooler.c-7.us-east-1.aws.neon.tech/neondb?sslmode=require"
# ================================================

RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
if not RENDER_URL:
    RENDER_URL = "https://your-app-name.onrender.com"

API_BASE = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), unique=True, nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    username = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    is_banned = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "first_name": self.first_name or "",
            "last_name": self.last_name or "",
            "username": self.username or "",
            "phone": self.phone or "",
            "first_seen": self.first_seen.strftime("%Y-%m-%d %H:%M:%S") if self.first_seen else "",
            "last_seen": self.last_seen.strftime("%Y-%m-%d %H:%M:%S") if self.last_seen else "",
        }

with app.app_context():
    db.create_all()

broadcast_state = {}
youtube_state = {}

def send_message(chat_id, text, reply_markup=None):
    url = f"{API_BASE}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"sendMessage error: {e}")

def send_video(chat_id, video_path, caption=""):
    url = f"{API_BASE}/sendVideo"
    with open(video_path, 'rb') as f:
        files = {'video': f}
        data = {'chat_id': chat_id, 'caption': caption}
        try:
            requests.post(url, data=data, files=files, timeout=180)
        except Exception as e:
            print(f"sendVideo error: {e}")

def send_audio(chat_id, audio_path, title, performer="YouTube"):
    url = f"{API_BASE}/sendAudio"
    with open(audio_path, 'rb') as f:
        files = {'audio': f}
        data = {'chat_id': chat_id, 'title': title, 'performer': performer}
        try:
            requests.post(url, data=data, files=files, timeout=180)
        except Exception as e:
            print(f"sendAudio error: {e}")

def get_user(user_id):
    user = User.query.filter_by(user_id=str(user_id)).first()
    if not user:
        user = User(user_id=str(user_id))
        db.session.add(user)
        db.session.commit()
    else:
        user.last_seen = datetime.utcnow()
        db.session.commit()
    return user

def all_users():
    return User.query.all()

def main_menu():
    return {
        "keyboard": [
            [{"text": "📢 اخبار و اطلاعیه‌ها"}],
            [{"text": "📞 ارتباط با پشتیبانی"}],
            [{"text": "ℹ️ درباره ما"}]
        ],
        "resize_keyboard": True
    }

def admin_menu():
    return {
        "inline_keyboard": [
            [{"text": "📊 آمار کاربران", "callback_data": "admin_stats"}],
            [{"text": "👥 ۱۵ کاربر آخر", "callback_data": "admin_latest_users"}],
            [{"text": "🔍 جستجوی پیامها", "callback_data": "admin_search"}],
            [{"text": "📢 ارسال به همه", "callback_data": "admin_broadcast"}],
            [{"text": "🎬 دانلود از یوتیوب", "callback_data": "admin_youtube"}],
            [{"text": "🏠 منوی اصلی", "callback_data": "back_menu"}]
        ]
    }

# ---------- توابع دانلود یوتیوب با تنظیمات جدید (force-ipv4 + extractor_args) ----------
def download_youtube_video(url, output_path):
    ydl_opts = {
        'cookiefile': 'cookies.txt',
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'format': 'best[height<=480][ext=mp4]+bestaudio[ext=mp4]/best[height<=480]',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        'force-ipv4': True,  # جدید: اولویت با IPv4
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],  # شبیه‌سازی کلاینت موبایل و وب
                'skip': ['hls']   # اسکیپ استریم‌های HLS (مشکل‌زا)
            }
        }
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return output_path + ".mp4"
    except Exception as e:
        print(f"download_video error: {e}")
        return None

def download_youtube_mp3(url, output_path):
    ydl_opts = {
        'cookiefile': 'cookies.txt',
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'force-ipv4': True,  # جدید
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'skip': ['hls']
            }
        },
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0',
        }],
        'embedthumbnail': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return output_path + ".mp3"
    except Exception as e:
        print(f"download_mp3 error: {e}")
        return None

def get_video_info(video_path):
    size_bytes = os.path.getsize(video_path)
    size_mb = size_bytes / (1024 * 1024)
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    duration = float(result.stdout.strip())
    return size_mb, duration

def split_video_by_size(video_path, target_part_mb=19):
    size_mb, duration = get_video_info(video_path)
    if size_mb <= target_part_mb:
        return [video_path]
    num_parts = math.ceil(size_mb / target_part_mb)
    segment_duration = (duration / num_parts) * 0.95
    temp_dir = tempfile.mkdtemp()
    base_name = os.path.join(temp_dir, "part_%03d.mp4")
    cmd = ['ffmpeg', '-i', video_path, '-c', 'copy', '-map', '0', '-segment_time', str(segment_duration), '-f', 'segment', '-reset_timestamps', '1', base_name]
    subprocess.run(cmd, capture_output=True, text=True)
    part_files = sorted(Path(temp_dir).glob("part_*.mp4"))
    return [str(p) for p in part_files]

def process_youtube(chat_id, url, media_type):
    send_message(chat_id, f"🎬 در حال آماده‌سازی {'ویدیو' if media_type == 'video' else 'MP3'}...")
    with tempfile.NamedTemporaryFile(suffix=".mp4" if media_type == "video" else ".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    if media_type == "video":
        downloaded = download_youtube_video(url, tmp_path)
        if not downloaded:
            send_message(chat_id, "❌ دانلود ویدیو انجام نشد.")
            return
        parts = split_video_by_size(downloaded)
        if not parts:
            send_message(chat_id, "❌ خطا در تقسیم ویدیو.")
            return
        total = len(parts)
        for idx, part in enumerate(parts, start=1):
            caption = f"بخش {idx} از {total}" if total > 1 else "ویدیو"
            send_video(chat_id, part, caption)
        os.unlink(downloaded)
        for p in parts:
            if p != downloaded and os.path.exists(p):
                os.unlink(p)
        send_message(chat_id, "✅ ویدیو با موفقیت ارسال شد.")
    else:
        downloaded = download_youtube_mp3(url, tmp_path[:-4])
        if not downloaded:
            send_message(chat_id, "❌ دانلود MP3 انجام نشد.")
            return
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'YouTube Audio')
        send_audio(chat_id, downloaded, title)
        os.unlink(downloaded)
        send_message(chat_id, "✅ MP3 با کیفیت بالا ارسال شد.")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data:
        return "OK", 200

    if "message" in data:
        msg = data["message"]
        chat_id = msg["chat"]["id"]
        uid = str(chat_id)
        text = msg.get("text", "")
        user = get_user(chat_id)

        if "from" in msg:
            frm = msg["from"]
            user.first_name = frm.get("first_name", "")
            user.last_name = frm.get("last_name", "")
            user.username = frm.get("username", "")
            if "phone" in frm:
                user.phone = frm.get("phone", "")
            db.session.commit()

        if user.is_banned:
            send_message(chat_id, "⛔ شما توسط ادمین مسدود شده‌اید.")
            return "OK", 200

        if chat_id not in ADMIN_IDS:
            if text == "/start":
                send_message(chat_id, "به ربات خوش آمدید!", reply_markup=main_menu())
            elif text == "📢 اخبار و اطلاعیه‌ها":
                send_message(chat_id, "به زودی...")
            elif text == "📞 ارتباط با پشتیبانی":
                send_message(chat_id, "ایدی پشتیبانی: @support")
            elif text == "ℹ️ درباره ما":
                send_message(chat_id, "ربات نمونه مدیریت کاربران")
            else:
                send_message(chat_id, "از منوی زیر استفاده کنید:", reply_markup=main_menu())
            return "OK", 200

        if text == "/start":
            send_message(chat_id, "پنل مدیریت", reply_markup=admin_menu())
            return "OK", 200

        if uid in broadcast_state:
            if broadcast_state[uid] == "waiting_for_message":
                broadcast_state[uid] = text
                markup = {
                    "inline_keyboard": [
                        [{"text": "✅ بله، ارسال کن", "callback_data": "confirm_broadcast"}],
                        [{"text": "❌ لغو", "callback_data": "cancel_broadcast"}]
                    ]
                }
                send_message(chat_id, f"پیام شما:\n\n{text}\n\nآیا ارسال شود؟", reply_markup=markup)
            return "OK", 200

        if uid in youtube_state and youtube_state[uid] == "waiting_for_link":
            youtube_regex = r'(https?://)?(www\.|m\.)?(youtube\.com|youtu\.be)/\S+'
            if re.search(youtube_regex, text):
                youtube_state[uid] = text
                markup = {
                    "inline_keyboard": [
                        [{"text": "🎵 MP3 (کیفیت بالا)", "callback_data": "youtube_mp3"}],
                        [{"text": "📹 ویدیو (480p)", "callback_data": "youtube_video"}]
                    ]
                }
                send_message(chat_id, "نوع خروجی را انتخاب کنید:", reply_markup=markup)
            else:
                send_message(chat_id, "❌ لینک معتبر یوتیوب ارسال کنید.")
            return "OK", 200

        if text == "/admin":
            send_message(chat_id, "پنل مدیریت", reply_markup=admin_menu())
        else:
            send_message(chat_id, "از منوی ادمین استفاده کنید.", reply_markup=admin_menu())

    elif "callback_query" in data:
        callback = data["callback_query"]
        uid = str(callback["from"]["id"])
        data_cb = callback["data"]
        chat_id = callback["message"]["chat"]["id"]

        if data_cb == "back_menu":
            send_message(chat_id, "منوی اصلی", reply_markup=main_menu())
            return "OK", 200

        if data_cb == "admin_stats":
            total_users = User.query.count()
            banned = User.query.filter_by(is_banned=True).count()
            today = datetime.utcnow().date()
            today_users = User.query.filter(db.func.date(User.last_seen) == today).count()
            stats = f"📊 آمار کاربران:\n👥 کل: {total_users}\n🚫 مسدود: {banned}\n📅 امروز: {today_users}"
            send_message(chat_id, stats)
            return "OK", 200

        if data_cb == "admin_latest_users":
            users = User.query.order_by(User.last_seen.desc()).limit(15).all()
            if not users:
                send_message(chat_id, "کاربری یافت نشد.")
                return "OK", 200
            msg = "👥 ۱۵ کاربر آخر:\n\n"
            for u in users:
                name = f"{u.first_name} {u.last_name}".strip() or "بدون نام"
                msg += f"🆔 {u.user_id} - {name} - {u.last_seen.strftime('%Y-%m-%d %H:%M')}\n"
            send_message(chat_id, msg)
            return "OK", 200

        if data_cb == "admin_broadcast":
            broadcast_state[uid] = "waiting_for_message"
            send_message(chat_id, "لطفاً پیام خود را ارسال کنید (متن).")
            return "OK", 200

        if data_cb == "confirm_broadcast":
            if uid in broadcast_state and broadcast_state[uid] != "waiting_for_message":
                msg_text = broadcast_state[uid]
                users = all_users()
                success = 0
                for user in users:
                    try:
                        send_message(int(user.user_id), msg_text)
                        success += 1
                    except:
                        pass
                send_message(chat_id, f"✅ پیام به {success} از {len(users)} کاربر ارسال شد.")
                del broadcast_state[uid]
            else:
                send_message(chat_id, "هیچ پیامی برای ارسال وجود ندارد.")
            return "OK", 200

        if data_cb == "cancel_broadcast":
            if uid in broadcast_state:
                del broadcast_state[uid]
            send_message(chat_id, "ارسال همگانی لغو شد.")
            return "OK", 200

        if data_cb == "admin_youtube":
            youtube_state[uid] = "waiting_for_link"
            send_message(chat_id, "لطفاً لینک ویدیو یوتیوب را ارسال کنید.")
            return "OK", 200

        if data_cb == "youtube_mp3" or data_cb == "youtube_video":
            if uid not in youtube_state or not isinstance(youtube_state[uid], str) or not youtube_state[uid].startswith("http"):
                send_message(chat_id, "❌ لینکی یافت نشد. از منوی اصلی دوباره اقدام کنید.")
                return "OK", 200
            url = youtube_state[uid]
            media_type = "mp3" if data_cb == "youtube_mp3" else "video"
            del youtube_state[uid]
            threading.Thread(target=process_youtube, args=(chat_id, url, media_type)).start()
            send_message(chat_id, "✅ دانلود آغاز شد. لطفاً صبر کنید...")
            return "OK", 200

    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "ربات فعال است."

def set_webhook():
    webhook_url = f"{RENDER_URL}/webhook"
    url = f"{API_BASE}/setWebhook"
    try:
        resp = requests.post(url, json={"url": webhook_url})
        print("setWebhook response:", resp.json())
    except Exception as e:
        print(f"setWebhook error: {e}")

if __name__ == "__main__":
    # بررسی وجود ffmpeg
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("⚠️ ffmpeg یا ffprobe نصب نیست. لطفاً Dockerfile را بررسی کنید.")
        sys.exit(1)
    # بررسی وجود فایل کوکی (اختیاری)
    if not os.path.exists("cookies.txt"):
        print("⚠️ فایل cookies.txt یافت نشد. ممکن است دانلود با خطا مواجه شود.")
    set_webhook()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
