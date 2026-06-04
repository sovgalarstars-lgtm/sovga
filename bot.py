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
from flask import Flask
from threading import Thread as FlaskThread

# ================= CONFIG =================
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "2010030869"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "stars_sovga_gifbot")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@Stars_5_odam_1stars")

if not API_TOKEN:
    print("❌ TOKEN topilmadi!")
    exit(1)

# ================= SOZLAMALAR =================
GROUP_ID = -1002449896845
GROUP_LINK = "https://t.me/Stars_2_odam_1stars"
DAILY_BONUS = 0.25

# ================= REKLAMA VA MOTIVATSIYA =================
ADS_BOT = "@zurnavolarbot"
ADS_MESSAGES = [f"🎵 {ADS_BOT} - Eng zo'r musiqa boti!", f"🔥 {ADS_BOT} - Sevimli qo'shiqlaringiz!", f"🎶 {ADS_BOT} - Musiqa dunyosi!", f"💃 {ADS_BOT} - Raqsga tushing!", f"🎧 {ADS_BOT} - Hit qo'shiqlar!"]
MOTIVATIONS = ["🔥 Siz zo'rsiz! Davom eting!", "💪 Har bir taklif - yulduz sari qadam!", "⭐ Yulduzlar sizni kutmoqda!", "🚀 Oldinga, lider bo'ling!", "👑 Siz eng yaxshisisiz!", "🎯 Maqsad sari intiling!", "💎 Katta sovg'alar kutyapti!", "🌟 Yulduzlar soni oshmoqda!", "🏆 Chempion bo'ling!", "⚡ Kuch sizda!"]
GIFT_ADS = [{"emoji": "❤️", "name": "Pushti Yurakcha", "desc": "Sevgi ramzi!", "photo": "https://i.imgur.com/8Yp9Z2M.jpg"}, {"emoji": "🧸", "name": "Ayiqcha", "desc": "Yoqimli sovg'a!", "photo": "https://i.imgur.com/5f2vL8K.jpg"}, {"emoji": "🌹", "name": "Atirgul", "desc": "Romantik!", "photo": "https://i.imgur.com/7zK9pQm.jpg"}, {"emoji": "🎁", "name": "Sovg'a qutisi", "desc": "Sirli sovg'a!", "photo": "https://i.imgur.com/3vX9pLm.jpg"}]

# ================= BOT INIT =================
bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML", threaded=False)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BOT")

# ================= FLASK SERVER (Render port uchun) =================
app = Flask('')

@app.route('/')
def home():
    return "✅ Bot is running!"

