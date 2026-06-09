import os
import time
import random
import logging
import sqlite3
import requests
from threading import Lock, Thread, Timer
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
import telebot
from telebot import types

load_dotenv()

# ================= KONFIGURATSIYA =================
API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    print("❌ BOT_TOKEN topilmadi!")
    exit(1)

ADMIN_ID = int(os.getenv("ADMIN_ID", "2010030869"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "stars_sovga_gifbot")
if BOT_USERNAME.startswith("@"):
    BOT_USERNAME = BOT_USERNAME[1:]

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@Stars_5_odam_1stars")
GROUP_ID = -1002449896845
GROUP_LINK = "https://t.me/Stars_2_odam_1stars"
DAILY_BONUS = 0.20
TASK_REWARD = 0.20

# ================= BOT INIT =================
bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML", threaded=False)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BOT")

# ================= DATABASE =================
lock = Lock()
pending_external_checks = {}  # {user_id: {"type": "forced", "db_id": x, "chat_id": y, "message_id": z, "timer": Timer}}

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
            CREATE TABLE IF NOT EXISTS forced_channels(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_type TEXT DEFAULT 'telegram',
                channel_id INTEGER,
                channel_username TEXT,
                channel_name TEXT,
                channel_url TEXT
            );
            CREATE TABLE IF NOT EXISTS user_forced(
                user_id INTEGER,
                channel_id INTEGER,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, channel_id)
            );
            CREATE TABLE IF NOT EXISTS tasks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT DEFAULT 'telegram',
                channel_id INTEGER,
                channel_username TEXT,
                channel_name TEXT,
                channel_url TEXT,
                reward REAL DEFAULT 0.20
            );
            CREATE TABLE IF NOT EXISTS bot_config(
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """)
            self.cur.execute("INSERT OR IGNORE INTO bot_config(key, value) VALUES('max_users', '500')")
            self.cur.execute("INSERT OR IGNORE INTO bot_config(key, value) VALUES('forced_mode', 'true')")
            self.conn.commit()

    def get_config(self, key, default=None):
        with lock:
            self.cur.execute("SELECT value FROM bot_config WHERE key=?", (key,))
            row = self.cur.fetchone()
            return row[0] if row else default

    def set_config(self, key, value):
        with lock:
            self.cur.execute("REPLACE INTO bot_config(key, value) VALUES(?,?)", (key, str(value)))
            self.conn.commit()

    # ---------- Foydalanuvchi ----------
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

    def get_user_count(self):
        with lock:
            self.cur.execute("SELECT COUNT(*) FROM users")
            return self.cur.fetchone()[0]

    # ---------- Referal ----------
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

    def check_duplicate(self, inviter_id, invited_id):
        with lock:
            self.cur.execute("SELECT COUNT(*) FROM invite_history WHERE inviter_id=? AND invited_id=?", (inviter_id, invited_id))
            return self.cur.fetchone()[0] > 0

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

    # ---------- Yulduzlar ----------
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
            self.cur.execute("UPDATE users SET stars = stars + ?, total_earned = total_earned + ? WHERE user_id=?", (amount, amount, uid))
            self.conn.commit()
            self.cur.execute("SELECT stars FROM users WHERE user_id=?", (uid,))
            return self.cur.fetchone()[0]

    def give_daily_bonus(self, uid):
        with lock:
            self.cur.execute("SELECT last_daily, stars, daily_streak, total_earned FROM users WHERE user_id=?", (uid,))
            row = self.cur.fetchone()
            if not row: return False, 0, 0, 0, 0
            last_daily, cs, streak, te = row
            cs = float(cs or 0); streak = streak or 0; te = float(te or 0)
            now = datetime.now()
            if last_daily:
                try:
                    last = datetime.fromisoformat(last_daily)
                    if now.date() == last.date(): return False, cs, 0, streak, 0
                    streak = streak + 1 if (now.date() - last.date()).days == 1 else 1
                except: streak = 1
            else: streak = 1
            bonus = DAILY_BONUS
            extra = 0.5 if streak % 7 == 0 else 0
            bonus += extra
            ns = cs + bonus
            ne = te + bonus
            self.cur.execute("UPDATE users SET stars=?, last_daily=?, daily_streak=?, total_earned=? WHERE user_id=?", (ns, now.isoformat(), streak, ne, uid))
            self.conn.commit()
            return True, ns, bonus, streak, extra

    def grant_vip(self, uid):
        with lock:
            self.cur.execute("UPDATE users SET vip=1 WHERE user_id=?", (uid,))
            self.conn.commit()

    # ---------- Boshqa ----------
    def get_top(self, limit=10):
        with lock:
            self.cur.execute("SELECT username, first_name, invites, stars, vip, daily_streak FROM users WHERE is_banned=0 ORDER BY invites DESC LIMIT ?", (limit,))
            return self.cur.fetchall()

    def get_purchase_history(self, uid):
        with lock:
            self.cur.execute("SELECT item_name, item_emoji, price, created_at FROM purchase_history WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (uid,))
            return self.cur.fetchall()

    def add_purchase_history(self, uid, name, emoji, price):
        with lock:
            self.cur.execute("INSERT INTO purchase_history(user_id, item_name, item_emoji, price) VALUES(?,?,?,?)", (uid, name, emoji, price))
            self.conn.commit()

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
            try:
                q = int(query)
                self.cur.execute("SELECT user_id, username, first_name, invites, stars, vip, daily_streak FROM users WHERE user_id=?", (q,))
                row = self.cur.fetchone()
                if row: return [row]
            except: pass
            self.cur.execute("SELECT user_id, username, first_name, invites, stars, vip, daily_streak FROM users WHERE username LIKE ? OR first_name LIKE ? LIMIT 10", (f"%{query}%", f"%{query}%"))
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

    def get_all_users_for_ad(self):
        with lock:
            self.cur.execute("SELECT user_id FROM users WHERE is_banned=0")
            return [row[0] for row in self.cur.fetchall()]

    # ---------- Majburiy kanallar ----------
    def get_forced_channels(self):
        with lock:
            self.cur.execute("SELECT id, channel_type, channel_id, channel_username, channel_name, channel_url FROM forced_channels")
            return self.cur.fetchall()

    def add_forced_channel(self, ctype, ch_id, uname, name, url):
        with lock:
            self.cur.execute("INSERT INTO forced_channels(channel_type, channel_id, channel_username, channel_name, channel_url) VALUES(?,?,?,?,?)", (ctype, ch_id, uname, name, url))
            self.conn.commit()
            return self.cur.lastrowid

    def remove_forced_channel(self, db_id):
        with lock:
            self.cur.execute("DELETE FROM forced_channels WHERE id=?", (db_id,))
            self.conn.commit()

    def is_forced_completed(self, uid, db_id):
        with lock:
            self.cur.execute("SELECT 1 FROM user_forced WHERE user_id=? AND channel_id=?", (uid, db_id))
            return self.cur.fetchone() is not None

    def complete_forced(self, uid, db_id):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO user_forced(user_id, channel_id) VALUES(?,?)", (uid, db_id))
            self.conn.commit()

    def get_user_completed_forced_ids(self, uid):
        with lock:
            self.cur.execute("SELECT channel_id FROM user_forced WHERE user_id=?", (uid,))
            return [r[0] for r in self.cur.fetchall()]

    # ---------- Vazifalar ----------
    def get_tasks(self):
        with lock:
            self.cur.execute("SELECT id, task_type, channel_id, channel_username, channel_name, channel_url, reward FROM tasks")
            return self.cur.fetchall()

    def add_task(self, ttype, ch_id, uname, name, url, reward=TASK_REWARD):
        with lock:
            self.cur.execute("INSERT INTO tasks(task_type, channel_id, channel_username, channel_name, channel_url, reward) VALUES(?,?,?,?,?,?)", (ttype, ch_id, uname, name, url, reward))
            self.conn.commit()

    def remove_task(self, tid):
        with lock:
            self.cur.execute("DELETE FROM tasks WHERE id=?", (tid,))
            self.conn.commit()

    def is_task_completed(self, uid, tid):
        with lock:
            self.cur.execute("SELECT 1 FROM user_tasks WHERE user_id=? AND task_id=?", (uid, tid))
            return self.cur.fetchone() is not None

    def complete_task(self, uid, tid, reward):
        with lock:
            if self.is_task_completed(uid, tid): return False
            self.cur.execute("INSERT INTO user_tasks(user_id, task_id) VALUES(?,?)", (uid, tid))
            self.cur.execute("UPDATE users SET stars=stars+?, total_earned=total_earned+? WHERE user_id=?", (reward, reward, uid))
            self.conn.commit()
            return True

db = DB()

# ================= SHOP =================
SHOP = {
    1: {"price":15,"name":"❤️ Pushti Yurakcha","emoji":"❤️","photo":"https://i.imgur.com/8Yp9Z2M.jpg","desc":"Chiroyli pushti yurak"},
    2: {"price":15,"name":"🧸 Ayiqcha","emoji":"🧸","photo":"https://i.imgur.com/5f2vL8K.jpg","desc":"Yoqimli ayiqcha"},
    3: {"price":25,"name":"🌹 Atirgul","emoji":"🌹","photo":"https://i.imgur.com/7zK9pQm.jpg","desc":"Romantik atirgul"},
    4: {"price":25,"name":"🎁 Sovg'a qutisi","emoji":"🎁","photo":"https://i.imgur.com/3vX9pLm.jpg","desc":"Sirli sovg'a"},
    5: {"price":50,"name":"🎂 Tort","emoji":"🎂","photo":"https://i.imgur.com/9pL2mNx.jpg","desc":"Shirin tort + VIP"},
    6: {"price":50,"name":"💐 Gullar","emoji":"💐","photo":"https://i.imgur.com/XkP5vRt.jpg","desc":"Guldasta + VIP"},
    7: {"price":100,"name":"🏆 Oltin kubok","emoji":"🏆","photo":"https://i.imgur.com/vL9pQmN.jpg","desc":"Oltin + VIP"},
    8: {"price":100,"name":"💍 Olmos uzuk","emoji":"💍","photo":"https://i.imgur.com/kP8mNxZ.jpg","desc":"Brilliant + VIP"},
    9: {"price":200,"name":"💎 Brilliant","emoji":"💎","photo":"https://i.imgur.com/kP8mNxZ.jpg","desc":"Qimmatbaho + VIP"},
    10:{"price":500,"name":"👑 Qirol toji","emoji":"👑","photo":"https://i.imgur.com/XkP5vRt.jpg","desc":"Haqiqiy toj + VIP"},
}

# ================= YORDAMCHI FUNKSIYALAR =================
def is_forced_mode_enabled():
    forced_mode = db.get_config("forced_mode", "true").lower() == "true"
    if not forced_mode:
        return False
    max_users = int(db.get_config("max_users", "500"))
    current_users = db.get_user_count()
    if current_users >= max_users:
        return False
    return True

def check_sub(uid):
    if not is_forced_mode_enabled():
        return []
    channels = db.get_forced_channels()
    not_sub = []
    completed_ids = db.get_user_completed_forced_ids(uid)
    for ch in channels:
        db_id, ctype, ch_id, username, name, url = ch
        if db_id in completed_ids:
            continue
        if ctype == 'telegram':
            try:
                member = bot.get_chat_member(ch_id, uid)
                if member.status not in ['member', 'administrator', 'creator']:
                    not_sub.append({"db_id": db_id, "type": ctype, "name": name, "url": url})
            except:
                not_sub.append({"db_id": db_id, "type": ctype, "name": name, "url": url})
        else:
            not_sub.append({"db_id": db_id, "type": ctype, "name": name, "url": url})
    return not_sub

def all_forced_completed(uid):
    return len(check_sub(uid)) == 0

def process_referral_after_forced(uid):
    if not all_forced_completed(uid):
        return False
    pending = db.get_pending_invite(uid)
    if pending:
        inviter_id, source = pending
        if not db.check_duplicate(inviter_id, uid):
            db.add_history(inviter_id, uid, str(uid), source)
            db.add_invite(inviter_id)
        db.remove_pending_invite(uid)
        return True
    return False

def add_footer(text):
    mot = random.choice(["🔥 Siz zo'rsiz!", "💪 Har bir taklif - yulduz", "⭐ Yulduzlar kutmoqda", "🚀 Oldinga!"])
    return f"{text}\n\n{'─'*20}\n💡 <i>{mot}</i>"

def format_stars(stars):
    if stars == int(stars): return str(int(stars))
    return f"{stars:.2f}"

def get_invite_link(uid):
    return f"https://t.me/{BOT_USERNAME}?start={uid}"

# ================= BOT HANDLERLAR =================
@bot.message_handler(commands=["start"])
def start(m):
    uid = m.from_user.id
    if db.check_ban(uid):
        return bot.send_message(m.chat.id, "❌ Siz bloklangansiz!")

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
            if ch['type'] == 'telegram':
                markup.add(types.InlineKeyboardButton(f"📢 {ch['name']}", url=ch['url']))
                markup.add(types.InlineKeyboardButton("✅ Obuna bo'ldim", callback_data=f"forcesub_check_{ch['db_id']}"))
            else:
                markup.add(types.InlineKeyboardButton(f"🔗 {ch['name']}", url=ch['url']))
                markup.add(types.InlineKeyboardButton("✅ Obuna bo'ldim", callback_data=f"forcesub_wait_{ch['db_id']}"))
        text = "❌ Botdan foydalanish uchun quyidagi kanal va sahifalarga obuna bo'ling:\n\n" + "\n".join([f"• {ch['name']}" for ch in not_sub])
        return bot.send_message(m.chat.id, text, reply_markup=markup)

    process_referral_after_forced(uid)
    db.create_user(uid, m.from_user.username, m.from_user.first_name)

    u = db.get(uid)
    vip_status = "✅ HA" if u["vip"] else "❌ YO'Q"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🛒 DO'KON", callback_data="shop"), types.InlineKeyboardButton(f"🎁 +{DAILY_BONUS}⭐", callback_data="daily"))
    markup.add(types.InlineKeyboardButton("🏆 TOP", callback_data="top"), types.InlineKeyboardButton("📊 PROFIL", callback_data="profile"))
    markup.add(types.InlineKeyboardButton("🔗 HAVOLA", callback_data="link"), types.InlineKeyboardButton("📜 XARIDLAR", callback_data="purchases"))
    markup.add(types.InlineKeyboardButton("📋 VAZIFALAR", callback_data="tasks"))

    text = f"""
🌟 <b>STARS BOT</b>

👤 <b>{m.from_user.first_name}</b>
👥 Takliflar: <b>{u['invites']}</b> (2 ta = 1⭐)
⭐ Yulduzlar: <b>{format_stars(u['stars'])}</b>
👑 VIP: <b>{vip_status}</b>
🔥 Streak: {u['streak']} kun

🎯 <i>2 ta taklif = 1⭐</i>
"""
    bot.send_message(m.chat.id, add_footer(text), reply_markup=markup)

@bot.message_handler(content_types=['new_chat_members'])
def new_members(message):
    if message.chat.id != GROUP_ID:
        return
    for member in message.new_chat_members:
        if member.is_bot: continue
        inviter_id = message.from_user.id
        invited_id = member.id
        if inviter_id == invited_id: continue
        db.add_pending_invite(inviter_id, invited_id, "group")
    try:
        bot.send_message(message.chat.id, f"✅ {len(message.new_chat_members)} ta yangi a'zo qo'shildi! Obunadan keyin taklif hisoblanadi.")
    except:
        pass

# ================= CALLBACKLAR =================
@bot.callback_query_handler(func=lambda c: True)
def callback(call):
    uid = call.from_user.id
    data = call.data

    try:
        # Majburiy obuna - telegram kanal (darhol tekshirish)
        if data.startswith("forcesub_check_"):
            db_id = int(data.split("_")[2])
            channels = db.get_forced_channels()
            target = next((c for c in channels if c[0] == db_id), None)
            if target and target[1] == 'telegram':
                try:
                    member = bot.get_chat_member(target[2], uid)
                    if member.status in ['member','administrator','creator']:
                        db.complete_forced(uid, db_id)
                        bot.answer_callback_query(call.id, "✅ Qabul qilindi!", show_alert=False)
                        start(call.message)
                    else:
                        bot.answer_callback_query(call.id, "❌ Hali obuna bo'lmagansiz!", show_alert=True)
                except:
                    bot.answer_callback_query(call.id, "❌ Tekshirib bo'lmadi!", show_alert=True)
            return

        # Majburiy obuna - tashqi link (10 soniya orqa fonda kutish)
        if data.startswith("forcesub_wait_"):
            db_id = int(data.split("_")[2])
            # Foydalanuvchiga xabar: kutish boshlanganini bildirish
            bot.answer_callback_query(call.id, "⏳ 10 soniya tekshiriladi, iltimos kuting...", show_alert=False)
            msg = bot.send_message(call.message.chat.id, "⏳ Obunangiz tekshirilmoqda. Iltimos, 10 soniya kuting...\n\n✅ Agar obuna bo'lgan bo'lsangiz, avtomatik tasdiqlanadi.")
            
            # Orqa fonda 10 soniyadan keyin tekshiruvchi funksiyani ishga tushirish
            def verify_external_forced():
                try:
                    # Obuna bajarilganmi? (hech qanday tasdiqlash tugmasi yo'q)
                    channels = db.get_forced_channels()
                    target = next((c for c in channels if c[0] == db_id), None)
                    if target and target[1] != 'telegram':
                        # Tashqi linklar uchun biz hech qanday haqiqiy tekshiruv qila olmaymiz,
                        # shuning uchun 10 soniyadan keyin avtomatik tasdiqlaymiz.
                        # Agar foydalanuvchi yolg'on gapirgan bo'lsa, bu uning muammosi.
                        # Siz xohlasangiz, bu erda API orqali tekshirish qo'shishingiz mumkin.
                        db.complete_forced(uid, db_id)
                        bot.send_message(call.message.chat.id, f"✅ {target[4]} uchun obuna tasdiqlandi! Endi botdan to‘liq foydalanishingiz mumkin.")
                        # Referalni qayta ishlash
                        process_referral_after_forced(uid)
                        # Startni yangilash
                        start(call.message)
                    else:
                        bot.send_message(call.message.chat.id, "❌ Xatolik: kanal topilmadi.")
                except Exception as e:
                    logger.error(f"External forced verification error: {e}")
                finally:
                    if uid in pending_external_checks:
                        del pending_external_checks[uid]
            
            timer = Timer(10.0, verify_external_forced)
            timer.daemon = True
            timer.start()
            pending_external_checks[uid] = {"type": "forced", "timer": timer, "chat_id": call.message.chat.id, "message_id": msg.message_id}
            return

        # Kunlik bonus
        if data == "daily":
            ok, ns, bonus, streak, extra = db.give_daily_bonus(uid)
            if ok:
                extra_text = f"\n🎉 HAFTALIK! +{extra}⭐" if extra else ""
                bot.send_message(call.message.chat.id, add_footer(f"🎁 Kunlik bonus: +{bonus}⭐\nJami: {format_stars(ns)}⭐\nStreak: {streak}{extra_text}"))
                bot.answer_callback_query(call.id, f"+{bonus}⭐", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "❌ Bugun olgansiz!", show_alert=True)
            return

        # Do'kon
        if data == "shop":
            u = db.get(uid)
            markup = types.InlineKeyboardMarkup(row_width=2)
            for iid, item in SHOP.items():
                can = "✅" if u['stars'] >= item['price'] else "🔒"
                markup.add(types.InlineKeyboardButton(f"{can} {item['emoji']} {item['name']} {item['price']}⭐", callback_data=f"buy_{iid}"))
            bot.send_message(call.message.chat.id, add_footer(f"🛒 Balans: {format_stars(u['stars'])}⭐"), reply_markup=markup)
            return

        # Top
        if data == "top":
            top = db.get_top(10)
            if top:
                text = "🏆 TOP 10 taklifchilar:\n\n"
                for i, (un, nm, inv, st, v, streak) in enumerate(top, 1):
                    user = f"@{un}" if un else nm
                    medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}️⃣"
                    vip = "👑" if v else ""
                    text += f"{medal} {user} {vip}\n👥 {inv} | ⭐ {format_stars(st)}\n\n"
                bot.send_message(call.message.chat.id, add_footer(text))
            else:
                bot.send_message(call.message.chat.id, "Hali hech qanday taklif yo'q")
            return

        # Profil
        if data == "profile":
            u = db.get(uid)
            vip = "✅" if u['vip'] else "❌"
            text = f"📊 <b>PROFIL</b>\n\n👤 {call.from_user.first_name}\n🆔 {uid}\n👑 VIP: {vip}\n🔥 Streak: {u['streak']}\n👥 Takliflar: {u['invites']}\n⭐ Yulduzlar: {format_stars(u['stars'])}\n💰 Sarflangan: {format_stars(u['spent'])}⭐\n💎 Topgan: {format_stars(u['earned'])}⭐"
            bot.send_message(call.message.chat.id, add_footer(text))
            return

        # Havola
        if data == "link":
            link = get_invite_link(uid)
            bot.send_message(call.message.chat.id, add_footer(f"🔗 <code>{link}</code>\n\n📢 Guruh: {GROUP_LINK}"))
            return

        # Xaridlar tarixi
        if data == "purchases":
            purchases = db.get_purchase_history(uid)
            if purchases:
                text = "📜 <b>XARIDLAR</b>\n\n" + "\n".join([f"{emoji} {name} - {format_stars(price)}⭐" for name, emoji, price, dt in purchases])
                bot.send_message(call.message.chat.id, add_footer(text))
            else:
                bot.send_message(call.message.chat.id, "❌ Hali xarid yo'q!")
            return

        # Vazifalar menyusi
        if data == "tasks":
            tasks = db.get_tasks()
            if not tasks:
                bot.send_message(call.message.chat.id, "❌ Hozircha vazifalar yo'q")
                return
            markup = types.InlineKeyboardMarkup(row_width=1)
            for tid, ttype, ch_id, uname, name, url, reward in tasks:
                if db.is_task_completed(uid, tid):
                    markup.add(types.InlineKeyboardButton(f"✅ {name} (+{reward}⭐)", callback_data="done"))
                else:
                    if ttype == 'telegram':
                        markup.add(types.InlineKeyboardButton(f"📢 {name} (+{reward}⭐)", url=url))
                        markup.add(types.InlineKeyboardButton("🔍 Tekshirish", callback_data=f"task_check_{tid}"))
                    else:
                        markup.add(types.InlineKeyboardButton(f"🔗 {name} (+{reward}⭐)", url=url))
                        markup.add(types.InlineKeyboardButton("✅ Bajarildi", callback_data=f"task_wait_{tid}"))
            bot.send_message(call.message.chat.id, "📋 <b>VAZIFALAR</b>\n\nHar bir vazifani bajarib yulduz oling.", reply_markup=markup)
            return

        # Vazifalar - telegram kanali uchun tekshirish
        if data.startswith("task_check_"):
            tid = int(data.split("_")[2])
            tasks = db.get_tasks()
            task = next((t for t in tasks if t[0] == tid), None)
            if not task:
                bot.answer_callback_query(call.id, "❌ Vazifa topilmadi")
                return
            if task[1] == 'telegram':
                try:
                    member = bot.get_chat_member(task[2], uid)
                    if member.status in ['member','administrator','creator']:
                        if db.complete_task(uid, tid, task[6]):
                            bot.answer_callback_query(call.id, f"✅ +{task[6]}⭐", show_alert=True)
                            bot.send_message(call.message.chat.id, f"✅ {task[4]} bajarildi! +{task[6]}⭐")
                        else:
                            bot.answer_callback_query(call.id, "❌ Siz bu vazifani allaqachon bajargan edingiz", show_alert=True)
                    else:
                        bot.answer_callback_query(call.id, "❌ Siz hali kanalga obuna bo'lmagansiz", show_alert=True)
                except:
                    bot.answer_callback_query(call.id, "❌ Kanalni tekshirib bo'lmadi", show_alert=True)
            return

        # Vazifalar - tashqi link uchun (10 soniya orqa fonda kutish)
        if data.startswith("task_wait_"):
            tid = int(data.split("_")[2])
            bot.answer_callback_query(call.id, "⏳ 10 soniya tekshiriladi, iltimos kuting...", show_alert=False)
            msg = bot.send_message(call.message.chat.id, "⏳ Vazifangiz tekshirilmoqda. Iltimos, 10 soniya kuting...")
            
            def verify_task():
                try:
                    tasks = db.get_tasks()
                    task = next((t for t in tasks if t[0] == tid), None)
                    if task:
                        if db.complete_task(uid, tid, task[6]):
                            bot.send_message(call.message.chat.id, f"✅ {task[4]} bajarildi! +{task[6]}⭐")
                        else:
                            bot.send_message(call.message.chat.id, "❌ Vazifa allaqachon bajarilgan yoki xatolik yuz berdi.")
                except Exception as e:
                    logger.error(f"Task verification error: {e}")
                finally:
                    if uid in pending_external_checks and pending_external_checks[uid].get("type") == "task":
                        del pending_external_checks[uid]
            
            timer = Timer(10.0, verify_task)
            timer.daemon = True
            timer.start()
            pending_external_checks[uid] = {"type": "task", "timer": timer, "chat_id": call.message.chat.id, "message_id": msg.message_id}
            return

        # Xarid qilish
        if data.startswith("buy_"):
            item_id = int(data.split("_")[1])
            item = SHOP.get(item_id)
            if not item: return
            u = db.get(uid)
            if u['stars'] < item['price']:
                bot.answer_callback_query(call.id, f"❌ {item['price'] - u['stars']:.2f}⭐ yetmaydi", show_alert=True)
                return
            ns = db.sub_star(uid, item['price'])
            db.add_purchase_history(uid, item['name'], item['emoji'], item['price'])
            extra = "\n👑 VIP berildi!" if item['price'] >= 50 else ""
            if item['price'] >= 50:
                db.grant_vip(uid)
            caption = f"""✅ <b>Sovg'a berildi!</b>

{item['emoji']} <b>{item['name']}</b>
💰 Sarflandi: <b>{item['price']}⭐</b>
⭐ Qoldi: <b>{format_stars(ns)}</b>{extra}

⏳ <b>Admin 24 soat ichida sovg'angizni yuboradi.</b>"""
            bot.send_photo(call.message.chat.id, item['photo'], caption=caption)
            bot.answer_callback_query(call.id, "✅ Sotib olindi!", show_alert=True)
            # Admin xabari
            profile_link = f"tg://user?id={uid}"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📞 Yozish", url=profile_link))
            try:
                bot.send_message(ADMIN_ID, f"🛍 {call.from_user.first_name} {item['name']} ({item['price']}⭐)", reply_markup=markup)
            except:
                pass
            return

        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Callback xatosi: {e}", exc_info=True)
        bot.answer_callback_query(call.id, f"❌ Xatolik: {e}", show_alert=True)

def show_tasks_menu(chat_id, uid):
    tasks = db.get_tasks()
    if not tasks:
        bot.send_message(chat_id, "❌ Hozircha vazifalar yo'q")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for tid, ttype, ch_id, uname, name, url, reward in tasks:
        status = "✅" if db.is_task_completed(uid, tid) else "❌"
        if db.is_task_completed(uid, tid):
            markup.add(types.InlineKeyboardButton(f"{status} {name} (+{reward}⭐)", callback_data="done"))
        else:
            if ttype == 'telegram':
                markup.add(types.InlineKeyboardButton(f"📢 {name} (+{reward}⭐)", url=url))
                markup.add(types.InlineKeyboardButton("🔍 Tekshirish", callback_data=f"task_check_{tid}"))
            else:
                markup.add(types.InlineKeyboardButton(f"🔗 {name} (+{reward}⭐)", url=url))
                markup.add(types.InlineKeyboardButton("✅ Bajarildi", callback_data=f"task_wait_{tid}"))
    bot.send_message(chat_id, "📋 <b>VAZIFALAR</b>\n\nHar bir vazifani bajarib yulduz oling.", reply_markup=markup)

# ================= ADMIN BUYRUG'LARI =================
@bot.message_handler(commands=["admin"])
def admin_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    s = db.get_stats()
    text = f"""🔐 <b>ADMIN PANEL</b>
👥 Foydalanuvchilar: {s['users']}
📊 Jami takliflar: {s['total_invites']}
⭐ Yulduzlar: {format_stars(s['stars'])}
👑 VIP: {s['vip']}
💸 Sarflangan: {format_stars(s['spent'])}
🛍 Xaridlar: {s['purchases']}

<b>Buyruqlar:</b>
/addstars [id] [miqdor]
/ban [id] /unban [id]
/broadcast [matn]
/addforced [tur] [chat_id] [@] [nomi] [url]
/removeforced [id]
/listforced
/addtask [tur] [chat_id] [@] [nomi] [url] [reward]
/removetask [id]
/listtasks
/set_limit [son]
/toggle_forced
/forced_status
/search [id/username]
/stats"""
    bot.reply_to(m, text)

@bot.message_handler(commands=["addstars"])
def addstars(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        parts = m.text.split()
        if len(parts) < 3:
            bot.reply_to(m, "❌ /addstars [id] [miqdor]"); return
        uid = int(parts[1]); amount = float(parts[2])
        db.create_user(uid, None, "User")
        new_balance = db.add_stars_admin(uid, amount)
        bot.reply_to(m, f"✅ {uid} ga +{format_stars(amount)}⭐ qo'shildi. Jami: {format_stars(new_balance)}⭐")
    except Exception as e:
        bot.reply_to(m, f"❌ Xato: {e}")

@bot.message_handler(commands=["ban"])
def ban_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        uid = int(m.text.split()[1])
        db.ban_user(uid)
        bot.reply_to(m, f"✅ {uid} bloklandi")
    except: bot.reply_to(m, "❌ /ban [id]")

@bot.message_handler(commands=["unban"])
def unban_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        uid = int(m.text.split()[1])
        db.unban_user(uid)
        bot.reply_to(m, f"✅ {uid} blokdan chiqarildi")
    except: bot.reply_to(m, "❌ /unban [id]")

@bot.message_handler(commands=["broadcast"])
def broadcast(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        text = m.text.split(maxsplit=1)[1]
        users = db.get_all_users_for_ad()
        sent = 0
        for uid in users:
            try:
                bot.send_message(uid, f"📢 {text}")
                sent += 1
                time.sleep(0.1)
            except: pass
        bot.reply_to(m, f"✅ {sent}/{len(users)}")
    except: bot.reply_to(m, "❌ /broadcast [matn]")

@bot.message_handler(commands=["addforced"])
def addforced(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        parts = m.text.split(maxsplit=5)
        if len(parts) < 6:
            bot.reply_to(m, "❌ /addforced [tur] [chat_id] [@] [nomi] [url]\nMasalan: /addforced telegram -100123 @kanal Kanal https://t.me/kanal")
            return
        ctype = parts[1].lower()
        if ctype not in ('telegram','instagram','youtube'):
            bot.reply_to(m, "❌ Noto'g'ri tur. telegram/instagram/youtube"); return
        try:
            ch_id = int(parts[2])
        except:
            ch_id = 0
        uname = parts[3]
        name = parts[4]
        url = parts[5]
        db.add_forced_channel(ctype, ch_id, uname, name, url)
        bot.reply_to(m, f"✅ Majburiy obuna qo'shildi: {name} ({ctype})")
    except Exception as e:
        bot.reply_to(m, f"❌ Xato: {e}")

@bot.message_handler(commands=["removeforced"])
def removeforced(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        fid = int(m.text.split()[1])
        db.remove_forced_channel(fid)
        bot.reply_to(m, f"✅ {fid} o'chirildi")
    except: bot.reply_to(m, "❌ /removeforced [id]")

@bot.message_handler(commands=["listforced"])
def listforced(m):
    if m.from_user.id != ADMIN_ID: return
    chs = db.get_forced_channels()
    if chs:
        text = "📋 Majburiy obunalar:\n"
        for c in chs:
            text += f"ID:{c[0]} | {c[1]} | {c[4]}\n"
        bot.reply_to(m, text)
    else:
        bot.reply_to(m, "Majburiy obuna yo'q")

@bot.message_handler(commands=["addtask"])
def addtask(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        parts = m.text.split(maxsplit=6)
        if len(parts) < 6:
            bot.reply_to(m, "❌ /addtask [tur] [chat_id] [@] [nomi] [url] [reward(0.20)]\nMasalan: /addtask telegram -100123 @kanal Vazifa https://t.me/kanal 0.20")
            return
        ctype = parts[1].lower()
        if ctype not in ('telegram','instagram','youtube'):
            bot.reply_to(m, "❌ Noto'g'ri tur. telegram/instagram/youtube"); return
        try:
            ch_id = int(parts[2])
        except:
            ch_id = 0
        uname = parts[3]
        name = parts[4]
        url = parts[5]
        reward = float(parts[6]) if len(parts) > 6 else TASK_REWARD
        db.add_task(ctype, ch_id, uname, name, url, reward)
        bot.reply_to(m, f"✅ Vazifa qo'shildi: {name} (+{reward}⭐)")
    except Exception as e:
        bot.reply_to(m, f"❌ Xato: {e}")

@bot.message_handler(commands=["removetask"])
def removetask(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        tid = int(m.text.split()[1])
        db.remove_task(tid)
        bot.reply_to(m, f"✅ {tid} o'chirildi")
    except: bot.reply_to(m, "❌ /removetask [id]")

@bot.message_handler(commands=["listtasks"])
def listtasks(m):
    if m.from_user.id != ADMIN_ID: return
    tasks = db.get_tasks()
    if tasks:
        text = "📋 Vazifalar:\n"
        for t in tasks:
            text += f"ID:{t[0]} | {t[1]} | {t[4]} | +{t[6]}⭐\n"
        bot.reply_to(m, text)
    else:
        bot.reply_to(m, "Vazifalar yo'q")

@bot.message_handler(commands=["set_limit"])
def set_limit(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        new_limit = int(m.text.split()[1])
        db.set_config("max_users", new_limit)
        bot.reply_to(m, f"✅ Foydalanuvchi limiti {new_limit} ga o'zgartirildi. Agar hozirgi foydalanuvchilar soni {db.get_user_count()} bo'lsa, majburiy obuna {'o\'chadi' if db.get_user_count() >= new_limit else 'yoqilgan holda qoladi'}.")
    except:
        bot.reply_to(m, "❌ /set_limit [son]")

@bot.message_handler(commands=["toggle_forced"])
def toggle_forced(m):
    if m.from_user.id != ADMIN_ID: return
    current = db.get_config("forced_mode", "true").lower() == "true"
    new_val = "false" if current else "true"
    db.set_config("forced_mode", new_val)
    status = "yoqildi" if new_val == "true" else "o'chirildi"
    bot.reply_to(m, f"✅ Majburiy obuna rejimi {status}.")

@bot.message_handler(commands=["forced_status"])
def forced_status(m):
    if m.from_user.id != ADMIN_ID: return
    enabled = is_forced_mode_enabled()
    max_users = int(db.get_config("max_users", "500"))
    current_users = db.get_user_count()
    forced_mode_config = db.get_config("forced_mode", "true").lower() == "true"
    text = f"""📊 <b>Majburiy obuna holati</b>
Konfiguratsiya: {"✅ YOQILGAN" if forced_mode_config else "❌ O'CHIRILGAN"}
Foydalanuvchi limiti: {max_users}
Jami foydalanuvchilar: {current_users}
Majburiy rejim: {"✅ faol" if enabled else "❌ faol emas"}

Agar {current_users} >= {max_users} bo'lsa, majburiy obuna avtomatik o'chadi."""
    bot.reply_to(m, text)

@bot.message_handler(commands=["search"])
def search_cmd(m):
    if m.from_user.id != ADMIN_ID: return
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

@bot.message_handler(commands=["stats"])
def stats_cmd(m):
    if m.from_user.id != ADMIN_ID:
        u = db.get(m.from_user.id)
        bot.reply_to(m, add_footer(f"📊\n👥{u['invites']} ⭐{format_stars(u['stars'])} 👑{'✅' if u['vip'] else '❌'} 🔥{u['streak']}"))
        return
    s = db.get_stats()
    text = f"📊 <b>Umumiy statistika</b>\n👥 Foydalanuvchilar: {s['users']}\n📊 Takliflar: {s['total_invites']}\n⭐ Yulduzlar: {format_stars(s['stars'])}\n👑 VIP: {s['vip']}\n💸 Sarflangan: {format_stars(s['spent'])}\n🛍 Xaridlar: {s['purchases']}"
    bot.reply_to(m, text)

@bot.message_handler(commands=["daily"])
def daily_cmd(m):
    uid = m.from_user.id
    ok, ns, bonus, streak, extra = db.give_daily_bonus(uid)
    if ok:
        bot.reply_to(m, add_footer(f"🎁 +{bonus}⭐ | Jami: {format_stars(ns)}⭐ | 🔥 Streak: {streak}"))
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

# ================= BACKGROUND TASKS =================
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
                    logger.info("Leaderboard updated (not sent to channels).")
        except Exception as e:
            logger.error(f"Leaderboard: {e}")
        time.sleep(60)

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

# ================= HTTP SERVER FOR RENDER =================
PORT = int(os.environ.get("PORT", 10000))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running")
    def log_message(self, format, *args):
        pass

def start_http_server():
    while True:
        try:
            server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
            print(f"✅ HTTP server listening on port {PORT}")
            server.serve_forever()
        except Exception as e:
            print(f"⚠️ HTTP server error: {e}, retrying in 10s...")
            time.sleep(10)

# ================= MAIN =================
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 STARS BOT ISHGA TUSHIRILDI")
    print(f"💰 Bonus: {DAILY_BONUS}⭐/kun")
    print(f"👤 Admin: {ADMIN_USERNAME}")
    print("📊 Top: 1 daqiqa (kanalga yuborilmaydi)")
    print("✅ Referal obunadan keyin hisoblanadi")
    print("✅ Vazifalar paneli qo'shildi")
    print("✅ Majburiy obuna (tashqi link) 10 soniya ORQA FONDA kutadi")
    print("=" * 50)

    try:
        requests.get(f"https://api.telegram.org/bot{API_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=5)
        time.sleep(1)
    except:
        pass

    Thread(target=leaderboard_scheduler, daemon=True).start()
    Thread(target=auto_ad_sender, daemon=True).start()
    Thread(target=start_http_server, daemon=True).start()
    time.sleep(2)

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
