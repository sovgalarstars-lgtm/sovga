import telebot
import sqlite3
import logging
import os
import time
import random
import requests
from flask import Flask
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

if not API_TOKEN:
    print("❌ TOKEN topilmadi!")
    exit(1)

# ================= SOZLAMALAR =================
GROUP_ID = -1002449896845  # Guruh ID (takliflar uchun)
GROUP_LINK = "https://t.me/Stars_2_odam_1stars"
DAILY_BONUS = 0.25

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

# ================= BOT INIT =================
bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML", threaded=False)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BOT")

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

            -- Majburiy kanallar (admin boshqaradi)
            CREATE TABLE IF NOT EXISTS forced_channels(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                channel_username TEXT,
                channel_name TEXT,
                channel_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Vazifalar (zadaniya) - kanalga obuna bo'lish
            CREATE TABLE IF NOT EXISTS tasks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                channel_username TEXT,
                channel_name TEXT,
                channel_url TEXT,
                reward REAL DEFAULT 0.25,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Foydalanuvchining bajargan vazifalari
            CREATE TABLE IF NOT EXISTS user_tasks(
                user_id INTEGER,
                task_id INTEGER,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, task_id)
            );
            """)
            self.conn.commit()

            # Agar forced_channels bo'sh bo'lsa, default kanallarni qo'shish
            self.cur.execute("SELECT COUNT(*) FROM forced_channels")
            if self.cur.fetchone()[0] == 0:
                default_channels = [
                    (-1003737363661, "@Tekin_stars_yulduz", "📢 KANAL", "https://t.me/Tekin_stars_yulduz"),
                    (-1002449896845, "@Stars_2_odam_1stars", "👥 GURUH", "https://t.me/Stars_2_odam_1stars")
                ]
                for ch_id, username, name, url in default_channels:
                    self.cur.execute("INSERT OR IGNORE INTO forced_channels(channel_id, channel_username, channel_name, channel_url) VALUES(?,?,?,?)",
                                     (ch_id, username, name, url))
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

    # ============= Majburiy kanallar =============
    def get_forced_channels(self):
        with lock:
            self.cur.execute("SELECT channel_id, channel_username, channel_name, channel_url FROM forced_channels")
            return self.cur.fetchall()

    def add_forced_channel(self, channel_id, username, name, url):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO forced_channels(channel_id, channel_username, channel_name, channel_url) VALUES(?,?,?,?)",
                             (channel_id, username, name, url))
            self.conn.commit()

    def remove_forced_channel(self, channel_id):
        with lock:
            self.cur.execute("DELETE FROM forced_channels WHERE channel_id=?", (channel_id,))
            self.conn.commit()

    # ============= Vazifalar =============
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
    """Majburiy kanallarga obuna tekshiruvi. Bot tekshira olmasa -> obuna bo'lgan deb hisoblanadi."""
    channels = db.get_forced_channels()
    not_sub = []
    for ch_id, username, name, url in channels:
        try:
            member = bot.get_chat_member(ch_id, uid)
            if member.status not in ['member', 'administrator', 'creator']:
                not_sub.append({"id": ch_id, "username": username, "name": name, "url": url})
        except Exception as e:
            logger.warning(f"Tekshirib bo'lmadi {ch_id}: {e}")
            continue
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

# ================= TOP O'ZGARISHINI TEKSHIRISH =================
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
    
    # Referal (taklif linki)
    if m.text and len(m.text.split()) > 1:
        try:
            ref = int(m.text.split()[1])
            if ref != uid and not db.check_duplicate(ref, uid):
                db.create_user(ref, None, "User")
                db.add_history(ref, uid, m.from_user.first_name, "link")
                db.add_invite(ref)
        except:
            pass
    
    # Majburiy obuna tekshiruvi
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
    
    text = f"""
🌟 <b>STARS BOT</b>

👤 <b>{m.from_user.first_name}</b>
👥 Takliflar: <b>{u['invites']}</b> (4 ta = 1⭐)
⭐ Yulduzlar: <b>{format_stars(u['stars'])}</b>
👑 VIP: <b>{vip_status}</b>
🔥 Streak: {u['streak']} kun

🎯 <i>4 ta taklif = 1⭐</i>
"""
    bot.send_message(m.chat.id, add_footer(text), reply_markup=markup)