def run_http():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# ================= DATABASE =================
lock = Lock()

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
            CREATE TABLE IF NOT EXISTS forced_channels(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER UNIQUE,
                channel_username TEXT,
                channel_name TEXT,
                channel_url TEXT,
                max_users INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS forced_channel_users(
                channel_id INTEGER,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (channel_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS tasks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                channel_username TEXT,
                channel_name TEXT,
                channel_url TEXT,
                reward REAL DEFAULT 0.25,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_tasks(
                user_id INTEGER,
                task_id INTEGER,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, task_id)
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
            stars = invites / 4.0
            self.cur.execute("UPDATE users SET stars=?, total_earned=? WHERE user_id=?", (stars, stars, uid))
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
            self.cur.execute("SELECT stars FROM users WHERE user_id=?", (uid,))
            row = self.cur.fetchone()
            current_stars = float(row[0] or 0)
            new_stars = current_stars + amount
            self.cur.execute("UPDATE users SET stars=?, total_earned=total_earned+? WHERE user_id=?", (new_stars, amount, uid))
            self.conn.commit()
            return new_stars

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

    def get_all_users_for_ad(self):
        with lock:
            self.cur.execute("SELECT user_id FROM users WHERE is_banned=0")
            return [row[0] for row in self.cur.fetchall()]

    # Majburiy kanallar
    def add_forced_channel(self, channel_id, username, name, url, max_users=0):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO forced_channels(channel_id, channel_username, channel_name, channel_url, max_users) VALUES(?,?,?,?,?)", 
                             (channel_id, username, name, url, max_users))
            self.conn.commit()

    def get_forced_channels(self):
        with lock:
            self.cur.execute("SELECT channel_id, channel_username, channel_name, channel_url, max_users FROM forced_channels")
            return self.cur.fetchall()

    def remove_forced_channel(self, channel_id):
        with lock:
            self.cur.execute("DELETE FROM forced_channels WHERE channel_id=?", (channel_id,))
            self.conn.commit()

    def record_channel_user(self, channel_id, user_id):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO forced_channel_users(channel_id, user_id) VALUES(?,?)", (channel_id, user_id))
            if self.cur.rowcount > 0:
                self.cur.execute("SELECT COUNT(*) FROM forced_channel_users WHERE channel_id=?", (channel_id,))
                count = self.cur.fetchone()[0]
                self.cur.execute("SELECT max_users FROM forced_channels WHERE channel_id=?", (channel_id,))
                row = self.cur.fetchone()
                if row and row[0] > 0 and count >= row[0]:
                    self.cur.execute("DELETE FROM forced_channels WHERE channel_id=?", (channel_id,))
                    self.conn.commit()
                    return True, count
                self.conn.commit()
                return False, count
            self.conn.commit()
            return False, None

    def is_channel_user_recorded(self, channel_id, user_id):
        with lock:
            self.cur.execute("SELECT 1 FROM forced_channel_users WHERE channel_id=? AND user_id=?", (channel_id, user_id))
            return self.cur.fetchone() is not None

    # Vazifalar
    def get_tasks(self):
        with lock:
            self.cur.execute("SELECT id, channel_id, channel_username, channel_name, channel_url, reward FROM tasks")
            return self.cur.fetchall()

    def add_task(self, channel_id, username, name, url, reward=0.25):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO tasks(channel_id, channel_username, channel_name, channel_url, reward) VALUES(?,?,?,?,?)", 
                             (channel_id, username, name, url, reward))
            self.conn.commit()

    def remove_task(self, task_id):
        with lock:
            self.cur.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            self.conn.commit()

    def is_task_completed(self, user_id, task_id):
        with lock:
            self.cur.execute("SELECT 1 FROM user_tasks WHERE user_id=? AND task_id=?", (user_id, task_id))
            return self.cur.fetchone() is not None

    def complete_task(self, user_id, task_id, reward):
        with lock:
            if self.is_task_completed(user_id, task_id):
                return False
            self.cur.execute("INSERT INTO user_tasks(user_id, task_id) VALUES(?,?)", (user_id, task_id))
            self.cur.execute("UPDATE users SET stars = stars + ?, total_earned = total_earned + ? WHERE user_id=?", (reward, reward, user_id))
            self.conn.commit()
            return True

    def get_user_completed_tasks(self, user_id):
        with lock:
            self.cur.execute("SELECT task_id FROM user_tasks WHERE user_id=?", (user_id,))
            return [row[0] for row in self.cur.fetchall()]

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
            self.cur.execute("SELECT COUNT(*) FROM users"); s["users"] = self.cur.fetchone()[0]
            self.cur.execute("SELECT SUM(invites) FROM users"); s["invites"] = self.cur.fetchone()[0] or 0
            self.cur.execute("SELECT SUM(stars) FROM users"); s["stars"] = float(self.cur.fetchone()[0] or 0)
            self.cur.execute("SELECT COUNT(*) FROM users WHERE vip=1"); s["vip"] = self.cur.fetchone()[0]
            self.cur.execute("SELECT SUM(total_spent) FROM users"); s["spent"] = float(self.cur.fetchone()[0] or 0)
            self.cur.execute("SELECT COUNT(*) FROM invite_history"); s["total_invites"] = self.cur.fetchone()[0]
            self.cur.execute("SELECT COUNT(*) FROM purchase_history"); s["purchases"] = self.cur.fetchone()[0]
            return s

db = DB()

# ================= SHOP =================
SHOP = {
    1: {"price": 15, "name": "❤️ Pushti Yurakcha", "emoji": "❤️", "photo": "https://i.imgur.com/8Yp9Z2M.jpg", "desc": "Chiroyli pushti yurak sovg'asi"},
    2: {"price": 15, "name": "🧸 Ayiqcha", "emoji": "🧸", "photo": "https://i.imgur.com/5f2vL8K.jpg", "desc": "Yoqimli ayiqcha sovg'a"},
    3: {"price": 25, "name": "🌹 Atirgul", "emoji": "🌹", "photo": "https://i.imgur.com/7zK9pQm.jpg", "desc": "Romantik atirgul"},
    4: {"price": 25, "name": "🎁 Sovg'a qutisi", "emoji": "🎁", "photo": "https://i.imgur.com/3vX9pLm.jpg", "desc": "Sirli sovg'a qutisi"},
    5: {"price": 50, "name": "🎂 Tort", "emoji": "🎂", "photo": "https://i.imgur.com/9pL2mNx.jpg", "desc": "Shirin tort + VIP"},
    6: {"price": 50, "name": "💐 Gullar", "emoji": "💐", "photo": "https://i.imgur.com/XkP5vRt.jpg", "desc": "Chiroyli guldasta + VIP"},
    7: {"price": 100, "name": "🏆 Oltin kubok", "emoji": "🏆", "photo": "https://i.imgur.com/vL9pQmN.jpg", "desc": "Oltin sovg'a + VIP"},
    8: {"price": 100, "name": "💍 Olmos uzuk", "emoji": "💍", "photo": "https://i.imgur.com/kP8mNxZ.jpg", "desc": "Brilliant uzuk + VIP"},
    9: {"price": 200, "name": "💎 Brilliant", "emoji": "💎", "photo": "https://i.imgur.com/kP8mNxZ.jpg", "desc": "Qimmatbaho brilliant + VIP"},
    10: {"price": 500, "name": "👑 Qirol toji", "emoji": "👑", "photo": "https://i.imgur.com/XkP5vRt.jpg", "desc": "Haqiqiy toj + VIP"},
}

# ================= YORDAMCHI FUNKSIYALAR =================
def check_sub(uid):
    channels = db.get_forced_channels()
    not_sub = []
    for ch_id, username, name, url, max_users in channels:
        try:
            member = bot.get_chat_member(ch_id, uid)
            if member.status in ['member', 'administrator', 'creator']:
                removed, count = db.record_channel_user(ch_id, uid)
                if removed:
                    try:
                        bot.send_message(ADMIN_ID, f"⚠️ Kanal {name} ({ch_id}) {count} foydalanuvchiga yetdi va majburiy ro'yxatdan olib tashlandi!")
                    except:
                        pass
            else:
                not_sub.append({"id": ch_id, "username": username, "name": name, "url": url})
        except Exception as e:
            # Agar tekshirib bo'lmasa (bot admin emas yoki API xato), obuna bo'lmagan deb hisoblaymiz
            logger.error(f"Kanal tekshiruvi xatosi {ch_id}: {e}")
            # Adminni ogohlantiramiz (faqat bir marta, har bir chaqiruvda emas? Buning uchun alohida mexanizm kerak, hozircha oddiy)
            try:
                bot.send_message(ADMIN_ID, f"❌ Bot kanalda admin emas yoki get_chat_member ishlamayapti: {name} ({ch_id})\nIltimos, botni kanalga admin qiling!")
            except:
                pass
            # Xavfsizlik uchun obuna bo'lmagan deb hisoblaymiz (majburiy talab)
            not_sub.append({"id": ch_id, "username": username, "name": name, "url": url})
    return not_sub

def add_footer(text):
    ad = random.choice(ADS_MESSAGES)
    mot = random.choice(MOTIVATIONS)
    return f"{text}\n\n{'─' * 20}\n💡 <i>{mot}</i>\n{ad}"

def format_stars(stars):
    return str(int(stars)) if stars == int(stars) else f"{stars:.2f}"

def get_invite_link(uid):
    return f"https://t.me/{BOT_USERNAME}?start={uid}"

# ================= TOP O'ZGARISHI =================
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

# ================= START =================
@bot.message_handler(commands=["start"])
def start(m):
    uid = m.from_user.id
    if db.check_ban(uid):
        return bot.send_message(m.chat.id, "❌ Bloklangansiz!")
    if m.text and len(m.text.split()) > 1:
        try:
            ref = int(m.text.split()[1])
            if ref != uid and not db.check_duplicate(ref, uid):
                db.create_user(ref, None, "User")
                db.add_history(ref, uid, m.from_user.first_name, "link")
                db.add_invite(ref)
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
    u = db.get(uid)
    vip_status = "✅ HA" if u["vip"] else "❌ YO'Q"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🛒 DO'KON", callback_data="shop"), types.InlineKeyboardButton(f"🎁 +{DAILY_BONUS}⭐", callback_data="daily"))
    markup.add(types.InlineKeyboardButton("🏆 TOP", callback_data="top"), types.InlineKeyboardButton("📊 PROFIL", callback_data="profile"))
    markup.add(types.InlineKeyboardButton("🔗 LINK", callback_data="link"), types.InlineKeyboardButton("📜 XARIDLAR", callback_data="purchases"))
    markup.add(types.InlineKeyboardButton("✅ VAZIFALAR", callback_data="tasks"))
    text = f"🌟 <b>STARS BOT</b>\n\n👤 <b>{m.from_user.first_name}</b>\n👥 Takliflar: <b>{u['invites']}</b> (4 ta = 1⭐)\n⭐ Yulduzlar: <b>{format_stars(u['stars'])}</b>\n👑 VIP: <b>{vip_status}</b>\n🔥 Streak: {u['streak']} kun\n\n🎯 <i>4 ta taklif = 1⭐</i>"
    bot.send_message(m.chat.id, add_footer(text), reply_markup=markup)

# ================= GURUHGA QO'SHISH =================
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
        if db.check_duplicate(inviter_id, invited_id):
            continue
        db.create_user(inviter_id, message.from_user.username, message.from_user.first_name)
        db.create_user(invited_id, member.username, member.first_name)
        db.add_history(inviter_id, invited_id, member.first_name, "group")
        db.add_invite(inviter_id)
    try:
        bot.send_message(message.chat.id, f"✅ {len(message.new_chat_members)} ta yangi a'zo qo'shildi!")
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
        for item_id, item in SHOP.items():
            can = "✅" if u["stars"] >= item["price"] else "🔒"
            markup.add(types.InlineKeyboardButton(f"{can} {item['emoji']} {item['name']} {item['price']}⭐", callback_data=f"buy_{item_id}"))
        bot.send_message(call.message.chat.id, add_footer(f"🛒 DO'KON\n\n⭐ Balans: {format_stars(u['stars'])}"), reply_markup=markup)
    elif data == "top":
        top = db.get_top(10)
        if top:
            text = "🏆 TOP 10 (takliflar bo'yicha)\n\n"
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
        text = f"📊 PROFIL\n\n👤 {call.from_user.first_name}\n🆔 <code>{uid}</code>\n👑 VIP: {vip_status}\n🔥 Streak: {u['streak']} kun\n👥 Takliflar: {u['invites']} (4 ta = 1⭐)\n⭐ Yulduzlar: {format_stars(u['stars'])}\n💎 Topgan: {format_stars(u['earned'])}⭐\n💸 Sarflangan: {format_stars(u['spent'])}⭐"
        bot.send_message(call.message.chat.id, add_footer(text))
    elif data == "link":
        bot.send_message(call.message.chat.id, add_footer(f"🔗 <code>{get_invite_link(uid)}</code>\n\n📢 {GROUP_LINK}"))
    elif data == "purchases":
        purchases = db.get_purchase_history(uid)
        if purchases:
            text = "📜 XARIDLAR\n\n" + "\n".join(f"{emoji} {name} - {format_stars(price)}⭐" for name, emoji, price, dt in purchases)
        else:
            text = "❌ Hali xarid yo'q!"
        bot.send_message(call.message.chat.id, add_footer(text))
    elif data == "tasks":
        tasks = db.get_tasks()
        completed = db.get_user_completed_tasks(uid)
        if not tasks:
            bot.send_message(call.message.chat.id, "❌ Hozircha vazifalar yo'q.")
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        for tid, ch_id, username, name, url, reward in tasks:
            if tid in completed:
                markup.add(types.InlineKeyboardButton(f"✅ {name} (bajarilgan)", callback_data=f"task_{tid}_done"))
            else:
                markup.add(types.InlineKeyboardButton(f"📢 {name} (+{reward}⭐)", url=url))
        markup.add(types.InlineKeyboardButton("🔙 ORQA", callback_data="back_to_menu"))
        bot.send_message(call.message.chat.id, "✅ VAZIFALAR\n\nKanalga obuna bo'ling, so'ng 'Tekshirish' tugmasini bosing.", reply_markup=markup)
    elif data.startswith("task_"):
        parts = data.split("_")
        if len(parts) == 3 and parts[2] == "check":
            task_id = int(parts[1])
            tasks = db.get_tasks()
            task = next((t for t in tasks if t[0] == task_id), None)
            if not task:
                bot.answer_callback_query(call.id, "❌ Vazifa topilmadi!")
                return
            tid, ch_id, username, name, url, reward = task
            try:
                member = bot.get_chat_member(ch_id, uid)
                if member.status in ['member', 'administrator', 'creator']:
                    if db.complete_task(uid, tid, reward):
                        bot.answer_callback_query(call.id, f"✅ +{reward}⭐ yulduz berildi!", show_alert=True)
                        callback_data = "tasks"
                        callback(call)
                    else:
                        bot.answer_callback_query(call.id, "❌ Siz bu vazifani avval bajargan-siz!", show_alert=True)
                else:
                    bot.answer_callback_query(call.id, f"❌ {name} kanaliga obuna bo'lmagansiz!", show_alert=True)
            except Exception as e:
                logger.warning(f"Task tekshiruvi xatosi {ch_id}: {e}")
                # Tekshirib bo'lmasa, obuna bo'lmagan deb hisoblaymiz
                bot.answer_callback_query(call.id, f"❌ Kanalga obuna bo'lmagansiz yoki bot admin emas!", show_alert=True)
        return
    elif data == "back_to_menu":
        start(call.message)
        return
    elif data.startswith("buy_"):
        item_id = int(data.split("_")[1])
        item = SHOP.get(item_id)
        if not item:
            bot.answer_callback_query(call.id, "❌ Mahsulot topilmadi!")
            return
        u = db.get(uid)
        price = item["price"]
        if u["stars"] < price:
            bot.answer_callback_query(call.id, f"❌ {format_stars(price - u['stars'])}⭐ yetmaydi!", show_alert=True)
        else:
            ns = db.sub_star(uid, price)
            db.add_purchase_history(uid, item['name'], item['emoji'], price)
            extra = "\n👑 VIP BERILDI!" if price >= 50 and not u["vip"] else ""
            if price >= 50:
                db.grant_vip(uid)
            admin_link = f"tg://user?id={ADMIN_ID}"
            caption = f"✅ SOVG'A BERILDI!\n\n{item['emoji']} {item['name']}\n{item['desc']}\n\n💰 Sarflandi: {price}⭐\n⭐ Qoldi: {format_stars(ns)}{extra}\n\n{'─'*20}\n📦 HAQIQIY SOVG'A:\n👤 <a href='{admin_link}'>{ADMIN_USERNAME}</a>\n⏳ Admin yuboradi\n📞 <a href='{admin_link}'>BOG'LANISH</a>"
            bot.send_photo(call.message.chat.id, item['photo'], caption=add_footer(caption))
            bot.answer_callback_query(call.id, "✅ Berildi!", show_alert=True)
            try:
                bot.send_message(GROUP_ID, f"🛍 {call.from_user.first_name} {item['emoji']} {item['name']} ({price}⭐)")
            except:
                pass
            try:
                bot.send_message(ADMIN_ID, f"🛍 {call.from_user.first_name}\n🆔 <code>{uid}</code>\n🎁 {item['name']}\n💰 {price}⭐\n📞 <a href='tg://user?id={uid}'>BOG'LANISH</a>")
            except:
                pass
    bot.answer_callback_query(call.id)

# ================= ADMIN BUYRUG'LARI =================
@bot.message_handler(commands=["admin"])
def admin_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    s = db.get_stats()
    text = f"🔐 ADMIN PANEL\n\n👥 Foydalanuvchilar: {s['users']}\n📊 Jami takliflar: {s['total_invites']}\n⭐ Yulduzlar: {format_stars(s['stars'])}\n👑 VIP: {s['vip']}\n💸 Sarflangan: {format_stars(s['spent'])}\n🛍 Xaridlar: {s['purchases']}\n\nBuyruqlar:\n/addstars /ban /unban /search /broadcast /send\n/addchannel /removechannel /channellist\n/addtask /removetask /tasklist"
    bot.send_message(m.chat.id, text)

@bot.message_handler(commands=["addchannel"])
def add_channel_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        parts = m.text.split(maxsplit=5)
        if len(parts) < 5:
            bot.reply_to(m, "❌ /addchannel [chat_id] [username] [name] [url] [limit (ixtiyoriy)]\nMasalan: /addchannel -100123456789 @kanal Kanal https://t.me/kanal 1000")
            return
        ch_id = int(parts[1])
        username = parts[2]
        name = parts[3]
        url = parts[4]
        max_users = int(parts[5]) if len(parts) > 5 else 0
        db.add_forced_channel(ch_id, username, name, url, max_users)
        bot.reply_to(m, f"✅ Kanal qo'shildi: {name} (limit: {max_users if max_users>0 else 'cheksiz'})")
    except Exception as e:
        bot.reply_to(m, f"❌ Xato: {e}")

@bot.message_handler(commands=["removechannel"])
def remove_channel_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        ch_id = int(m.text.split()[1])
        db.remove_forced_channel(ch_id)
        bot.reply_to(m, f"✅ Kanal olib tashlandi: {ch_id}")
    except:
        bot.reply_to(m, "❌ /removechannel [chat_id]")

@bot.message_handler(commands=["channellist"])
def channel_list_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    channels = db.get_forced_channels()
    if channels:
        text = "📢 Majburiy kanallar:\n"
        for ch_id, username, name, url, max_users in channels:
            db.cur.execute("SELECT COUNT(*) FROM forced_channel_users WHERE channel_id=?", (ch_id,))
            current = db.cur.fetchone()[0]
            limit_str = f"{current}/{max_users}" if max_users>0 else f"{current}/cheksiz"
            text += f"🆔 {ch_id} | {name} | {username} | {limit_str}\n"
        bot.reply_to(m, text)
    else:
        bot.reply_to(m, "❌ Hech qanday majburiy kanal yo'q.")

@bot.message_handler(commands=["addtask"])
def add_task_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        parts = m.text.split(maxsplit=5)
        if len(parts) < 5:
            bot.reply_to(m, "❌ /addtask [chat_id] [username] [name] [url] [reward (ixtiyoriy)]\nMasalan: /addtask -100123 @kanal Kanal https://t.me/kanal 0.25")
            return
        ch_id = int(parts[1])
        username = parts[2]
        name = parts[3]
        url = parts[4]
        reward = float(parts[5]) if len(parts) > 5 else 0.25
        db.add_task(ch_id, username, name, url, reward)
        bot.reply_to(m, f"✅ Vazifa qo'shildi: {name} (+{reward}⭐)")
    except Exception as e:
        bot.reply_to(m, f"❌ Xato: {e}")

@bot.message_handler(commands=["removetask"])
def remove_task_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        task_id = int(m.text.split()[1])
        db.remove_task(task_id)
        bot.reply_to(m, f"✅ Vazifa olib tashlandi: {task_id}")
    except:
        bot.reply_to(m, "❌ /removetask [task_id]")

@bot.message_handler(commands=["tasklist"])
def task_list_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    tasks = db.get_tasks()
    if tasks:
        text = "📋 Vazifalar:\n" + "\n".join(f"🆔 {tid} | {name} | +{reward}⭐" for tid, ch_id, username, name, url, reward in tasks)
        bot.reply_to(m, text)
    else:
        bot.reply_to(m, "❌ Hech qanday vazifa yo'q.")

@bot.message_handler(commands=["addstars"])
def addstars_cmd(m):
    if m.from_user.id != ADMIN_ID: return
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
    if m.from_user.id != ADMIN_ID: return
    try:
        parts = m.text.split(maxsplit=2)
        uid, text = int(parts[1]), parts[2]
        bot.send_message(uid, f"📩 ADMIN:\n\n{text}")
        bot.reply_to(m, f"✅ {uid} ga yuborildi!")
    except:
        bot.reply_to(m, "❌ /send [id] [matn]")

@bot.message_handler(commands=["ban"])
def ban_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        db.ban_user(int(m.text.split()[1]))
        bot.reply_to(m, "✅ Ban!")
    except:
        bot.reply_to(m, "❌ /ban [id]")

@bot.message_handler(commands=["unban"])
def unban_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        db.unban_user(int(m.text.split()[1]))
        bot.reply_to(m, "✅ Unban!")
    except:
        bot.reply_to(m, "❌ /unban [id]")

@bot.message_handler(commands=["search"])
def search_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        query = m.text.split(maxsplit=1)[1]
        results = db.search_user(query)
        if results:
            text = "🔍 Natijalar:\n" + "\n".join(f"🆔{uid} {user} {'👑' if vip else ''} 👥{inv} ⭐{format_stars(st)}" for uid, un, nm, inv, st, vip, streak in results[:10])
            bot.reply_to(m, text)
        else:
            bot.reply_to(m, "❌ Topilmadi!")
    except:
        bot.reply_to(m, "❌ /search [id/username]")

@bot.message_handler(commands=["broadcast"])
def broadcast_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        text = m.text.split(maxsplit=1)[1]
        users = db.get_all_users_for_ad()
        sent = 0
        for uid in users:
            try:
                bot.send_message(uid, f"📢 E'LON\n\n{text}")
                sent += 1
                time.sleep(0.1)
            except:
                pass
        bot.reply_to(m, f"✅ {sent}/{len(users)}")
    except:
        bot.reply_to(m, "❌ /broadcast [matn]")

# ================= FOYDALANUVCHI BUYRUG'LARI =================
@bot.message_handler(commands=["stats"])
def stats_cmd(m):
    u = db.get(m.from_user.id)
    bot.reply_to(m, add_footer(f"📊 Sizning statistikangiz:\n👥 Takliflar: {u['invites']}\n⭐ Yulduzlar: {format_stars(u['stars'])}\n👑 VIP: {'HA' if u['vip'] else 'YO\'Q'}\n🔥 Streak: {u['streak']} kun"))

@bot.message_handler(commands=["daily"])
def daily_cmd(m):
    ok, ns, bonus, streak, extra = db.give_daily_bonus(m.from_user.id)
    bot.reply_to(m, add_footer(f"🎁 +{bonus}⭐ | Jami: {format_stars(ns)}⭐ | 🔥 Streak: {streak}") if ok else "❌ Bugun kunlik bonusni olgansiz!")

@bot.message_handler(commands=["link"])
def link_cmd(m):
    bot.reply_to(m, f"🔗 Taklif linkingiz:\n<code>{get_invite_link(m.from_user.id)}</code>")

@bot.message_handler(commands=["tasks"])
def tasks_cmd(m):
    tasks = db.get_tasks()
    completed = db.get_user_completed_tasks(m.from_user.id)
    if not tasks:
        bot.reply_to(m, "❌ Hozircha vazifalar yo'q.")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    for tid, ch_id, username, name, url, reward in tasks:
        if tid in completed:
            markup.add(types.InlineKeyboardButton(f"✅ {name} (bajarilgan)", callback_data=f"task_{tid}_done"))
        else:
            markup.add(types.InlineKeyboardButton(f"📢 {name} (+{reward}⭐)", url=url))
    bot.reply_to(m, "✅ Vazifalar:\nKanalga obuna bo'ling, so'ng 'Tekshirish' tugmasini bosing.", reply_markup=markup)

@bot.message_handler(commands=["help"])
def help_cmd(m):
    bot.reply_to(m, f"🤖 Yordam\n\n/start - Boshlash\n/stats - Statistika\n/daily - Kunlik bonus\n/link - Taklif linki\n/tasks - Vazifalar\n/help - Yordam\n\n📢 Guruh: {GROUP_LINK}\n🎁 4 ta taklif = 1⭐\n🎁 Kunlik bonus: +{DAILY_BONUS}⭐")

# ================= LEADERBOARD SCHEDULER =================
def leaderboard_scheduler():
    empty_count = 0
    while True:
        try:
            if should_send_leaderboard():
                top = db.get_top(10)
                if top:
                    text = "🏆 TOP 10 TAKLIFCHILAR\n\n"
                    for i, (u, n, inv, st, v, streak) in enumerate(top, 1):
                        user = f"@{u}" if u else n
                        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}️⃣"
                        text += f"{medal} <b>{user}</b> {'👑' if v else ''}\n👥{inv} ⭐{format_stars(st)} 🔥{streak}\n\n"
                    text += f"\n🔥 4 ta taklif = 1⭐ | 🔗 @{BOT_USERNAME}"
                    for ch_id, username, name, url, _ in db.get_forced_channels():
                        try: bot.send_message(ch_id, text)
                        except: pass
                    empty_count = 0
            else:
                empty_count += 1
                if empty_count >= 60:
                    top = db.get_top(10)
                    if top:
                        text = "🏆 TOP 10 (avtomatik)\n\n" + "\n".join(f"{'🥇' if i==1 else '🥈' if i==2 else '🥉' if i==3 else f'{i}️⃣'} <b>{'@'+u if u else n}</b> {'👑' if v else ''}\n👥{inv} ⭐{format_stars(st)}" for i, (u, n, inv, st, v, streak) in enumerate(top, 1)) + f"\n\n🔗 @{BOT_USERNAME}"
                        for ch_id, username, name, url, _ in db.get_forced_channels():
                            try: bot.send_message(ch_id, text)
                            except: pass
                    empty_count = 0
        except Exception as e:
            logger.error(f"Leaderboard: {e}")
        time.sleep(60)

