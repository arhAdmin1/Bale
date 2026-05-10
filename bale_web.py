import os
import sqlite3
import time
import json
import logging
from datetime import datetime
from typing import Dict, Set, Optional
from flask import Flask, request, jsonify
import requests

# ========== تنظیمات اولیه ==========
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    try:
        with open("token.txt", "r") as f:
            TOKEN = f.read().strip()
    except:
        pass

if not TOKEN:
    raise ValueError("BOT_TOKEN not found")

# آیدی ادمین (آیدی خودتان را اینجا وارد کنید)
ADMIN_IDS = {1246154254}  # 🔁 آیدی خودتان را جایگزین کنید

# ========== دیتابیس ==========
def get_db():
    return sqlite3.connect("bot.db", check_same_thread=False)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        is_admin INTEGER,
        last_seen INTEGER
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER,
        receiver_id INTEGER,
        msg_type TEXT,
        content TEXT,
        ts INTEGER
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS blocked_users (
        owner_id INTEGER,
        blocked_id INTEGER,
        PRIMARY KEY (owner_id, blocked_id)
    )""")
    conn.commit()
    conn.close()

init_db()

def now_ts():
    return int(time.time())

def save_user(user_id, username="", full_name=""):
    conn = get_db()
    cur = conn.cursor()
    is_admin = 1 if user_id in ADMIN_IDS else 0
    cur.execute("""INSERT OR REPLACE INTO users
        (user_id, username, full_name, is_admin, last_seen)
        VALUES (?,?,?,?,?)""",
        (user_id, username, full_name, is_admin, now_ts()))
    conn.commit()
    conn.close()

def save_message(sender, receiver, msg_type, content=""):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO messages (sender_id, receiver_id, msg_type, content, ts) VALUES (?,?,?,?,?)",
                (sender, receiver, msg_type, content, now_ts()))
    conn.commit()
    conn.close()

def is_blocked(owner, user):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM blocked_users WHERE owner_id=? AND blocked_id=?", (owner, user))
    res = cur.fetchone() is not None
    conn.close()
    return res

def block_user(owner, user):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO blocked_users VALUES (?,?)", (owner, user))
    conn.commit()
    conn.close()

def get_last_owner(sender_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT receiver_id FROM messages WHERE sender_id=? AND msg_type='forward' ORDER BY ts DESC LIMIT 1", (sender_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def get_all_users():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE is_admin=0")
    users = [r[0] for r in cur.fetchall()]
    conn.close()
    return users

def get_user_messages(uid, limit=30):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT sender_id, receiver_id, msg_type, content, ts FROM messages WHERE sender_id=? OR receiver_id=? ORDER BY ts DESC LIMIT ?",
                (uid, uid, limit))
    rows = cur.fetchall()
    conn.close()
    return rows

# ========== توابع ارسال به بله (با آدرس صحیح tapi.bale.ir) ==========
def send_message(chat_id, text, reply_markup=None):
    url = f"https://tapi.bale.ir/bot{TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        response = requests.post(url, json=data, timeout=10)
        logging.info(f"send_message to {chat_id}: {response.status_code} - {response.text[:200]}")
        return response.json()
    except Exception as e:
        logging.error(f"send_message error: {e}")
        return None

def answer_callback(callback_id, text=""):
    url = f"https://tapi.bale.ir/bot{TOKEN}/answerCallbackQuery"
    try:
        requests.post(url, json={"callback_query_id": callback_id, "text": text}, timeout=5)
    except Exception as e:
        logging.error(f"answer_callback error: {e}")

# ========== کیبوردها ==========
def main_menu():
    return {"inline_keyboard": [
        [{"text": "📎 دریافت لینک اختصاصی", "callback_data": "get_link"}],
        [{"text": "✉️ ارسال پیام مستقیم", "callback_data": "send_direct"}]
    ]}

def admin_menu():
    return {"inline_keyboard": [
        [{"text": "👥 آمار کاربران", "callback_data": "admin_stats"}],
        [{"text": "🆕 ۱۵ کاربر آخر", "callback_data": "admin_latest_users"}],
        [{"text": "🔍 جستجوی پیام‌ها", "callback_data": "admin_search"}],
        [{"text": "📢 ارسال به همه", "callback_data": "admin_broadcast"}],
        [{"text": "🔙 منوی اصلی", "callback_data": "back_menu"}]
    ]}

def after_send_menu(mode, target_id):
    return {"inline_keyboard": [
        [{"text": "✉️ ارسال دوباره", "callback_data": f"send_again|{mode}|{target_id}"}],
        [{"text": "🔙 منوی اصلی", "callback_data": "back_menu"}]
    ]}

def reply_block_menu(user_id):
    return {"inline_keyboard": [
        [{"text": "✉️ پاسخ", "callback_data": f"reply_{user_id}"},
         {"text": "🚫 بلاک", "callback_data": f"block_{user_id}"}]
    ]}

# ========== وضعیت‌های موقت ==========
user_links: Dict[int, int] = {}
reply_state: Dict[int, int] = {}
send_direct_state: Set[int] = set()
admin_search_state: Set[int] = set()
admin_broadcast_state: Set[int] = set()
last_owner_cache: Dict[int, int] = {}

# ========== برنامه اصلی Flask ==========
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = request.get_json()
        logging.info(f"Webhook received: {update}")
        if not update:
            return "OK", 200

        # پردازش Callback Query
        if "callback_query" in update:
            cb = update["callback_query"]
            user_id = cb["from"]["id"]
            username = cb["from"].get("username", "")
            full_name = cb["from"].get("first_name", "")
            data = cb["data"]
            cid = cb["id"]

            save_user(user_id, username, full_name)
            answer_callback(cid)

            # منوی اصلی
            if data == "get_link":
                bot_user = "Na8henasBot"  # 🔁 یوزرنیم ربات خود را وارد کنید
                link = f"https://ble.ir/{bot_user}?start={user_id}"
                send_message(user_id, f"🔗 لینک اختصاصی شما:\n`{link}`")
                return "OK", 200

            if data == "send_direct":
                send_direct_state.add(user_id)
                send_message(user_id, "📨 آیدی عددی کاربر مقصد را وارد کنید:")
                return "OK", 200

            if data == "back_menu":
                if user_id in ADMIN_IDS:
                    send_message(user_id, "🛠 پنل مدیریت", reply_markup=admin_menu())
                else:
                    send_message(user_id, "🔙 منوی اصلی", reply_markup=main_menu())
                return "OK", 200

            # ارسال دوباره
            if data.startswith("send_again|"):
                parts = data.split("|")
                if len(parts) == 3:
                    _, mode, tid = parts
                    target_id = int(tid)
                    if mode == "user_link":
                        if is_blocked(target_id, user_id):
                            send_message(user_id, "⛔️ شما توسط این کاربر بلاک شده‌اید.")
                        else:
                            user_links[user_id] = target_id
                            send_message(user_id, "✉️ پیام خود را ارسال کنید:")
                    elif mode == "owner_reply":
                        owner = last_owner_cache.get(target_id) or get_last_owner(target_id)
                        if user_id not in ADMIN_IDS and user_id != owner:
                            send_message(user_id, "⛔️ دسترسی غیرمجاز.")
                        else:
                            reply_state[user_id] = target_id
                            send_message(user_id, "✉️ پاسخ خود را ارسال کنید:")
                return "OK", 200

            # بخش ادمین
            if user_id not in ADMIN_IDS:
                return "OK", 200

            if data == "admin_stats":
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM users")
                total = cur.fetchone()[0]
                conn.close()
                send_message(user_id, f"👥 تعداد کاربران: {total}")
                return "OK", 200

            if data == "admin_latest_users":
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT user_id, full_name, username, last_seen FROM users ORDER BY last_seen DESC LIMIT 15")
                rows = cur.fetchall()
                conn.close()
                if not rows:
                    send_message(user_id, "❌ کاربری یافت نشد.")
                    return "OK", 200
                txt = "🆕 آخرین کاربران:\n"
                for uid, name, uname, ts in rows:
                    txt += f"\n👤 {name or 'بدون نام'} (🆔 {uid})"
                    if uname:
                        txt += f" @{uname}"
                    txt += f" — {datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')}"
                send_message(user_id, txt[:4000])
                return "OK", 200

            if data == "admin_search":
                admin_search_state.add(user_id)
                send_message(user_id, "🔍 آیدی عددی کاربر را وارد کنید:")
                return "OK", 200

            if data == "admin_broadcast":
                admin_broadcast_state.add(user_id)
                send_message(user_id, "📢 متن پیام همگانی را بفرستید:")
                return "OK", 200

            if data.startswith("reply_"):
                target = int(data.split("_")[1])
                owner = last_owner_cache.get(target) or get_last_owner(target)
                if user_id not in ADMIN_IDS and user_id != owner:
                    send_message(user_id, "⛔️ دسترسی غیرمجاز")
                    return "OK", 200
                reply_state[user_id] = target
                send_message(user_id, "✉️ پاسخ خود را بنویسید:")
                return "OK", 200

            if data.startswith("block_"):
                target = int(data.split("_")[1])
                owner = last_owner_cache.get(target) or get_last_owner(target)
                if user_id not in ADMIN_IDS and user_id != owner:
                    send_message(user_id, "⛔️ دسترسی غیرمجاز")
                    return "OK", 200
                block_user(user_id, target)
                send_message(user_id, "🚫 کاربر بلاک شد.")
                return "OK", 200

            return "OK", 200

        # پردازش پیام معمولی
        if "message" in update:
            msg = update["message"]
            user_id = msg["from"]["id"]
            username = msg["from"].get("username", "")
            full_name = msg["from"].get("first_name", "")
            text = msg.get("text", "")

            save_user(user_id, username, full_name)

            # استارت و لینک
            if text.startswith("/start"):
                parts = text.split()
                if len(parts) > 1 and parts[1].isdigit():
                    owner_id = int(parts[1])
                    if is_blocked(owner_id, user_id):
                        send_message(user_id, "⛔️ شما توسط این کاربر بلاک شده‌اید.")
                        return "OK", 200
                    user_links[user_id] = owner_id
                    send_message(user_id, "✅ حالت ارسال ناشناس فعال شد.\nپیام خود را ارسال کنید:")
                    return "OK", 200
                else:
                    if user_id in ADMIN_IDS:
                        send_message(user_id, "🛠 پنل مدیریت", reply_markup=admin_menu())
                    else:
                        send_message(user_id, "👋 به ربات خوش آمدید!", reply_markup=main_menu())
                    return "OK", 200

            # وضعیت‌های ادمین
            if user_id in ADMIN_IDS:
                if user_id in admin_search_state:
                    admin_search_state.discard(user_id)
                    if text.isdigit():
                        target = int(text)
                        rows = get_user_messages(target)
                        if not rows:
                            send_message(user_id, "❌ پیامی برای این کاربر یافت نشد.")
                            return "OK", 200
                        resp = f"📜 پیام‌های کاربر {target}:\n"
                        for s, r, t, c, ts in rows[:15]:
                            direction = "📤 ارسال" if s == target else "📥 دریافت"
                            dt = datetime.fromtimestamp(ts).strftime("%H:%M %Y-%m-%d")
                            resp += f"\n{direction} [{dt}] {t}: {c[:80]}"
                        send_message(user_id, resp[:4000])
                    else:
                        send_message(user_id, "❌ لطفاً یک آیدی عددی وارد کنید.")
                    return "OK", 200

                if user_id in admin_broadcast_state:
                    admin_broadcast_state.discard(user_id)
                    users = get_all_users()
                    send_message(user_id, f"📢 در حال ارسال به {len(users)} کاربر...")
                    ok = 0
                    for uid in users:
                        try:
                            send_message(uid, text)
                            ok += 1
                        except:
                            pass
                    send_message(user_id, f"✅ ارسال شد: {ok} موفق، {len(users)-ok} ناموفق")
                    return "OK", 200

            # ارسال مستقیم (کاربر عادی)
            if user_id in send_direct_state:
                send_direct_state.discard(user_id)
                if text.isdigit():
                    target = int(text)
                    reply_state[user_id] = target
                    send_message(user_id, "✉️ پیام خود را ارسال کنید:")
                else:
                    send_message(user_id, "❌ باید یک آیدی عددی وارد کنید.")
                return "OK", 200

            # پاسخ به پیام
            if user_id in reply_state:
                target = reply_state.pop(user_id)
                send_message(target, text)
                save_message(user_id, target, "reply", text)
                send_message(user_id, "✅ پاسخ شما ارسال شد.", reply_markup=after_send_menu("owner_reply", target))
                return "OK", 200

            # ارسال ناشناس از طریق لینک
            if user_id in user_links:
                owner = user_links.pop(user_id)
                if is_blocked(owner, user_id):
                    send_message(user_id, "⛔️ شما توسط این کاربر بلاک شده‌اید.")
                    return "OK", 200

                user_info = f"📨 پیام ناشناس جدید:\nاز کاربر: {user_id}"
                if username:
                    user_info += f" (@{username})"
                if full_name:
                    user_info += f" - {full_name}"
                user_info += f"\n\nمتن:\n{text}"

                send_message(owner, user_info)
                send_message(owner, "🔽 گزینه‌ها:", reply_markup=reply_block_menu(user_id))

                save_message(user_id, owner, "forward", text)
                last_owner_cache[user_id] = owner
                send_message(user_id, "✅ پیام شما ارسال شد.", reply_markup=after_send_menu("user_link", owner))
                return "OK", 200

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
