import os
import time
import logging
from datetime import datetime
from typing import Dict, Set, Optional, Tuple

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
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

ADMIN_IDS = {1246154254}  # 👈 آیدی خودتان را جایگزین کنید

app = Flask(__name__)

# دیتابیس (Neon PostgreSQL)
database_url = "postgresql+psycopg://neondb_owner:npg_PdDIhBH93tCQ@ep-bitter-scene-apv1qffc-pooler.c-7.us-east-1.aws.neon.tech/neondb?sslmode=require"
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_size": 5,
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
db = SQLAlchemy(app)

logging.basicConfig(level=logging.INFO)

# ========== مدل‌ها ==========
class User(db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255))
    full_name = db.Column(db.String(255))
    is_admin = db.Column(db.Integer, default=0)
    last_seen = db.Column(db.Integer)

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer)
    receiver_id = db.Column(db.Integer)
    msg_type = db.Column(db.String(50))
    content = db.Column(db.Text, default="")
    ts = db.Column(db.Integer)
    message_id = db.Column(db.Integer, nullable=True)

class BlockedUser(db.Model):
    __tablename__ = 'blocked_users'
    owner_id = db.Column(db.Integer, primary_key=True)
    blocked_id = db.Column(db.Integer, primary_key=True)

with app.app_context():
    db.create_all()
    print("✅ دیتابیس آماده است.")

# ========== توابع کمکی ==========
def now_ts():
    return int(time.time())

def save_user(user_id, username="", full_name=""):
    with app.app_context():
        is_admin = 1 if user_id in ADMIN_IDS else 0
        user = db.session.get(User, user_id)
        if user:
            user.username = username
            user.full_name = full_name
            user.is_admin = is_admin
            user.last_seen = now_ts()
        else:
            user = User(user_id=user_id, username=username, full_name=full_name,
                        is_admin=is_admin, last_seen=now_ts())
            db.session.add(user)
        db.session.commit()

def save_message(sender, receiver, msg_type, content="", message_id=None):
    with app.app_context():
        msg = Message(sender_id=sender, receiver_id=receiver, msg_type=msg_type,
                      content=content, ts=now_ts(), message_id=message_id)
        db.session.add(msg)
        db.session.commit()

def is_blocked(owner, user):
    with app.app_context():
        return db.session.query(BlockedUser).filter_by(owner_id=owner, blocked_id=user).first() is not None

def block_user(owner, user):
    with app.app_context():
        if not is_blocked(owner, user):
            db.session.add(BlockedUser(owner_id=owner, blocked_id=user))
            db.session.commit()

def get_last_owner(sender_id):
    with app.app_context():
        msg = db.session.query(Message).filter_by(sender_id=sender_id, msg_type='forward').order_by(Message.ts.desc()).first()
        return msg.receiver_id if msg else None

def get_all_users():
    with app.app_context():
        return [u.user_id for u in db.session.query(User.user_id).filter(User.is_admin == 0).all()]

def get_user_messages(uid, limit=30):
    with app.app_context():
        msgs = db.session.query(Message).filter(
            (Message.sender_id == uid) | (Message.receiver_id == uid)
        ).order_by(Message.ts.desc()).limit(limit).all()
        return [(m.sender_id, m.receiver_id, m.msg_type, m.content, m.ts, m.message_id) for m in msgs]

# ========== توابع API بله ==========
def send_message(chat_id, text, reply_markup=None, reply_to_message_id=None):
    url = f"https://tapi.bale.ai/bot{TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = reply_markup
    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id
    try:
        resp = requests.post(url, json=data, timeout=10)
        result = resp.json()
        logging.info(f"📤 send_message to {chat_id} | status={resp.status_code} | ok={result.get('ok')} | text={text[:50]}...")
        if result.get('ok') and result.get('result'):
            return result['result'].get('message_id')
        else:
            logging.error(f"❌ send_message failed: {result}")
            return None
    except Exception as e:
        logging.error(f"❌ send_message error: {e}")
        return None

def answer_callback(callback_id, text=""):
    url = f"https://tapi.bale.ai/bot{TOKEN}/answerCallbackQuery"
    try:
        requests.post(url, json={"callback_query_id": callback_id, "text": text}, timeout=5)
    except:
        pass

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

def after_send_menu(mode, target_id, last_message_id=None):
    return {"inline_keyboard": [
        [{"text": "✉️ ارسال دوباره", "callback_data": f"send_again|{mode}|{target_id}|{last_message_id if last_message_id else ''}"}],
        [{"text": "🔙 منوی اصلی", "callback_data": "back_menu"}]
    ]}

def reply_block_menu(user_id, message_id):
    return {"inline_keyboard": [
        [{"text": "✉️ پاسخ", "callback_data": f"reply_{user_id}_{message_id}"},
         {"text": "🚫 بلاک", "callback_data": f"block_{user_id}"}]
    ]}

