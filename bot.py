import telebot
import sqlite3
import logging
import os
import time
import random
import requests
from telebot import types
from datetime import datetime, timedelta
from threading import Lock, Thread
from dotenv import load_dotenv

# ================= CONFIG =================
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "2010030869"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "stars_sovga_gifbot")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@Stars_5_odam_1stars")

YOUTUBE_LINK = os.getenv("YOUTUBE_LINK", "https://youtube.com/@example")
INSTAGRAM_LINK = os.getenv("INSTAGRAM_LINK", "https://instagram.com/example")

if not API_TOKEN:
    print("❌ TOKEN topilmadi!")
    exit(1)

# ================= SOZLAMALAR =================
REQUIRED_CHANNELS = [
    {"id": -1003737363661, "username": "@Tekin_stars_yulduz", "url": "https://t.me/Tekin_stars_yulduz", "name": "📢 KANAL"},
    {"id": -1002449896845, "username": "@Stars_2_odam_1stars", "url": "https://t.me/Stars_2_odam_1stars", "name": "👥 GURUH"}
]
GROUP_ID = -1002449896845
GROUP_LINK = "https://t.me/Stars_2_odam_1stars"
DAILY_BONUS = 0.20

# ================= REKLAMA VA MOTIVATSIYA =================
ADS_BOT = "@zurnavolarbot"
ADS_MESSAGES = [
    f"🎵 {ADS_BOT} - Eng zo'r musiqa boti!",
    f"🔥 {ADS_BOT} - Sevimli qo'shiqlaringiz!",
    f"🎶 {ADS_BOT} - Musiqa dunyosi!",
    f"💃 {ADS_BOT} - Raqsga tushing!",
    f"🎧 {ADS_BOT} - Hit qo'shiqlar!"
]

MOTIVATIONS = [
    "🔥 Siz zo'rsiz! Davom eting!",
    "💪 Har bir taklif - yulduz sari qadam!",
    "⭐ Yulduzlar sizni kutmoqda!",
    "🚀 Oldinga, lider bo'ling!",
    "👑 Siz eng yaxshisisiz!",
    "🎯 Maqsad sari intiling!",
    "💎 Katta sovg'alar kutyapti!",
    "🌟 Yulduzlar soni oshmoqda!",
    "🏆 Chempion bo'ling!",
    "⚡ Kuch sizda!"
]

GIFT_ADS = [
    {"emoji": "❤️", "name": "Pushti Yurakcha", "desc": "Sevgi ramzi!", "photo": "https://i.imgur.com/8Yp9Z2M.jpg"},
    {"emoji": "🧸", "name": "Ayiqcha", "desc": "Yoqimli sovg'a!", "photo": "https://i.imgur.com/5f2vL8K.jpg"},
    {"emoji": "🌹", "name": "Atirgul", "desc": "Romantik!", "photo": "https://i.imgur.com/7zK9pQm.jpg"},
    {"emoji": "🎁", "name": "Sovg'a qutisi", "desc": "Sirli sovg'a!", "photo": "https://i.imgur.com/3vX9pLm.jpg"},
]

# ================= TASKLAR =================
TASKS = [
    {"id": "channel1", "type": "telegram", "name": "📢 Kanalga obuna bo'ling", "link": "https://t.me/Tekin_stars_yulduz", "channel_id": -1003737363661, "reward": 0.20},
    {"id": "channel2", "type": "telegram", "name": "👥 Guruhga obuna bo'ling", "link": "https://t.me/Stars_2_odam_1stars", "channel_id": -1002449896845, "reward": 0.20},
    {"id": "youtube", "type": "external", "name": "🎬 YouTube kanal", "link": YOUTUBE_LINK, "reward": 0.20},
    {"id": "instagram", "type": "external", "name": "📸 Instagram", "link": INSTAGRAM_LINK, "reward": 0.20}
]

# ================= BOT INIT =================
bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML", threaded=False)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BOT")

# ================= DATABASE =================
lock = Lock()
pending_verifications = {}  # {user_id: {task_id: timestamp}}