# ================= GURUHGA QO'SHISH (SHAXSIY XABAR YO'Q) =================
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
        bot.send_message(message.chat.id, f"✅ {len(message.new_chat_members)} ta yangi a'zo qo'shildi! Top o'zgarsa ko'rsatiladi.")
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
        text = f"🛒 <b>DO'KON</b>\n\n⭐ Balans: <b>{format_stars(u['stars'])}</b>"
        bot.send_message(call.message.chat.id, add_footer(text), reply_markup=markup)
    
    elif data == "top":
        top = db.get_top(10)
        if top:
            text = "🏆 <b>TOP 10 (takliflar bo'yicha)</b>\n\n"
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
👥 Takliflar: <b>{u['invites']}</b> (4 ta = 1⭐)
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
        tasks = db.get_tasks()
        completed = db.get_user_completed_tasks(uid)
        if not tasks:
            bot.send_message(call.message.chat.id, "❌ Hozircha vazifalar yo'q.")
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for tid, ch_id, username, name, url, reward in tasks:
            if tid in completed:
                markup.add(types.InlineKeyboardButton(f"✅ {name} (bajarilgan)", callback_data=f"task_{tid}_done"))
            else:
                markup.add(types.InlineKeyboardButton(f"📢 {name} (+{reward}⭐)", url=url))
        # Har bir vazifa uchun tekshirish tugmasi
        markup2 = types.InlineKeyboardMarkup(row_width=2)
        for tid, ch_id, username, name, url, reward in tasks:
            if tid not in completed:
                markup2.add(types.InlineKeyboardButton(f"🔍 {name}", callback_data=f"task_{tid}_check"))
        if markup2.keyboard:
            bot.send_message(call.message.chat.id, "✅ Vazifalar: Kanalga obuna bo'ling, so'ng 'Tekshirish' tugmasini bosing.", reply_markup=markup2)
        else:
            bot.send_message(call.message.chat.id, "✅ Barcha vazifalarni bajargan-siz!")
    
    elif data.startswith("task_"):
        parts = data.split("_")
        if len(parts) == 3 and parts[2] == "check":
            task_id = int(parts[1])
            tasks = db.get_tasks()
            task = None
            for t in tasks:
                if t[0] == task_id:
                    task = t
                    break
            if not task:
                bot.answer_callback_query(call.id, "❌ Vazifa topilmadi!")
                return
            tid, ch_id, username, name, url, reward = task
            try:
                member = bot.get_chat_member(ch_id, uid)
                if member.status in ['member', 'administrator', 'creator']:
                    if db.complete_task(uid, tid, reward):
                        bot.answer_callback_query(call.id, f"✅ +{reward}⭐ yulduz berildi!", show_alert=True)
                        callback(call)  # yangilash uchun
                    else:
                        bot.answer_callback_query(call.id, "❌ Siz bu vazifani avval bajargan-siz!", show_alert=True)
                else:
                    bot.answer_callback_query(call.id, f"❌ {name} kanaliga obuna bo'lmagansiz!", show_alert=True)
            except Exception as e:
                logger.warning(f"Task tekshiruvi xatosi {ch_id}: {e}")
                if db.complete_task(uid, tid, reward):
                    bot.answer_callback_query(call.id, f"✅ +{reward}⭐ (tekshirib bo'lmadi, hisoblandi)", show_alert=True)
                    callback(call)
                else:
                    bot.answer_callback_query(call.id, "❌ Xatolik yoki avval bajarilgan!", show_alert=True)
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
    if m.from_user.id != ADMIN_ID:
        return
    s = db.get_stats()
    text = f"🔐 <b>ADMIN PANEL</b>\n\n👥 Foydalanuvchilar: {s['users']}\n📊 Jami takliflar: {s['total_invites']}\n⭐ Muomaladagi yulduzlar: {format_stars(s['stars'])}\n👑 VIP: {s['vip']}\n💸 Sarflangan: {format_stars(s['spent'])}\n🛍 Xaridlar: {s['purchases']}\n\n<b>Buyruqlar:</b>\n/addstars /ban /unban /search /broadcast /send\n/addchannel /removechannel /channellist\n/addtask /removetask /tasklist"
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
            text = "🔍 Natijalar:\n"
            for uid, un, nm, inv, st, vip, streak in results[:10]:
                user = f"@{un}" if un else nm
                text += f"🆔{uid} {user} {'👑' if vip else ''} 👥{inv} ⭐{format_stars(st)} 🔥{streak}\n"
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

