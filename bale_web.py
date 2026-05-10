import os
import sqlite3
import time
from datetime import datetime
from typing import Dict, Set, Optional
from flask import Flask, request, jsonify
import requests

# ========== بارگذاری توکن (مثل پروژه اصلی) ==========
def load_token() -> str:
    token = os.environ.get("BOT_TOKEN")
    if token and token.strip():
        return token.strip()
    for name in ("Token.txt", "token.txt"):
        try:
            with open(name, "r", encoding="="utf-8") as f:
                t = f.read().strip()
                if t:
                    return t
        except FileNotFoundError:
            pass
    raise ValueError("BOT_TOKEN not found")

TOKEN = load_token()
ADMIN_IDS = {1246154254}  # 🔁 آیدی خودتان در بله را اینجا وارد کنید

# ========== دیتابیس ==========
def get_db():
    return sqlite3.connect("bot.db", check_same_thread=False)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT, full_name TEXT,
        is_admin INTEGER, last_seen INTEGER)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER, receiver_id INTEGER,
        msg_type TEXT, content TEXT, ts INTEGER)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS blocked_users (
        owner_id INTEGER, blocked_id INTEGER,
        PRIMARY KEY (owner_id, blocked_id))""")
    conn.commit()
    conn.close()

init_db()

def now_ts():
    return int(time.time())

def save_user(user_id: int, username="", full_name=""):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""INSERT OR REPLACE INTO users
        (user_id, username, full_name, is_admin, last_seen)
        VALUES (?,?,?,?,?)""",
        (user_id, username, full_name, int(user_id in ADMIN_IDS), now_ts()))
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

def get_last_owner(sender_id: int) -> Optional[int]:
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

# ========== توابع ارتباط با بله ==========
def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.bale.ai/v1/bot{TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        return requests.post(url, json=data, timeout=10).json()
    except:
        return None

def answer_callback(callback_id, text=""):
    url = f"https://api.bale.ai/v1/bot{TOKEN}/answerCallbackQuery"
    try:
        requests.post(url, json={"callback_query_id": callback_id, "text": text}, timeout=5)
    except:
        pass

# ========== منوهای کیبورد ==========
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
         {"text": "🚫 بلاک", "callback_data": f"block_{user_id}""}]
    ]}

# ========== وضعیت‌های درون حافظه (مثل پروژه اصلی) ==========
user_links: Dict[int, int] = {}        # کاربر -> ادمین (لینک یکبار مصرف)
reply_state: Dict[int, int] = {}       # پاسخ‌دهنده -> هدف
send_direct_state: Set[int] = set()    # کاربرانی که در حالت ارسال مستقیم هستند
admin_search_state: Set[int] = set()
admin_broadcast_state: Set[int] = set()
last_owner_cache: Dict[int, int] = {}  # کش برای ادمین متناظر با کاربر