class DB:
    def __init__(self):
        self.conn = sqlite3.connect("bot.db", check_same_thread=False)
        self.cur = self.conn.cursor()
        self.init()

    def init(self):
        with lock:
            self.cur.executescript("""
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                invites INTEGER DEFAULT 0,
                stars REAL DEFAULT 0,
                vip INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                last_daily TIMESTAMP,
                last_ad TIMESTAMP,
                daily_streak INTEGER DEFAULT 0,
                total_spent REAL DEFAULT 0,
                total_earned REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS invite_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inviter_id INTEGER,
                invited_id INTEGER,
                invited_name TEXT,
                source TEXT DEFAULT 'group',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS purchase_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_name TEXT,
                item_emoji TEXT,
                price REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_tasks(
                user_id INTEGER,
                task_id TEXT,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(user_id, task_id)
            );
            CREATE TABLE IF NOT EXISTS pending_invites(
                inviter_id INTEGER,
                invited_id INTEGER,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(inviter_id, invited_id)
            );
            """)
            self.conn.commit()

    def create_user(self, uid, username, name):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO users(user_id, username, first_name) VALUES(?,?,?)", (uid, username, name))
            self.conn.commit()

    def get(self, uid):
        with lock:
            self.cur.execute("SELECT invites, stars, vip, total_spent, last_daily, last_ad, daily_streak, total_earned FROM users WHERE user_id=?", (uid,))
            row = self.cur.fetchone()
            if row:
                return {"invites": row[0] or 0, "stars": float(row[1] or 0), "vip": row[2] or 0, "spent": float(row[3] or 0), "last_daily": row[4], "last_ad": row[5], "streak": row[6] or 0, "earned": float(row[7] or 0)}
            return {"invites": 0, "stars": 0.0, "vip": 0, "spent": 0.0, "last_daily": None, "last_ad": None, "streak": 0, "earned": 0.0}

    def add_invite(self, uid):
        with lock:
            self.cur.execute("UPDATE users SET invites = invites + 1 WHERE user_id=?", (uid,))
            self.cur.execute("SELECT invites FROM users WHERE user_id=?", (uid,))
            row = self.cur.fetchone()
            invites = row[0] or 0
            stars = invites / 2.0
            self.cur.execute("UPDATE users SET stars=?, total_earned=total_earned+? WHERE user_id=?", (stars, 0.5, uid))
            self.conn.commit()
            return invites, stars

    def add_history(self, inviter_id, invited_id, invited_name, source="group"):
        with lock:
            self.cur.execute("INSERT INTO invite_history(inviter_id, invited_id, invited_name, source) VALUES(?,?,?,?)", (inviter_id, invited_id, invited_name, source))
            self.conn.commit()

    def add_purchase_history(self, uid, item_name, item_emoji, price):
        with lock:
            self.cur.execute("INSERT INTO purchase_history(user_id, item_name, item_emoji, price) VALUES(?,?,?,?)", (uid, item_name, item_emoji, price))
            self.conn.commit()

    def check_duplicate(self, inviter_id, invited_id):
        with lock:
            self.cur.execute("SELECT COUNT(*) FROM invite_history WHERE inviter_id=? AND invited_id=?", (inviter_id, invited_id))
            return self.cur.fetchone()[0] > 0

    def sub_star(self, uid, amount):
        with lock:
            self.cur.execute("SELECT stars FROM users WHERE user_id=?", (uid,))
            row = self.cur.fetchone()
            current = float(row[0] or 0)
            new_stars = max(0.0, current - amount)
            self.cur.execute("UPDATE users SET stars=?, total_spent=total_spent+? WHERE user_id=?", (new_stars, amount, uid))
            self.conn.commit()
            return new_stars

    def add_stars_admin(self, uid, amount):
        with lock:
            self.cur.execute("SELECT invites FROM users WHERE user_id=?", (uid,))
            row = self.cur.fetchone()
            ci = row[0] or 0
            ni = ci + int(amount * 2)
            ns = ni / 2.0
            self.cur.execute("UPDATE users SET invites=?, stars=?, total_earned=total_earned+? WHERE user_id=?", (ni, ns, amount, uid))
            self.conn.commit()
            return ns

    def give_daily_bonus(self, uid):
        with lock:
            self.cur.execute("SELECT last_daily, stars, daily_streak, total_earned FROM users WHERE user_id=?", (uid,))
            row = self.cur.fetchone()
            if row:
                last_daily = row[0]
                cs = float(row[1] or 0)
                streak = row[2] or 0
                te = float(row[3] or 0)
                now = datetime.now()
                if last_daily:
                    try:
                        last = datetime.fromisoformat(last_daily)
                        if now.date() == last.date():
                            return False, cs, 0, streak, 0
                        if (now.date() - last.date()).days == 1:
                            streak += 1
                        else:
                            streak = 1
                    except:
                        streak = 1
                else:
                    streak = 1
                bonus = DAILY_BONUS
                extra = 0
                if streak > 0 and streak % 7 == 0:
                    extra = 0.5
                    bonus += extra
                ns = cs + bonus
                ne = te + bonus
                self.cur.execute("UPDATE users SET stars=?, last_daily=?, daily_streak=?, total_earned=? WHERE user_id=?", (ns, now.isoformat(), streak, ne, uid))
                self.conn.commit()
                return True, ns, bonus, streak, extra
            return False, 0.0, 0, 0, 0

    def can_send_ad(self, uid, hours=48):
        with lock:
            self.cur.execute("SELECT last_ad FROM users WHERE user_id=?", (uid,))
            row = self.cur.fetchone()
            if row and row[0]:
                try:
                    last = datetime.fromisoformat(row[0])
                    if datetime.now() < last + timedelta(hours=hours):
                        return False
                except:
                    pass
            return True

    def update_last_ad(self, uid):
        with lock:
            self.cur.execute("UPDATE users SET last_ad=? WHERE user_id=?", (datetime.now().isoformat(), uid))
            self.conn.commit()

    def grant_vip(self, uid):
        with lock:
            self.cur.execute("UPDATE users SET vip=1 WHERE user_id=?", (uid,))
            self.conn.commit()

    def get_top(self, limit=10):
        with lock:
            self.cur.execute("SELECT username, first_name, invites, stars, vip, daily_streak FROM users WHERE is_banned=0 ORDER BY invites DESC LIMIT ?", (limit,))
            return self.cur.fetchall()

    def get_top_streak(self, limit=10):
        with lock:
            self.cur.execute("SELECT username, first_name, daily_streak, stars FROM users WHERE is_banned=0 AND daily_streak>0 ORDER BY daily_streak DESC LIMIT ?", (limit,))
            return self.cur.fetchall()

    def get_history(self, uid):
        with lock:
            self.cur.execute("SELECT invited_id, invited_name, source, created_at FROM invite_history WHERE inviter_id=? ORDER BY created_at DESC LIMIT 10", (uid,))
            return self.cur.fetchall()

    def get_purchase_history(self, uid):
        with lock:
            self.cur.execute("SELECT item_name, item_emoji, price, created_at FROM purchase_history WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (uid,))
            return self.cur.fetchall()

    def check_ban(self, uid):
        with lock:
            self.cur.execute("SELECT is_banned FROM users WHERE user_id=?", (uid,))
            row = self.cur.fetchone()
            return row and row[0] == 1

    def ban_user(self, uid):
        with lock:
            self.cur.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (uid,))
            self.conn.commit()

    def unban_user(self, uid):
        with lock:
            self.cur.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (uid,))
            self.conn.commit()

    def search_user(self, query):
        with lock:
            self.cur.execute("SELECT user_id, username, first_name, invites, stars, vip, daily_streak FROM users WHERE user_id=? OR username LIKE ? OR first_name LIKE ?", (query, f"%{query}%", f"%{query}%"))
            return self.cur.fetchall()

    def get_stats(self):
        with lock:
            s = {}
            self.cur.execute("SELECT COUNT(*) FROM users")
            s["users"] = self.cur.fetchone()[0]
            self.cur.execute("SELECT SUM(invites) FROM users")
            s["invites"] = self.cur.fetchone()[0] or 0
            self.cur.execute("SELECT SUM(stars) FROM users")
            s["stars"] = float(self.cur.fetchone()[0] or 0)
            self.cur.execute("SELECT COUNT(*) FROM users WHERE vip=1")
            s["vip"] = self.cur.fetchone()[0]
            self.cur.execute("SELECT SUM(total_spent) FROM users")
            s["spent"] = float(self.cur.fetchone()[0] or 0)
            self.cur.execute("SELECT COUNT(*) FROM invite_history")
            s["total_invites"] = self.cur.fetchone()[0]
            self.cur.execute("SELECT COUNT(*) FROM purchase_history")
            s["purchases"] = self.cur.fetchone()[0]
            return s

    def get_all_users_for_ad(self):
        with lock:
            self.cur.execute("SELECT user_id FROM users WHERE is_banned=0")
            return [row[0] for row in self.cur.fetchall()]

    # TASKS
    def is_task_completed(self, uid, task_id):
        with lock:
            self.cur.execute("SELECT 1 FROM user_tasks WHERE user_id=? AND task_id=?", (uid, task_id))
            return self.cur.fetchone() is not None

    def complete_task(self, uid, task_id):
        with lock:
            if self.is_task_completed(uid, task_id):
                return False
            self.cur.execute("INSERT INTO user_tasks(user_id, task_id) VALUES(?,?)", (uid, task_id))
            self.cur.execute("UPDATE users SET stars=stars+?, total_earned=total_earned+? WHERE user_id=?", (0.20, 0.20, uid))
            self.conn.commit()
            return True

    # PENDING INVITES
    def add_pending_invite(self, inviter_id, invited_id, source="link"):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO pending_invites(inviter_id, invited_id, source) VALUES(?,?,?)", (inviter_id, invited_id, source))
            self.conn.commit()

    def get_pending_invite(self, invited_id):
        with lock:
            self.cur.execute("SELECT inviter_id, source FROM pending_invites WHERE invited_id=?", (invited_id,))
            return self.cur.fetchone()

    def remove_pending_invite(self, invited_id):
        with lock:
            self.cur.execute("DELETE FROM pending_invites WHERE invited_id=?", (invited_id,))
            self.conn.commit()