# ============= MAJBURIY KANALLAR (ADMIN) =============
@bot.message_handler(commands=["addchannel"])
def add_channel_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        parts = m.text.split(maxsplit=4)
        if len(parts) < 5:
            bot.reply_to(m, "❌ /addchannel [chat_id] [username] [name] [url]\nMasalan: /addchannel -100123456789 @kanal Kanal https://t.me/kanal")
            return
        ch_id = int(parts[1])
        username = parts[2]
        name = parts[3]
        url = parts[4]
        db.add_forced_channel(ch_id, username, name, url)
        bot.reply_to(m, f"✅ Kanal qo'shildi: {name}")
    except Exception as e:
        bot.reply_to(m, f"❌ Xato: {e}")

@bot.message_handler(commands=["removechannel"])
def remove_channel_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        ch_id = int(m.text.split()[1])
        db.remove_forced_channel(ch_id)
        bot.reply_to(m, f"✅ Kanal olib tashlandi: {ch_id}")
    except:
        bot.reply_to(m, "❌ /removechannel [chat_id]")

@bot.message_handler(commands=["channellist"])
def channel_list_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    channels = db.get_forced_channels()
    if channels:
        text = "📢 <b>Majburiy kanallar:</b>\n"
        for ch_id, username, name, url in channels:
            text += f"🆔 {ch_id} | {name} | {username}\n"
        bot.reply_to(m, text)
    else:
        bot.reply_to(m, "❌ Hech qanday majburiy kanal yo'q.")

# ============= VAZIFALAR (ZADANIYA) ADMIN =============
@bot.message_handler(commands=["addtask"])
def add_task_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        parts = m.text.split(maxsplit=5)
        if len(parts) < 5:
            bot.reply_to(m, "❌ /addtask [chat_id] [username] [name] [url] [reward (ixtiyoriy)]\nMasalan: /addtask -100123456789 @kanal Kanal https://t.me/kanal 0.25")
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
    if m.from_user.id != ADMIN_ID:
        return
    try:
        task_id = int(m.text.split()[1])
        db.remove_task(task_id)
        bot.reply_to(m, f"✅ Vazifa olib tashlandi: {task_id}")
    except:
        bot.reply_to(m, "❌ /removetask [task_id]")

@bot.message_handler(commands=["tasklist"])
def task_list_cmd(m):
    if m.from_user.id != ADMIN_ID:
        return
    tasks = db.get_tasks()
    if tasks:
        text = "📋 <b>Vazifalar:</b>\n"
        for tid, ch_id, username, name, url, reward in tasks:
            text += f"🆔 {tid} | {name} | +{reward}⭐\n"
        bot.reply_to(m, text)
    else:
        bot.reply_to(m, "❌ Hech qanday vazifa yo'q.")

# ================= FOYDALANUVCHI BUYRUG'LARI =================
@bot.message_handler(commands=["stats"])
def stats_cmd(m):
    u = db.get(m.from_user.id)
    vip_status = "✅ HA" if u["vip"] else "❌ YO'Q"
    bot.reply_to(m, add_footer(f"📊 Sizning statistikangiz:\n👥 Takliflar: {u['invites']}\n⭐ Yulduzlar: {format_stars(u['stars'])}\n👑 VIP: {vip_status}\n🔥 Streak: {u['streak']} kun"))