# ========== وضعیت‌های موقت ==========
user_links: Dict[int, int] = {}
reply_state: Dict[int, Tuple[int, int]] = {}
send_direct_state: Set[int] = set()
admin_search_state: Set[int] = set()
admin_broadcast_state: Set[int] = set()
last_owner_cache: Dict[int, int] = {}

# ========== Webhook ==========
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = request.get_json()
        if not update:
            return "OK", 200
        logging.info(f"📥 Webhook received")

        # -------------------- Callback Query --------------------
        if "callback_query" in update:
            cb = update["callback_query"]
            uid = cb["from"]["id"]
            username = cb["from"].get("username", "")
            full_name = cb["from"].get("first_name", "")
            data = cb["data"]
            cid = cb["id"]
            save_user(uid, username, full_name)
            answer_callback(cid)

            # منوی اصلی
            if data == "get_link":
                bot_user = "Na8henasBot"   # 👈 یوزرنیم ربات خود را بگذار
                link = f"https://ble.ir/{bot_user}?start={uid}"
                send_message(uid, f"🔗 لینک اختصاصی:\n`{link}`")
                return "OK", 200
            if data == "send_direct":
                send_direct_state.add(uid)
                send_message(uid, "📨 آیدی عددی مقصد را بفرست:")
                return "OK", 200
            if data == "back_menu":
                if uid in ADMIN_IDS:
                    send_message(uid, "🛠 پنل مدیریت", reply_markup=admin_menu())
                else:
                    send_message(uid, "🔙 منوی اصلی", reply_markup=main_menu())
                return "OK", 200

            # ارسال دوباره
            if data.startswith("send_again|"):
                parts = data.split("|")
                if len(parts) >= 3:
                    mode, target = parts[1], int(parts[2])
                    last_msg = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
                    if mode == "user_link":
                        if is_blocked(target, uid):
                            send_message(uid, "⛔️ بلاک شده‌اید")
                        else:
                            user_links[uid] = target
                            send_message(uid, "✉️ پیامت را بفرست")
                    elif mode == "owner_reply":
                        owner = last_owner_cache.get(target) or get_last_owner(target)
                        if uid not in ADMIN_IDS and uid != owner:
                            send_message(uid, "⛔️ دسترسی ندارید")
                        else:
                            reply_state[uid] = (target, last_msg)
                            send_message(uid, "✉️ پاسخ خود را بنویسید")
                return "OK", 200

            # پاسخ به پیام (ریپلای) - اصلاح شده
            if data.startswith("reply_"):
                parts = data.split("_")
                if len(parts) >= 3:
                    target_user = int(parts[1])
                    reply_to_msg = int(parts[2]) if parts[2].isdigit() else None
                    reply_state[uid] = (target_user, reply_to_msg)
                    send_message(uid, "✉️ پاسخ خود را بنویسید:")
                return "OK", 200

            # بلاک
            if data.startswith("block_"):
                target_user = int(data.split("_")[1])
                owner = last_owner_cache.get(target_user) or get_last_owner(target_user)
                if uid not in ADMIN_IDS and uid != owner:
                    send_message(uid, "⛔️ دسترسی ندارید")
                else:
                    block_user(uid, target_user)
                    send_message(uid, "🚫 کاربر بلاک شد")
                return "OK", 200

            # بخش ادمین
            if uid not in ADMIN_IDS:
                return "OK", 200
            if data == "admin_stats":
                total = db.session.query(User).count()
                send_message(uid, f"👥 تعداد کاربران: {total}")
                return "OK", 200
            if data == "admin_latest_users":
                users = db.session.query(User).order_by(User.last_seen.desc()).limit(15).all()
                if not users:
                    send_message(uid, "کاربری یافت نشد")
                else:
                    txt = "🆕 آخرین کاربران:\n"
                    for u in users:
                        txt += f"\n👤 {u.full_name or 'بدون نام'} (🆔 {u.user_id}) @{u.username or ''} — {datetime.fromtimestamp(u.last_seen).strftime('%Y-%m-%d %H:%M')}"
                    send_message(uid, txt[:4000])
                return "OK", 200
            if data == "admin_search":
                admin_search_state.add(uid)
                send_message(uid, "🔍 آیدی عددی کاربر را بفرست")
                return "OK", 200
            if data == "admin_broadcast":
                admin_broadcast_state.add(uid)
                send_message(uid, "📢 متن پیام همگانی را بفرست")
                return "OK", 200

        # -------------------- پیام معمولی --------------------
        if "message" in update:
            msg = update["message"]
            uid = msg["from"]["id"]
            username = msg["from"].get("username", "")
            full_name = msg["from"].get("first_name", "")
            text = msg.get("text", "")
            message_id = msg.get("message_id")
            save_user(uid, username, full_name)

            # استارت و لینک
            if text.startswith("/start"):
                parts = text.split()
                if len(parts) > 1 and parts[1].isdigit():
                    owner = int(parts[1])
                    if is_blocked(owner, uid):
                        send_message(uid, "⛔️ بلاک شده‌اید")
                        return "OK", 200
                    user_links[uid] = owner
                    send_message(uid, "✅ حالت ناشناس فعال شد. پیام خود را بفرست:")
                    return "OK", 200
                else:
                    if uid in ADMIN_IDS:
                        send_message(uid, "🛠 پنل مدیریت", reply_markup=admin_menu())
                    else:
                        send_message(uid, "👋 خوش آمدید!", reply_markup=main_menu())
                    return "OK", 200

            # ادمین: جستجو و همگانی
            if uid in ADMIN_IDS:
                if uid in admin_search_state:
                    admin_search_state.discard(uid)
                    if text.isdigit():
                        target = int(text)
                        rows = get_user_messages(target, 30)
                        if not rows:
                            send_message(uid, "❌ پیامی یافت نشد")
                        else:
                            resp = f"📜 پیام‌های {target}:\n"
                            for s, r, t, c, ts, mid in rows[:15]:
                                direction = "📤 ارسال" if s == target else "📥 دریافت"
                                dt = datetime.fromtimestamp(ts).strftime("%H:%M %Y-%m-%d")
                                resp += f"\n{direction} [{dt}] {t}: {c[:80]}"
                            send_message(uid, resp[:4000])
                    else:
                        send_message(uid, "❌ آیدی عددی بفرست")
                    return "OK", 200
                if uid in admin_broadcast_state:
                    admin_broadcast_state.discard(uid)
                    users = get_all_users()
                    send_message(uid, f"📢 ارسال به {len(users)} کاربر...")
                    ok = 0
                    for u in users:
                        if send_message(u, text):
                            ok += 1
                    send_message(uid, f"✅ موفق: {ok} از {len(users)}")
                    return "OK", 200

            # ارسال مستقیم
            if uid in send_direct_state:
                send_direct_state.discard(uid)
                if text.isdigit():
                    target = int(text)
                    reply_state[uid] = (target, None)
                    send_message(uid, "✉️ پیام خود را ارسال کن")
                else:
                    send_message(uid, "❌ فقط آیدی عددی")
                return "OK", 200

            # ========== پاسخ به پیام (بخش اصلاح شده) ==========
            if uid in reply_state:
                target, reply_to_msg = reply_state.pop(uid)

                # 1) ابتدا متن پاسخ را بدون هیچ دکمه و بدون ریپلای ارسال کن (برای اطمینان از دیده شدن متن)
                sent_msg_id = send_message(target, text)   # بدون reply_to_message_id
                if sent_msg_id:
                    save_message(uid, target, "reply", text, sent_msg_id)

                    # 2) سپس یک پیام جداگانه حاوی دکمه پاسخ (برای ادامه زنجیره) بفرست
                    #    این دکمه به کاربر target اجازه می‌دهد به این پاسخ جدید، پاسخ دهد.
                    send_message(target, "🔽 گزینه‌ها:", reply_markup=reply_block_menu(uid, sent_msg_id))

                    # 3) به پاسخ‌دهنده (uid) پیام موفقیت و گزینه ارسال دوباره بده
                    send_message(uid, "✅ پاسخ ارسال شد", reply_markup=after_send_menu("owner_reply", target, sent_msg_id))
                else:
                    send_message(uid, "❌ ارسال پاسخ ناموفق بود. لطفاً دوباره تلاش کن.")
                return "OK", 200

            # ارسال ناشناس از طریق لینک
            if uid in user_links:
                owner = user_links.pop(uid)
                if is_blocked(owner, uid):
                    send_message(uid, "⛔️ شما بلاک شده‌اید")
                    return "OK", 200
                user_info = f"📨 پیام ناشناس:\nاز: {uid}"
                if username:
                    user_info += f" (@{username})"
                if full_name:
                    user_info += f" - {full_name}"
                user_info += f"\n\nمتن:\n{text}"
                sent = send_message(owner, user_info)
                if sent:
                    save_message(uid, owner, "forward", text, sent)
                    send_message(owner, "🔽 گزینه‌ها:", reply_markup=reply_block_menu(uid, sent))
                    last_owner_cache[uid] = owner
                    send_message(uid, "✅ پیام ارسال شد", reply_markup=after_send_menu("user_link", owner, sent))
                else:
                    send_message(uid, "❌ ارسال نشد")
                return "OK", 200

        return "OK", 200

    except Exception as e:
        logging.error(f"❌ Webhook exception: {e}", exc_info=True)
        return "Internal error", 500

@app.route("/", methods=["GET"])
def home():
    return "Bale bot (Neon DB + fixed reply)", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