db = DB()

# ================= SHOP =================
SHOP = {
    15: {"name": "❤️ Pushti Yurakcha", "emoji": "❤️", "photo": "https://i.imgur.com/8Yp9Z2M.jpg", "desc": "Chiroyli pushti yurak sovg'asi"},
    15: {"name": "🧸 Ayiqcha", "emoji": "🧸", "photo": "https://i.imgur.com/5f2vL8K.jpg", "desc": "Yoqimli ayiqcha sovg'a"},
    25: {"name": "🌹 Atirgul", "emoji": "🌹", "photo": "https://i.imgur.com/7zK9pQm.jpg", "desc": "Romantik atirgul"},
    25: {"name": "🎁 Sovg'a qutisi", "emoji": "🎁", "photo": "https://i.imgur.com/3vX9pLm.jpg", "desc": "Sirli sovg'a qutisi"},
    50: {"name": "🎂 Tort", "emoji": "🎂", "photo": "https://i.imgur.com/9pL2mNx.jpg", "desc": "Shirin tort + VIP"},
    50: {"name": "💐 Gullar", "emoji": "💐", "photo": "https://i.imgur.com/XkP5vRt.jpg", "desc": "Chiroyli guldasta + VIP"},
    100: {"name": "🏆 Oltin kubok", "emoji": "🏆", "photo": "https://i.imgur.com/vL9pQmN.jpg", "desc": "Oltin sovg'a + VIP"},
    100: {"name": "💍 Olmos uzuk", "emoji": "💍", "photo": "https://i.imgur.com/kP8mNxZ.jpg", "desc": "Brilliant uzuk + VIP"},
    200: {"name": "💎 Brilliant", "emoji": "💎", "photo": "https://i.imgur.com/kP8mNxZ.jpg", "desc": "Qimmatbaho brilliant + VIP"},
    500: {"name": "👑 Qirol toji", "emoji": "👑", "photo": "https://i.imgur.com/XkP5vRt.jpg", "desc": "Haqiqiy toj + VIP"},
}