# ================= AVTOMATIK REKLAMA =================
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
                        bot.send_photo(uid, gift['photo'], caption=f"🎁 {gift['name']}\n{gift['desc']}\n\n⭐ Do'kondan oling!\n🔗 @{BOT_USERNAME}", reply_markup=markup)
                        db.update_last_ad(uid)
                    except:
                        pass
                    time.sleep(0.5)
        except:
            pass
        time.sleep(172800)

# ================= MAIN =================
if __name__ == "__main__":
    print("="*50)
    print("🚀 STARS BOT ISHGA TUSHIRILDI")
    print(f"💰 Kunlik bonus: {DAILY_BONUS}⭐")
    print(f"👤 Admin: {ADMIN_USERNAME}")
    print("📊 Taklif tizimi: 4 ta = 1⭐")
    print("📢 Majburiy kanallar limit bilan boshqariladi")
    print("🌐 HTTP server port uchun ishga tushiriladi")
    print("="*50)
    
    # Flask serverini alohida threadda ishga tushirish
    FlaskThread(target=run_http, daemon=True).start()
    
    # Webhook o‘chirish
    try:
        requests.get(f"https://api.telegram.org/bot{API_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=5)
        time.sleep(1)
    except:
        pass
    
    # Scheduler va ad sender threadlari
    Thread(target=leaderboard_scheduler, daemon=True).start()
    Thread(target=auto_ad_sender, daemon=True).start()
    
    # Bot polling
    while True:
        try:
            bot.infinity_polling(timeout=60, skip_pending=True)
        except KeyboardInterrupt:
            print("👋 Bot to'xtatildi")
            break
        except Exception as e:
            if "409" in str(e):
                print("⚠️ Conflict, qayta ulanish...")
                time.sleep(15)
            else:
                print(f"❌ Xato: {e}")
                time.sleep(5)