# ========== پردازش اصلی ==========
def process_update(update: dict):
    # ---------- پردازش Callback Query ----------
    if "callback_query" in update:
        cb = update["callback_query"]
        user_id = cb["from"]["id"]
        username = cb["from"].get("username", "")
        full_name = cb["from"].get("first_name", "")
        data = cb["data"]
        cid = cb["id"]

        save_user(user_id, username, full_name)
        answer_callback(cid)

        # ------ گزینه‌های عمومی ------
        if data == "get_link":
            bot_user = "YOUR_BOT_USERNAME"  # 🔁 یوزرنیم رباتتان
            link = f"https://ble.ir/{bot_user}?start={user_id}"
            send_message(user_id, f"🔗 لینک اختصاصی شما:\n`{link}`\n(این لینک را به اشتراک بگذارید)")
            return

        if data == "send_direct":
            send_direct_state.add(user_id)
            send_message(user_id, "📨 آیدی عددی کاربر مقصد را وارد کنید:")
            return

        if data == "back_menu":
            if user_id in ADMIN_IDS:
                send_message(user_id, "🛠 پنل مدیریت", reply_markup=admin_menu())
            else:
                send_message(user_id, "🔙 منوی اصلی", reply_markup=main_menu())
            return

        # ------ ارسال دوباره ------
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
            return

        # ------ بخش ادمین (فقط برای ادمین‌ها) ------
        if user_id not in ADMIN_IDS:
            return

        if data == "admin_stats":
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0]
            conn.close()
            send_message(user_id, f"👥 تعداد کاربران: {total}")
            return

        if data == "admin_latest_users":
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT user_id, full_name, username, last_seen FROM users ORDER BY last_seen DESC LIMIT 15")
            rows = cur.fetchall()
            conn.close()
            if not rows:
                send_message(user_id, "❌ کاربری یافت نشد.")
                return
            txt = "🆕 آخرین کاربران:\n"
            for uid, name, uname, ts in rows:
                txt += f"\n👤 {name or 'بدون نام'} (🆔 {uid})"
                if uname:
                    txt += f" @{uname}"
                txt += f" — {datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')}"
            send_message(user_id, txt[:4000])
            return

        if data == "admin_search":
            admin_search_state.add(user_id)
            send_message(user_id, "🔍 آیدی عددی کاربر را وارد کنید:")
            return

        if data == "admin_broadcast":
            admin_broadcast_state.add(user_id)
            send_message(user_id, "📢 متن پیام همگانی را بفرستید:")
            return

        # ------ پاسخ / بلاک (Owner & Admin) ------
        if data.startswith("reply_"):
            target = int(data.split("_")[1])
            owner = last_owner_cache.get(target) or get_last_owner(target)
            if user_id not in ADMIN_IDS and user_id != owner:
                send_message(user_id, "⛔️ دسترسی غیرمجاز")
                return
            reply_state[user_id] = target
            send_message(user_id, "✉️ پاسخ خود را بنویسید:")
            return

        if data.startswith("block_"):
            target = int(data.split("_")[1])
            owner = last_owner_cache.get(target) or get_last_owner(target)
            if user_id not in ADMIN_IDS and user_id != owner:
                send_message(user_id, "⛔️ دسترسی غیرمجاز")
                return
            block_user(user_id, target)
            send_message(user_id, "🚫 کاربر بلاک شد.")
            return

        return  # پایان callback

    # ---------- پردازش پیام معمولی ----------
    msg = update.get("message", {})
    if not msg:
        return

    user_id = msg["from"]["id"]
    username = msg["from"].get("username", "")
    full_name = msg["from"].get("first_name", "")
    text = msg.get("text", "")

    save_user(user_id, username, full_name)

    # ------ شروع - استارت و لینک دعوت ------
    if text.startswith("/start"):
        parts = text.split()
        if len(parts) > 1 and parts[1].isdigit():
            owner_id = int(parts[1])
            if is_blocked(owner_id, user_id):
                send_message(user_id, "⛔️ شما توسط این کاربر بلاک شده‌اید.")
                return
            user_links[user_id] = owner_id
            send_message(user_id, "✅ حالت ارسال ناشناس فعال شد.\nپیام خود را ارسال کنید:")
            return
        else:
            if user_id in ADMIN_IDS:
                send_message(user_id, "🛠 پنل مدیریت", reply_markup=admin_menu())
            else:
                send_message(user_id, "👋 به ربات خوش آمدید!", reply_markup=main_menu())
            return

    # ------ وضعیت‌های ادمین ------
    if user_id in ADMIN_IDS:
        # جستجو
        if user_id in admin_search_state:
            admin_search_state.discard(user_id)
            if text.isdigit():
                target = int(text)
                rows = get_user_messages(target)
                if not rows:
                    send_message(user_id, "❌ پیامی برای این کاربر یافت نشد.")
                    return
                resp = f"📜 پیام‌های کاربر {target}:\n"
                for s, r, t, c, ts in rows[:15]:
                    direction = "📤 ارسال" if s == target else "📥 دریافت"
                    dt = datetime.fromtimestamp(ts).strftime("%H:%M %Y-%m-%d")
                    resp += f"\n{direction} [{dt}] {t}: {c[:80]}"
                send_message(user_id, resp[:4000])
            else:
                send_message(user_id, "❌ لطفاً یک آیدی عددی وارد کنید.")
            return

        # ارسال همگانی
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
            return

    # ------ ارسال مستقیم (کاربر عادی) ------
    if user_id in send_direct_state:
        send_direct_state.discard(user_id)
        if text.isdigit():
            target = int(text)
            reply_state[user_id] = target
            send_message(user_id, "✉️ پیام خود را ارسال کنید:")
        else:
            send_message(user_id, "❌ باید یک آیدی عددی وارد کنید.")
        return

    # ------ پاسخ به پیام (ریپلای) ------
    if user_id in reply_state:
        target = reply_state.pop(user_id)
        send_message(target, text)
        save_message(user_id, target, "reply", text)
        send_message(user_id, "✅ پاسخ شما ارسال شد.", reply_markup=after_send_menu("owner_reply", target))
        return

    # ------ ارسال ناشناس از طریق لینک ------
    if user_id in user_links:
        owner = user_links.pop(user_id)
        if is_blocked(owner, user_id):
            send_message(user_id, "⛔️ شما توسط این کاربر بلاک شده‌اید.")
            return

        # ارسال متن به ادمین
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
        return

# ========== راه‌اندازی Flask Webhook ==========
app = Flask(__name__)

@app.route("/", methods=["POST"])
def webhook():
    try:
        update = request.get_json()
        if update:
            process_update(update)
        return "OK", 200
    except Exception as e:
        print("Error:", e)
        return "Internal error", 500

@app.route("/", methods=["GET"])
def health():
    return "Bale Bot is running", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