@bot.message_handler(commands=["daily"])
def daily_cmd(m):
    uid = m.from_user.id
    ok, ns, bonus, streak, extra = db.give_daily_bonus(uid)
    if ok:
        bot.reply_to(m, add_footer(f"🎁 +{bonus}⭐ | Jami: {format_stars(ns)}⭐ | 🔥 Streak: {streak}"))
    else:
        bot.reply_to(m, "❌ Bugun kunlik bonusni olgansiz!")

@bot.message_handler(commands=["link"])
def link_cmd(m):
    bot.reply_to(m, f"🔗 Taklif linkingiz:\n<code>{get_invite_link(m.from_user.id)}</code>")

@bot.message_handler(commands=["help"])
def help_cmd(m):
    bot.reply_to(m, f"🤖 <b>Yordam</b>\n\n/start - Botni boshlash\n/stats - Statistika\n/daily - Kunlik bonus\n/link - Taklif linki\n/tasks - Vazifalar\n/help - Yordam\n\n📢 Guruh: {GROUP_LINK}\n🎁 4 ta taklif = 1⭐\n🎁 Kunlik bonus: +{DAILY_BONUS}⭐")

@bot.message_handler(commands=["tasks"])
def tasks_cmd(m):
    uid = m.from_user.id
    tasks = db.get_tasks()
    completed = db.get_user_completed_tasks(uid)
    if not tasks:
        bot.reply_to(m, "❌ Hozircha vazifalar yo'q.")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    for tid, ch_id, username, name, url, reward in tasks:
        if tid not in completed:
            markup.add(types.InlineKeyboardButton(f"🔍 {name}", callback_data=f"task_{tid}_check"))
    if markup.keyboard:
        bot.reply_to(m, "✅ Vazifalar: Kanalga obuna bo'ling, so'ng 'Tekshirish' tugmasini bosing.", reply_markup=markup)
    else:
        bot.reply_to(m, "✅ Barcha vazifalarni bajargan-siz!")

# ================= LEADERBOARD SCHEDULER (majburiy kanallarga xabar YO'Q) =================
def leaderboard_scheduler():
    empty_count = 0
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
                    text += f"\n🔥 4 ta taklif = 1⭐ | 🔗 @{BOT_USERNAME}"
                    # ********** KANALLARGA YUBORISH O'CHIRILGAN **********
                    empty_count = 0
            else:
                empty_count += 1
                if empty_count >= 60:
                    top = db.get_top(10)
                    if top:
                        text = "🏆 <b>TOP 10 (avtomatik)</b>\n\n"
                        for i, (u, n, inv, st, v, streak) in enumerate(top, 1):
                            user = f"@{u}" if u else n
                            medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}️⃣"
                            text += f"{medal} <b>{user}</b> {'👑' if v else ''}\n👥{inv} ⭐{format_stars(st)}\n\n"
                        text += f"🔗 @{BOT_USERNAME}"
                        # ********** KANALLARGA YUBORISH O'CHIRILGAN **********
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
                        bot.send_photo(uid, gift['photo'], caption=f"🎁 <b>{gift['name']}</b>\n{gift['desc']}\n\n⭐ Do'kondan oling!\n🔗 @{BOT_USERNAME}", reply_markup=markup)
                        db.update_last_ad(uid)
                    except:
                        pass
                    time.sleep(0.5)
        except:
            pass
        time.sleep(172800)

# ================= FLASK HTTP SERVER (Render uchun) =================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot ishlamoqda", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ================= MAIN =================
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 STARS BOT ISHGA TUSHIRILDI")
    print(f"💰 Kunlik bonus: {DAILY_BONUS}⭐")
    print(f"👤 Admin: {ADMIN_USERNAME}")
    print(f"📊 Taklif tizimi: 4 ta = 1⭐")
    print("📢 Majburiy kanallarga xabar yuborilmaydi")
    print("=" * 50)
    
    try:
        requests.get(f"https://api.telegram.org/bot{API_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=5)
        time.sleep(1)
    except:
        pass
    
    # Leaderboard va reklama thread'lari
    Thread(target=leaderboard_scheduler, daemon=True).start()
    Thread(target=auto_ad_sender, daemon=True).start()
    
    # Flask server thread
    Thread(target=run_flask, daemon=True).start()
    
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