# ================= YORDAMCHI =================
def check_sub(uid):
    not_sub = []
    for ch in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(ch["id"], uid)
            if member.status not in ['member', 'administrator', 'creator']:
                not_sub.append(ch)
        except:
            pass
    return not_sub

def add_footer(text):
    ad = random.choice(ADS_MESSAGES)
    mot = random.choice(MOTIVATIONS)
    return f"{text}\n\n{'─' * 20}\n💡 <i>{mot}</i>\n{ad}"

def format_stars(stars):
    if stars == int(stars):
        return str(int(stars))
    return f"{stars:.2f}"

def get_invite_link(uid):
    return f"https://t.me/{BOT_USERNAME}?start={uid}"

def process_referral(invited_id):
    """Taklif qilingan foydalanuvchi obunani to'liq bajarganidan keyin chaqiriladi"""
    pending = db.get_pending_invite(invited_id)
    if pending:
        inviter_id, source = pending
        if not db.check_duplicate(inviter_id, invited_id):
            db.add_history(inviter_id, invited_id, str(invited_id), source)
            db.add_invite(inviter_id)
        db.remove_pending_invite(invited_id)

# ================= START =================
@bot.message_handler(commands=["start"])
def start(m):
    uid = m.from_user.id
    if db.check_ban(uid):
        return bot.send_message(m.chat.id, "❌ Bloklangansiz!")

    # Referal parametrni saqlash
    if m.text and len(m.text.split()) > 1:
        try:
            ref = int(m.text.split()[1])
            if ref != uid:
                db.add_pending_invite(ref, uid, "link")
        except:
            pass

    not_sub = check_sub(uid)
    if not_sub:
        markup = types.InlineKeyboardMarkup(row_width=1)
        for ch in not_sub:
            markup.add(types.InlineKeyboardButton(f"{ch['name']} - OBUNA", url=ch['url']))
        markup.add(types.InlineKeyboardButton("✅ OBUNA BO'LDIM", callback_data="check_sub"))
        channels = "\n".join([f"• {ch['name']}: {ch['username']}" for ch in not_sub])
        return bot.send_message(m.chat.id, f"❌ Obuna bo'ling:\n\n{channels}", reply_markup=markup)

    db.create_user(uid, m.from_user.username, m.from_user.first_name)

    # Referalni tekshirish (agar obuna bo'lgan bo'lsa)
    process_referral(uid)

    u = db.get(uid)
    vip_status = "✅ HA" if u["vip"] else "❌ YO'Q"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🛒 DO'KON", callback_data="shop"), types.InlineKeyboardButton(f"🎁 +{DAILY_BONUS}⭐", callback_data="daily"))
    markup.add(types.InlineKeyboardButton("🏆 TOP", callback_data="top"), types.InlineKeyboardButton("📊 PROFIL", callback_data="profile"))
    markup.add(types.InlineKeyboardButton("🔗 LINK", callback_data="link"), types.InlineKeyboardButton("📜 XARIDLAR", callback_data="purchases"))
    markup.add(types.InlineKeyboardButton("📋 VAZIFALAR", callback_data="tasks"))

    text = f"""
🌟 <b>STARS BOT</b>

👤 <b>{m.from_user.first_name}</b>
👥 Takliflar: <b>{u['invites']}</b>
⭐ Yulduzlar: <b>{format_stars(u['stars'])}</b>
👑 VIP: <b>{vip_status}</b>
🔥 Streak: {u['streak']} kun

🎯 <i>2 ta taklif = 1⭐</i>
"""
    bot.send_message(m.chat.id, add_footer(text), reply_markup=markup)

# ================= GURUHGA QO'SHISH (faqat pending) =================
@bot.message_handler(content_types=['new_chat_members'])
def new_members(message):
    if message.chat.id != GROUP_ID:
        return

    for member in message.new_chat_members:
        if member.is_bot:
            continue
        inviter_id = message.from_user.id
        invited_id = member.id
        if inviter_id == invited_id:
            continue
        # Taklifni faqat saqlaymiz, hozir hisoblamaymiz
        db.add_pending_invite(inviter_id, invited_id, "group")

    try:
        bot.send_message(message.chat.id, f"✅ {len(message.new_chat_members)} ta yangi a'zo qo'shildi! Obunadan keyin taklif hisoblanadi.")
    except:
        pass

# ================= CALLBACK =================
@bot.callback_query_handler(func=lambda c: True)
def callback(call):
    uid = call.from_user.id
    data = call.data

    if data == "check_sub":
        not_sub = check_sub(uid)
        if not_sub:
            bot.answer_callback_query(call.id, "❌ Obuna bo'ling!", show_alert=True)
        else:
            db.create_user(uid, call.from_user.username, call.from_user.first_name)
            # Obuna bo'lgach, referalni hisobga olish
            process_referral(uid)
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                pass
            bot.answer_callback_query(call.id, "✅ Xush kelibsiz!", show_alert=False)
            start(call.message)
        return

    if data == "daily":
        ok, ns, bonus, streak, extra = db.give_daily_bonus(uid)
        if ok:
            extra_text = f"\n🎉 <b>HAFTALIK!</b> +{extra}⭐" if extra > 0 else ""
            text = f"🎁 <b>KUNLIK BONUS</b>\n\n✨ +{bonus}⭐\n💰 Jami: <b>{format_stars(ns)}</b>\n🔥 Streak: <b>{streak}</b> kun{extra_text}"
            bot.send_message(call.message.chat.id, add_footer(text))
            bot.answer_callback_query(call.id, f"✅ +{bonus}⭐", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ Bugun olgansiz!", show_alert=True)
        return

    if data == "shop":
        u = db.get(uid)
        markup = types.InlineKeyboardMarkup(row_width=2)
        seen = {}
        for price, item in SHOP.items():
            if price not in seen:
                seen[price] = []
            seen[price].append(item)
        for price, items in seen.items():
            can = "✅" if u["stars"] >= price else "🔒"
            for idx, item in enumerate(items):
                cb = f"buy_{price}_{idx}" if len(items) > 1 else f"buy_{price}"
                markup.add(types.InlineKeyboardButton(f"{can} {item['emoji']} {item['name']} {price}⭐", callback_data=cb))
        text = f"🛒 <b>DO'KON</b>\n\n⭐ Balans: <b>{format_stars(u['stars'])}</b>"
        bot.send_message(call.message.chat.id, add_footer(text), reply_markup=markup)

    elif data == "top":
        top = db.get_top(10)
        if top:
            text = "🏆 <b>TOP 10</b>\n\n"
            for i, (u, n, inv, st, v, streak) in enumerate(top, 1):
                user = f"@{u}" if u else n
                medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}️⃣"
                vip_mark = "👑" if v else ""
                text += f"{medal} <b>{user}</b> {vip_mark}\n👥{inv} ⭐{format_stars(st)} 🔥{streak}\n\n"
            bot.send_message(call.message.chat.id, add_footer(text))
        else:
            bot.send_message(call.message.chat.id, "❌ Hali top yo'q!")

    elif data == "profile":
        u = db.get(uid)
        vip_status = "✅ HA" if u["vip"] else "❌ YO'Q"
        text = f"""
📊 <b>PROFIL</b>

👤 {call.from_user.first_name}
🆔 <code>{uid}</code>
👑 VIP: <b>{vip_status}</b>
🔥 Streak: <b>{u['streak']}</b> kun
👥 Takliflar: <b>{u['invites']}</b>
⭐ Yulduzlar: <b>{format_stars(u['stars'])}</b>
💎 Topgan: <b>{format_stars(u['earned'])}</b>⭐
💸 Sarflangan: <b>{format_stars(u['spent'])}</b>⭐
"""
        bot.send_message(call.message.chat.id, add_footer(text))

    elif data == "link":
        link = get_invite_link(uid)
        bot.send_message(call.message.chat.id, add_footer(f"🔗 <code>{link}</code>\n\n📢 {GROUP_LINK}"))

    elif data == "purchases":
        purchases = db.get_purchase_history(uid)
        if purchases:
            text = "📜 <b>XARIDLAR</b>\n\n"
            for name, emoji, price, dt in purchases:
                text += f"{emoji} {name} - {format_stars(price)}⭐\n"
        else:
            text = "❌ Hali xarid yo'q!"
        bot.send_message(call.message.chat.id, add_footer(text))

    elif data == "tasks":
        show_tasks_menu(call.message.chat.id, uid)

    elif data.startswith("task_"):
        task_id = data[5:]
        task = next((t for t in TASKS if t["id"] == task_id), None)
        if not task:
            return
        if db.is_task_completed(uid, task_id):
            bot.answer_callback_query(call.id, "❌ Bu vazifa allaqachon bajarilgan!", show_alert=True)
            return
        if task["type"] == "telegram":
            # Telegram kanaliga obunani tekshirish
            channel_id = task["channel_id"]
            try:
                member = bot.get_chat_member(channel_id, uid)
                if member.status in ['member', 'administrator', 'creator']:
                    if db.complete_task(uid, task_id):
                        bot.send_message(call.message.chat.id, add_footer(f"✅ {task['name']} bajarildi! +{task['reward']}⭐"))
                    else:
                        bot.send_message(call.message.chat.id, "❌ Xatolik yuz berdi.")
                else:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("Obuna bo'lish", url=task['link']))
                    markup.add(types.InlineKeyboardButton("Tekshirish", callback_data=f"task_{task_id}"))
                    bot.send_message(call.message.chat.id, f"❌ Siz {task['name']} ga obuna bo'lmagansiz!", reply_markup=markup)
            except:
                bot.send_message(call.message.chat.id, "❌ Kanalni tekshirishda xatolik.")
        else:
            # Tashqi link (YouTube/Instagram)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔗 Linkni ochish", url=task['link']))
            markup.add(types.InlineKeyboardButton("✅ Obuna bo'ldim", callback_data=f"confirm_external_{task_id}"))
            bot.send_message(call.message.chat.id, f"📢 {task['name']}\n\nQuyidagi link orqali obuna bo'ling, so‘ng «Obuna bo‘ldim» tugmasini bosing.", reply_markup=markup)

    elif data.startswith("confirm_external_"):
        task_id = data[17:]
        task = next((t for t in TASKS if t["id"] == task_id), None)
        if not task:
            return
        if db.is_task_completed(uid, task_id):
            bot.answer_callback_query(call.id, "❌ Vazifa allaqachon bajarilgan!", show_alert=True)
            return
        # Vaqtni saqlash
        pending_verifications[uid] = {task_id: datetime.now()}
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"verify_external_{task_id}"))
        bot.send_message(call.message.chat.id, "⏳ Iltimos 10 soniya kuting, so‘ng «Tasdiqlash» tugmasini bosing.", reply_markup=markup)

    elif data.startswith("verify_external_"):
        task_id = data[16:]
        task = next((t for t in TASKS if t["id"] == task_id), None)
        if not task:
            return
        if db.is_task_completed(uid, task_id):
            bot.answer_callback_query(call.id, "❌ Vazifa allaqachon bajarilgan!", show_alert=True)
            return
        if uid in pending_verifications and task_id in pending_verifications[uid]:
            elapsed = (datetime.now() - pending_verifications[uid][task_id]).total_seconds()
            if elapsed >= 10:
                if db.complete_task(uid, task_id):
                    bot.send_message(call.message.chat.id, add_footer(f"✅ {task['name']} bajarildi! +{task['reward']}⭐"))
                else:
                    bot.send_message(call.message.chat.id, "❌ Xatolik yuz berdi.")
                del pending_verifications[uid][task_id]
                if not pending_verifications[uid]:
                    del pending_verifications[uid]
            else:
                bot.answer_callback_query(call.id, f"⏳ {10 - int(elapsed)} soniya qoldi", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ Avval «Obuna bo‘ldim» tugmasini bosing.", show_alert=True)

    elif data.startswith("buy_"):
        parts = data.split("_")
        price = int(parts[1])
        idx = int(parts[2]) if len(parts) > 2 else 0

        u = db.get(uid)
        if u["stars"] < price:
            bot.answer_callback_query(call.id, f"❌ {format_stars(price - u['stars'])}⭐ yetmaydi!", show_alert=True)
        else:
            items = [(p, item) for p, item in SHOP.items() if p == price]
            item = items[min(idx, len(items)-1)][1]

            ns = db.sub_star(uid, price)
            db.add_purchase_history(uid, item['name'], item['emoji'], price)

            extra = ""
            if price >= 50:
                db.grant_vip(uid)
                extra = "\n👑 <b>VIP BERILDI!</b>"

            admin_link = f"tg://user?id={ADMIN_ID}"
            caption = f"""
✅ <b>SOVG'A BERILDI!</b>

{item['emoji']} <b>{item['name']}</b>
📝 {item['desc']}

💰 Sarflandi: <b>{price}⭐</b>
⭐ Qoldi: <b>{format_stars(ns)}</b>{extra}

{'─' * 20}
📦 <b>HAQIQIY SOVG'A:</b>
👤 <a href='{admin_link}'>{ADMIN_USERNAME}</a>
⏳ Admin yuboradi
📞 <a href='{admin_link}'>BOG'LANISH</a>
"""
            bot.send_photo(call.message.chat.id, item['photo'], caption=add_footer(caption))
            bot.answer_callback_query(call.id, "✅ Berildi!", show_alert=True)

            # Guruhga e'lon (faqat guruhga, kanalga emas)
            try:
                bot.send_message(GROUP_ID, f"🛍 {call.from_user.first_name} {item['emoji']} {item['name']} ({price}⭐)")
            except:
                pass

            # Admin xabari
            try:
                bot.send_message(ADMIN_ID, f"🛍 {call.from_user.first_name}\n🆔 <code>{uid}</code>\n🎁 {item['name']}\n💰 {price}⭐\n📞 <a href='tg://user?id={uid}'>BOG'LANISH</a>")
            except:
                pass

    bot.answer_callback_query(call.id)

def show_tasks_menu(chat_id, uid):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for task in TASKS:
        status = "✅" if db.is_task_completed(uid, task["id"]) else "❌"
        markup.add(types.InlineKeyboardButton(f"{status} {task['name']} (+{task['reward']}⭐)", callback_data=f"task_{task['id']}"))
    bot.send_message(chat_id, "📋 <b>VAZIFALAR</b>\n\nHar bir vazifani bajarib 0.20⭐ yulduz oling.", reply_markup=markup)

# ================= ADMIN =================
@bot.message_handler(commands=["admin"])
def admin_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    s = db.get_stats()
    text = f"🔐 <b>ADMIN</b>\n👥{s['users']} 👥{s['total_invites']}\n⭐{format_stars(s['stars'])} 👑{s['vip']}\n💰{format_stars(s['spent'])} 🛍{s['purchases']}\n\n/addstars /ban /unban /search /broadcast /send"
    bot.send_message(m.chat.id, text)

@bot.message_handler(commands=["addstars"])
def addstars_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        parts = m.text.split()
        uid, amount = int(parts[1]), float(parts[2])
        db.create_user(uid, None, "User")
        ns = db.add_stars_admin(uid, amount)
        bot.reply_to(m, f"✅ {uid} +{format_stars(amount)}⭐ | Jami: {format_stars(ns)}⭐")
    except:
        bot.reply_to(m, "❌ /addstars [id] [miqdor]")

@bot.message_handler(commands=["send"])
def send_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        parts = m.text.split(maxsplit=2)
        uid, text = int(parts[1]), parts[2]
        bot.send_message(uid, f"📩 <b>ADMIN:</b>\n\n{text}")
        bot.reply_to(m, f"✅ {uid} ga yuborildi!")
    except:
        bot.reply_to(m, "❌ /send [id] [matn]")

@bot.message_handler(commands=["ban"])
def ban_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        db.ban_user(int(m.text.split()[1]))
        bot.reply_to(m, "✅ Ban!")
    except:
        bot.reply_to(m, "❌ /ban [id]")

@bot.message_handler(commands=["unban"])
def unban_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        db.unban_user(int(m.text.split()[1]))
        bot.reply_to(m, "✅ Unban!")
    except:
        bot.reply_to(m, "❌ /unban [id]")

@bot.message_handler(commands=["search"])
def search_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        query = m.text.split(maxsplit=1)[1]
        results = db.search_user(query)
        if results:
            text = "🔍\n"
            for uid, un, nm, inv, st, vip, streak in results[:10]:
                user = f"@{un}" if un else nm
                text += f"🆔{uid} {user} {'👑' if vip else ''} 👥{inv} ⭐{format_stars(st)}\n"
            bot.reply_to(m, text)
        else:
            bot.reply_to(m, "❌ Topilmadi!")
    except:
        bot.reply_to(m, "❌ /search [id/username]")

@bot.message_handler(commands=["broadcast"])
def broadcast_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        text = m.text.split(maxsplit=1)[1]
        users = db.get_all_users_for_ad()
        sent = 0
        for uid in users:
            try:
                bot.send_message(uid, f"📢 <b>E'LON</b>\n\n{text}")
                sent += 1
                time.sleep(0.1)
            except:
                pass
        bot.reply_to(m, f"✅ {sent}/{len(users)}")
    except:
        bot.reply_to(m, "❌ /broadcast [matn]")

@bot.message_handler(commands=["stats"])
def stats_cmd(m):
    u = db.get(m.from_user.id)
    vip_status = "✅ HA" if u["vip"] else "❌ YO'Q"
    bot.reply_to(m, add_footer(f"📊\n👥{u['invites']} ⭐{format_stars(u['stars'])} 👑{vip_status} 🔥{u['streak']}"))

@bot.message_handler(commands=["daily"])
def daily_cmd(m):
    uid = m.from_user.id
    ok, ns, bonus, streak, extra = db.give_daily_bonus(uid)
    if ok:
        bot.reply_to(m, add_footer(f"🎁 +{bonus}⭐ | Jami: {format_stars(ns)}⭐ | 🔥{streak}"))
    else:
        bot.reply_to(m, "❌ Bugun olgansiz!")

@bot.message_handler(commands=["link"])
def link_cmd(m):
    bot.reply_to(m, f"🔗 <code>{get_invite_link(m.from_user.id)}</code>")

@bot.message_handler(commands=["tasks"])
def tasks_cmd(m):
    show_tasks_menu(m.chat.id, m.from_user.id)

@bot.message_handler(commands=["help"])
def help_cmd(m):
    bot.reply_to(m, f"🤖 {BOT_USERNAME}\n/start /stats /daily /link /tasks /help\n\n👥 2 ta = 1⭐\n🎁 +{DAILY_BONUS}⭐/kun\n📢 {GROUP_LINK}")

# ================= LEADERBOARD (faqat ichki, kanalga yubormaydi) =================
last_top_hash = ""

def get_top_hash():
    top = db.get_top(10)
    return str([(row[2], row[3]) for row in top])

def should_send_leaderboard():
    global last_top_hash
    current_hash = get_top_hash()
    if current_hash != last_top_hash:
        last_top_hash = current_hash
        return True
    return False

def leaderboard_scheduler():
    while True:
        try:
            if should_send_leaderboard():
                top = db.get_top(10)
                if top:
                    text = "🏆 <b>TOP 10 TAKLIFCHILAR</b>\n\n"
                    for i, (u, n, inv, st, v, streak) in enumerate(top, 1):
                        user = f"@{u}" if u else n
                        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}️⃣"
                        vip_mark = "👑" if v else ""
                        text += f"{medal} <b>{user}</b> {vip_mark}\n👥{inv} ⭐{format_stars(st)} 🔥{streak}\n\n"
                    text += f"\n🔥 2 ta = 1⭐ | 🔗 @{BOT_USERNAME}"
                    # KANALGA YUBORISH O'CHIRILDI
                    # Faqat konsolga chiqarish mumkin
                    logger.info("Leaderboard updated, not sent to channels.")
        except Exception as e:
            logger.error(f"Leaderboard: {e}")
        time.sleep(60)

# ================= AVTOMATIK REKLAMA (faqat foydalanuvchilarga) =================
def auto_ad_sender():
    while True:
        try:
            users = db.get_all_users_for_ad()
            gift = random.choice(GIFT_ADS)
            for uid in users:
                if db.can_send_ad(uid, 48):
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🛒 Do'kon", callback_data="shop"), types.InlineKeyboardButton("👥 Guruh", url=GROUP_LINK))
                    try:
                        bot.send_photo(uid, gift['photo'], caption=f"🎁 <b>{gift['name']}</b>\n{gift['desc']}\n\n⭐ Do'kondan oling!\n🔗 @{BOT_USERNAME}", reply_markup=markup)
                        db.update_last_ad(uid)
                    except:
                        pass
                    time.sleep(1)
        except:
            pass
        time.sleep(172800)

# ================= MAIN =================
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 STARS BOT ISHGA TUSHIRILDI")
    print(f"💰 Bonus: {DAILY_BONUS}⭐/kun")
    print(f"👤 Admin: {ADMIN_USERNAME}")
    print("📊 Top: 1 daqiqa | Kanalga yuborish O'CHIRILDI")
    print("✅ Referal obunadan keyin hisoblanadi")
    print("✅ Vazifalar paneli qo'shildi")
    print("=" * 50)

    try:
        requests.get(f"https://api.telegram.org/bot{API_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=5)
        time.sleep(1)
    except:
        pass

    Thread(target=leaderboard_scheduler, daemon=True).start()
    Thread(target=auto_ad_sender, daemon=True).start()

    while True:
        try:
            bot.infinity_polling(timeout=60, skip_pending=True)
        except KeyboardInterrupt:
            print("👋 To'xtadi")
            break
        except Exception as e:
            if "409" in str(e):
                time.sleep(15)
            else:
                time.sleep(5)
