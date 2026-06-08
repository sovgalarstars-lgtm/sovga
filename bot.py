import os
import time
import random
import logging
import sqlite3
import requests
from threading import Lock, Thread
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
import telebot
from telebot import types

load_dotenv()

# ================= CONFIG =================
API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    print("❌ BOT_TOKEN topilmadi!")
    exit(1)

ADMIN_ID = int(os.getenv("ADMIN_ID", "2010030869"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "stars_sovga_gifbot")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@Stars_5_odam_1stars")
GROUP_ID = -1002449896845
GROUP_LINK = "https://t.me/Stars_2_odam_1stars"
DAILY_BONUS = 0.20
TASK_REWARD = 0.20

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BOT")

# ================= DATABASE =================
lock = Lock()

class DB:
    def __init__(self):
        db_path = "/tmp/bot.db"
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cur = self.conn.cursor()
        self.init()

    def init(self):
        with lock:
            self.cur.executescript("""
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                successful_invites INTEGER DEFAULT 0,
                stars REAL DEFAULT 0,
                vip INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                last_daily TIMESTAMP,
                daily_streak INTEGER DEFAULT 0,
                total_spent REAL DEFAULT 0,
                total_earned REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS invite_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inviter_id INTEGER,
                invited_id INTEGER,
                invited_name TEXT,
                source TEXT DEFAULT 'link',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

            CREATE TABLE IF NOT EXISTS user_tasks(
                user_id INTEGER,
                task_id INTEGER,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, task_id)
            );

            CREATE TABLE IF NOT EXISTS pending_referrals(
                invited_id INTEGER PRIMARY KEY,
                inviter_id INTEGER,
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
            """)
            self.conn.commit()

    # ---------- Foydalanuvchi ----------
    def create_user(self, uid, username, name):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO users(user_id, username, first_name) VALUES(?,?,?)", (uid, username, name))
            self.conn.commit()

    def get(self, uid):
        with lock:
            self.cur.execute("SELECT successful_invites, stars, vip, total_spent, last_daily, daily_streak, total_earned FROM users WHERE user_id=?", (uid,))
            row = self.cur.fetchone()
            if row:
                return {"successful_invites": row[0] or 0, "stars": float(row[1] or 0), "vip": row[2] or 0, "spent": float(row[3] or 0), "last_daily": row[4], "streak": row[5] or 0, "earned": float(row[6] or 0)}
            return {"successful_invites": 0, "stars": 0.0, "vip": 0, "spent": 0.0, "last_daily": None, "streak": 0, "earned": 0.0}

    # ---------- Referal ----------
    def add_pending_referral(self, invited_id, inviter_id):
        with lock:
            self.cur.execute("INSERT OR REPLACE INTO pending_referrals(invited_id, inviter_id) VALUES(?,?)", (invited_id, inviter_id))
            self.conn.commit()

    def get_pending_inviter(self, invited_id):
        with lock:
            self.cur.execute("SELECT inviter_id FROM pending_referrals WHERE invited_id=?", (invited_id,))
            row = self.cur.fetchone()
            return row[0] if row else None

    def remove_pending(self, invited_id):
        with lock:
            self.cur.execute("DELETE FROM pending_referrals WHERE invited_id=?", (invited_id,))
            self.conn.commit()

    def add_history(self, inviter_id, invited_id, invited_name, source="link"):
        with lock:
            self.cur.execute("INSERT INTO invite_history(inviter_id, invited_id, invited_name, source) VALUES(?,?,?,?)", (inviter_id, invited_id, invited_name, source))
            self.conn.commit()

    def check_duplicate(self, inviter_id, invited_id):
        with lock:
            self.cur.execute("SELECT COUNT(*) FROM invite_history WHERE inviter_id=? AND invited_id=?", (inviter_id, invited_id))
            return self.cur.fetchone()[0] > 0

    def add_successful_invite(self, uid):
        with lock:
            self.cur.execute("SELECT successful_invites, stars, total_earned FROM users WHERE user_id=?", (uid,))
            row = self.cur.fetchone()
            if row:
                old_cnt = row[0] or 0
                stars = float(row[1] or 0)
                earned = float(row[2] or 0)
            else:
                old_cnt = 0; stars = 0.0; earned = 0.0
            new_cnt = old_cnt + 1
            added_stars = 0.0
            if new_cnt % 2 == 0 and old_cnt % 2 != 0:
                added_stars = 1.0
            new_stars = stars + added_stars
            new_earned = earned + added_stars
            self.cur.execute("UPDATE users SET successful_invites=?, stars=?, total_earned=? WHERE user_id=?", (new_cnt, new_stars, new_earned, uid))
            self.conn.commit()
            return new_cnt, new_stars

    # ---------- Yulduzlar ----------
    def sub_star(self, uid, amount):
        with lock:
            self.cur.execute("SELECT stars FROM users WHERE user_id=?", (uid,))
            cur = float(self.cur.fetchone()[0] or 0)
            new = max(0.0, cur - amount)
            self.cur.execute("UPDATE users SET stars=?, total_spent=total_spent+? WHERE user_id=?", (new, amount, uid))
            self.conn.commit()
            return new

    def add_stars_admin(self, uid, amount):
        with lock:
            self.cur.execute("SELECT stars FROM users WHERE user_id=?", (uid,))
            cur = float(self.cur.fetchone()[0] or 0)
            new = cur + amount
            self.cur.execute("UPDATE users SET stars=?, total_earned=total_earned+? WHERE user_id=?", (new, amount, uid))
            self.conn.commit()
            return new

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
            extra = 0.5 if streak > 0 and streak % 7 == 0 else 0
            bonus += extra
            ns = cs + bonus
            ne = te + bonus
            self.cur.execute("UPDATE users SET stars=?, last_daily=?, daily_streak=?, total_earned=? WHERE user_id=?", (ns, now.isoformat(), streak, ne, uid))
            self.conn.commit()
            return True, ns, bonus, streak, extra

    # ---------- Boshqa ----------
    def grant_vip(self, uid):
        with lock:
            self.cur.execute("UPDATE users SET vip=1 WHERE user_id=?", (uid,))
            self.conn.commit()

    def get_top(self, limit=10):
        with lock:
            self.cur.execute("SELECT username, first_name, successful_invites, stars, vip, daily_streak FROM users WHERE is_banned=0 ORDER BY successful_invites DESC LIMIT ?", (limit,))
            return self.cur.fetchall()

    def get_purchase_history(self, uid):
        with lock:
            self.cur.execute("SELECT item_name, item_emoji, price, created_at FROM purchase_history WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (uid,))
            return self.cur.fetchall()

    def add_purchase_history(self, uid, item_name, item_emoji, price):
        with lock:
            self.cur.execute("INSERT INTO purchase_history(user_id, item_name, item_emoji, price) VALUES(?,?,?,?)", (uid, item_name, item_emoji, price))
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

    def get_all_users_for_ad(self):
        with lock:
            self.cur.execute("SELECT user_id FROM users WHERE is_banned=0")
            return [row[0] for row in self.cur.fetchall()]

    def get_stats(self):
        with lock:
            s = {}
            self.cur.execute("SELECT COUNT(*) FROM users"); s["users"] = self.cur.fetchone()[0]
            self.cur.execute("SELECT SUM(successful_invites) FROM users"); s["invites"] = self.cur.fetchone()[0] or 0
            self.cur.execute("SELECT SUM(stars) FROM users"); s["stars"] = float(self.cur.fetchone()[0] or 0)
            self.cur.execute("SELECT COUNT(*) FROM users WHERE vip=1"); s["vip"] = self.cur.fetchone()[0]
            self.cur.execute("SELECT SUM(total_spent) FROM users"); s["spent"] = float(self.cur.fetchone()[0] or 0)
            self.cur.execute("SELECT COUNT(*) FROM invite_history"); s["total_invites"] = self.cur.fetchone()[0]
            self.cur.execute("SELECT COUNT(*) FROM purchase_history"); s["purchases"] = self.cur.fetchone()[0]
            return s

    # ---------- Majburiy kanallar ----------
    def get_forced_channels(self):
        with lock:
            self.cur.execute("SELECT id, channel_type, channel_id, channel_username, channel_name, channel_url FROM forced_channels")
            return self.cur.fetchall()

    def add_forced_channel(self, channel_type, channel_id, username, name, url):
        with lock:
            self.cur.execute("INSERT INTO forced_channels(channel_type, channel_id, channel_username, channel_name, channel_url) VALUES(?,?,?,?,?)",
                             (channel_type, channel_id, username, name, url))
            self.conn.commit()

    def remove_forced_channel(self, channel_db_id):
        with lock:
            self.cur.execute("DELETE FROM forced_channels WHERE id=?", (channel_db_id,))
            self.conn.commit()

    def is_forced_completed(self, user_id, channel_db_id):
        with lock:
            self.cur.execute("SELECT 1 FROM user_forced WHERE user_id=? AND channel_id=?", (user_id, channel_db_id))
            return self.cur.fetchone() is not None

    def complete_forced(self, user_id, channel_db_id):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO user_forced(user_id, channel_id) VALUES(?,?)", (user_id, channel_db_id))
            self.conn.commit()

    # ---------- Vazifalar ----------
    def get_tasks(self):
        with lock:
            self.cur.execute("SELECT id, task_type, channel_id, channel_username, channel_name, channel_url, reward FROM tasks")
            return self.cur.fetchall()

    def add_task(self, task_type, channel_id, username, name, url, reward=TASK_REWARD):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO tasks(task_type, channel_id, channel_username, channel_name, channel_url, reward) VALUES(?,?,?,?,?,?)",
                             (task_type, channel_id, username, name, url, reward))
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
            if self.is_task_completed(user_id, task_id): return False
            self.cur.execute("INSERT INTO user_tasks(user_id, task_id) VALUES(?,?)", (user_id, task_id))
            self.cur.execute("UPDATE users SET stars = stars + ?, total_earned = total_earned + ? WHERE user_id=?", (reward, reward, user_id))
            self.conn.commit()
            return True

    def get_user_completed_tasks(self, user_id):
        with lock:
            self.cur.execute("SELECT task_id FROM user_tasks WHERE user_id=?", (user_id,))
            return [row[0] for row in self.cur.fetchall()]

    # ---------- Qidiruv (admin uchun) ----------
    def search_user(self, query):
        with lock:
            try:
                q = int(query)
                self.cur.execute("SELECT user_id, username, first_name, successful_invites, stars, vip, daily_streak FROM users WHERE user_id=?", (q,))
                row = self.cur.fetchone()
                if row:
                    return [row]
            except:
                pass
            self.cur.execute("SELECT user_id, username, first_name, successful_invites, stars, vip, daily_streak FROM users WHERE username LIKE ? OR first_name LIKE ? LIMIT 10", (f"%{query}%", f"%{query}%"))
            return self.cur.fetchall()

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

# ================= YORDAMCHI =================
def check_sub(uid):
    channels = db.get_forced_channels()
    not_sub = []
    for ch in channels:
        db_id, ctype, ch_id, username, name, url = ch
        if ctype == 'telegram':
            try:
                member = bot.get_chat_member(ch_id, uid)
                if member.status not in ['member','administrator','creator']:
                    not_sub.append({"db_id": db_id, "type": ctype, "name": name, "url": url, "username": username})
            except Exception as e:
                if "chat not found" in str(e).lower():
                    logger.warning(f"Kanal topilmadi, o'chirilmoqda: {db_id}")
                    db.remove_forced_channel(db_id)
                else:
                    logger.warning(f"Telegram tekshirish xatosi: {e}")
        else:
            if not db.is_forced_completed(uid, db_id):
                not_sub.append({"db_id": db_id, "type": ctype, "name": name, "url": url, "username": username})
    return not_sub

def add_footer(text):
    mot = random.choice(["🔥 Siz zo'rsiz!","💪 Har bir taklif - yulduz","⭐ Yulduzlar kutmoqda"])
    return f"{text}\n\n{'─'*20}\n💡 <i>{mot}</i>"

def format_stars(stars):
    if stars == int(stars): return str(int(stars))
    return f"{stars:.2f}"

def get_invite_link(uid):
    try:
        user_info = bot.get_chat(uid)
        if user_info.username:
            return f"https://t.me/{BOT_USERNAME}?start={user_info.username}"
    except:
        pass
    return f"https://t.me/{BOT_USERNAME}?start={uid}"

def finalize_referral(invited_id):
    inviter_id = db.get_pending_inviter(invited_id)
    if inviter_id:
        db.create_user(inviter_id, None, "User")
        try:
            user = bot.get_chat(invited_id)
            name = user.first_name
        except: name = "User"
        db.add_history(inviter_id, invited_id, name, "link")
        new_cnt, new_stars = db.add_successful_invite(inviter_id)
        db.remove_pending(invited_id)
        try:
            bot.send_message(inviter_id, f"🎉 Sizning havolangiz orqali {name} qo'shildi! Sizda {new_cnt} ta taklif, {format_stars(new_stars)}⭐")
        except: pass

# ================= BOT HANDLERLAR =================
bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML", threaded=False)

@bot.message_handler(commands=["start"])
def start(m):
    uid = m.from_user.id
    try:
        if db.check_ban(uid):
            return bot.send_message(m.chat.id, "❌ Bloklangansiz!")
        if m.text and len(m.text.split()) > 1:
            param = m.text.split()[1]
            try:
                ref = int(param)
            except:
                # username bo'yicha qidirish
                # Eng oddiy yo'l: get_chat orqali username ni tekshirish
                try:
                    user = bot.get_chat(param)  # param @username bo'lsa, user obyekti qaytadi
                    ref = user.id
                except:
                    ref = None
            if ref and ref != uid and not db.check_duplicate(ref, uid):
                db.add_pending_referral(uid, ref)
        not_sub = check_sub(uid)
        if not_sub:
            markup = types.InlineKeyboardMarkup(row_width=1)
            for ch in not_sub:
                if ch['type'] == 'telegram':
                    markup.add(types.InlineKeyboardButton(f"{ch['name']} - OBUNA", url=ch['url']))
                    markup.add(types.InlineKeyboardButton("✅ OBUNA BO'LDIM", callback_data=f"forcesub_telegram_{ch['db_id']}"))
                else:
                    markup.add(types.InlineKeyboardButton(f"{ch['name']} - HA VOLA", url=ch['url']))
                    markup.add(types.InlineKeyboardButton("✅ BAJARDIM", callback_data=f"forcesub_claim_{ch['db_id']}"))
            return bot.send_message(m.chat.id, "❌ Obuna bo'ling:\n\n", reply_markup=markup)
        finalize_referral(uid)
        db.create_user(uid, m.from_user.username, m.from_user.first_name)
        u = db.get(uid)
        vip_status = "✅ HA" if u["vip"] else "❌ YO'Q"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("🛒 DO'KON", callback_data="shop"), types.InlineKeyboardButton(f"🎁 +{DAILY_BONUS}⭐", callback_data="daily"))
        markup.add(types.InlineKeyboardButton("🏆 TOP", callback_data="top"), types.InlineKeyboardButton("📊 PROFIL", callback_data="profile"))
        markup.add(types.InlineKeyboardButton("🔗 LINK", callback_data="link"), types.InlineKeyboardButton("✅ VAZIFALAR", callback_data="tasks"))
        text = f"""🌟 <b>STARS BOT</b>
👤 <b>{m.from_user.first_name}</b>
👥 Takliflar: <b>{u['successful_invites']}</b> (2 ta = 1⭐)
⭐ Yulduzlar: <b>{format_stars(u['stars'])}</b>
👑 VIP: <b>{vip_status}</b>
🔥 Streak: {u['streak']} kun"""
        bot.send_message(m.chat.id, add_footer(text), reply_markup=markup)
    except Exception as e:
        logger.error(f"/start xatosi: {e}")
        bot.send_message(m.chat.id, f"❌ Xatolik yuz berdi. Admin bilan bog'laning.\nXato: {str(e)[:100]}")

@bot.callback_query_handler(func=lambda c: True)
def callback(call):
    uid = call.from_user.id
    data = call.data
    try:
        if data.startswith("forcesub_"):
            parts = data.split("_")
            action = parts[1]
            db_id = int(parts[2])
            if action == "telegram":
                ch = db.get_forced_channels()
                target = next((c for c in ch if c[0] == db_id), None)
                if target:
                    try:
                        member = bot.get_chat_member(target[2], uid)
                        if member.status in ['member','administrator','creator']:
                            bot.answer_callback_query(call.id, "✅ Qabul qilindi!", show_alert=False)
                            try: bot.delete_message(call.message.chat.id, call.message.message_id)
                            except: pass
                            start(call.message)
                        else:
                            bot.answer_callback_query(call.id, "❌ Obuna bo'lmagansiz!", show_alert=True)
                    except:
                        bot.answer_callback_query(call.id, "❌ Tekshirib bo'lmadi!", show_alert=True)
            elif action == "claim":
                db.complete_forced(uid, db_id)
                bot.answer_callback_query(call.id, "✅ Tasdiqlandi!", show_alert=False)
                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                except: pass
                start(call.message)
            return

        if data == "daily":
            ok, ns, bonus, streak, extra = db.give_daily_bonus(uid)
            if ok:
                extra_text = f"\n🎉 HAFTALIK! +{extra}⭐" if extra else ""
                bot.send_message(call.message.chat.id, add_footer(f"🎁 Kunlik bonus: +{bonus}⭐\nJami: {format_stars(ns)}⭐\nStreak: {streak}{extra_text}"))
                bot.answer_callback_query(call.id, f"+{bonus}⭐", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "❌ Bugun olgansiz!", show_alert=True)
        elif data == "shop":
            u = db.get(uid)
            markup = types.InlineKeyboardMarkup(row_width=2)
            for iid, item in SHOP.items():
                can = "✅" if u['stars'] >= item['price'] else "🔒"
                markup.add(types.InlineKeyboardButton(f"{can} {item['emoji']} {item['name']} {item['price']}⭐", callback_data=f"buy_{iid}"))
            bot.send_message(call.message.chat.id, add_footer(f"🛒 Balans: {format_stars(u['stars'])}⭐"), reply_markup=markup)
        elif data == "top":
            top = db.get_top(10)
            if top:
                text = "🏆 TOP 10:\n"
                for i,(un,nm,inv,st,v,streak) in enumerate(top,1):
                    user = f"@{un}" if un else nm
                    medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}️⃣"
                    vip = "👑" if v else ""
                    text += f"{medal} {user} {vip} - {inv} taklif, {format_stars(st)}⭐\n"
                bot.send_message(call.message.chat.id, add_footer(text))
        elif data == "profile":
            u = db.get(uid)
            vip = "✅" if u['vip'] else "❌"
            # username olish
            try:
                user_info = bot.get_chat(uid)
                username = f"@{user_info.username}" if user_info.username else "🚫 username yo'q"
            except:
                username = "🚫 username yo'q"
            bot.send_message(call.message.chat.id, add_footer(f"📊 Profil\n👤 {call.from_user.first_name}\n🆔 {uid}\n📛 {username}\n👑 VIP: {vip}\n🔥 Streak: {u['streak']}\n👥 Takliflar: {u['successful_invites']}\n⭐ Yulduz: {format_stars(u['stars'])}"))
        elif data == "link":
            link = get_invite_link(uid)
            bot.send_message(call.message.chat.id, add_footer(f"🔗 {link}"))
        elif data == "tasks":
            tasks = db.get_tasks()
            completed = db.get_user_completed_tasks(uid)
            if not tasks:
                bot.send_message(call.message.chat.id, "❌ Vazifalar yo'q")
                return
            markup = types.InlineKeyboardMarkup(row_width=1)
            for tid, ttype, ch_id, uname, name, url, reward in tasks:
                if tid in completed:
                    markup.add(types.InlineKeyboardButton(f"✅ {name}", callback_data="done"))
                else:
                    if ttype == 'telegram':
                        markup.add(types.InlineKeyboardButton(f"📢 {name} (+{reward}⭐)", url=url))
                        markup.add(types.InlineKeyboardButton("🔍 Tekshirish", callback_data=f"task_{tid}_check"))
                    else:
                        markup.add(types.InlineKeyboardButton(f"🎯 {name} (+{reward}⭐)", callback_data=f"task_{tid}_claim"))
            bot.send_message(call.message.chat.id, "✅ Vazifalar", reply_markup=markup)
        elif data.startswith("task_"):
            parts = data.split("_")
            if len(parts)<3: return
            tid = int(parts[1])
            action = parts[2]
            tasks = db.get_tasks()
            task = next((t for t in tasks if t[0]==tid), None)
            if not task:
                bot.answer_callback_query(call.id, "❌ Topilmadi")
                return
            ttype = task[1]; ch_id = task[2]; name = task[4]; reward = task[6]
            if ttype == 'telegram':
                try:
                    member = bot.get_chat_member(ch_id, uid)
                    if member.status in ['member','administrator','creator']:
                        if db.complete_task(uid, tid, reward):
                            bot.answer_callback_query(call.id, f"✅ +{reward}⭐", show_alert=True)
                            bot.send_message(call.message.chat.id, f"✅ {name} bajarildi! +{reward}⭐")
                        else:
                            bot.answer_callback_query(call.id, "❌ Bajarilgan!", show_alert=True)
                    else:
                        bot.answer_callback_query(call.id, "❌ Obuna bo'lmagansiz", show_alert=True)
                except Exception as e:
                    bot.answer_callback_query(call.id, "❌ Tekshirib bo'lmadi", show_alert=True)
            else:
                if action == "claim":
                    if db.complete_task(uid, tid, reward):
                        bot.answer_callback_query(call.id, f"✅ +{reward}⭐", show_alert=True)
                        bot.send_message(call.message.chat.id, f"✅ {name} bajarildi! +{reward}⭐")
                    else:
                        bot.answer_callback_query(call.id, "❌ Bajarilgan!", show_alert=True)
        elif data.startswith("buy_"):
            item_id = int(data.split("_")[1])
            item = SHOP.get(item_id)
            if not item: return
            u = db.get(uid)
            if u['stars'] < item['price']:
                bot.answer_callback_query(call.id, f"❌ {item['price'] - u['stars']}⭐ yetmaydi", show_alert=True)
                return
            ns = db.sub_star(uid, item['price'])
            db.add_purchase_history(uid, item['name'], item['emoji'], item['price'])
            extra = "\n👑 VIP berildi!" if item['price'] >= 50 else ""
            if item['price'] >= 50: db.grant_vip(uid)
            caption = f"""✅ <b>Sovg'a berildi!</b>

{item['emoji']} <b>{item['name']}</b>
💰 Sarflandi: <b>{item['price']}⭐</b>
⭐ Qoldi: <b>{format_stars(ns)}</b>{extra}

⏳ <b>Admin 24 soat ichida sovg'angizni yuboradi.</b>"""
            bot.send_photo(call.message.chat.id, item['photo'], caption=caption)
            bot.answer_callback_query(call.id, "✅", show_alert=True)
            # Admin uchun xabar (username qo'shib)
            try:
                user_info = bot.get_chat(uid)
                uname = f"@{user_info.username}" if user_info.username else ""
                admin_msg = f"🛍 {call.from_user.first_name} {uname} (<a href='tg://user?id={uid}'>{uid}</a>) {item['name']} {item['price']}⭐"
            except:
                admin_msg = f"🛍 {call.from_user.first_name} (<a href='tg://user?id={uid}'>{uid}</a>) {item['name']} {item['price']}⭐"
            try:
                bot.send_message(ADMIN_ID, admin_msg)
            except:
                logger.error("Admin xabari yuborilmadi. Admin botga /start bosganmi?")
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Callback xatosi: {e}")
        bot.answer_callback_query(call.id, f"❌ Xatolik: {e}", show_alert=True)

# ================= ADMIN BUYRUG'LARI =================
@bot.message_handler(commands=["admin"])
def admin_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
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
/ban [id]
/unban [id]
/broadcast [matn]
/addchannel [tur] [chat_id] [@] [nomi] [url]
/removetask [id]
/tasklist
/search [id/username]
/userlink [id yoki @username]
"""
        bot.reply_to(m, text)
    except Exception as e:
        bot.reply_to(m, f"❌ Xato: {e}")

@bot.message_handler(commands=["userlink"])
def userlink_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        query = m.text.split(maxsplit=1)[1]
        # username yoki ID bo'lishi mumkin
        try:
            uid = int(query)
        except:
            # username bo'yicha qidirish
            results = db.search_user(query)
            if results:
                uid = results[0][0]  # birinchi natijaning user_id
            else:
                bot.reply_to(m, "❌ Foydalanuvchi topilmadi!")
                return
        link = f"tg://user?id={uid}"
        bot.reply_to(m, f"🔗 <a href='{link}'>{uid}</a>", parse_mode="HTML")
    except:
        bot.reply_to(m, "❌ /userlink [id yoki @username]")

@bot.message_handler(commands=["addstars"])
def addstars(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        parts = m.text.split()
        if len(parts) < 3:
            bot.reply_to(m, "❌ /addstars [id] [miqdor]")
            return
        uid, amt = int(parts[1]), float(parts[2])
        db.create_user(uid, None, "User")
        ns = db.add_stars_admin(uid, amt)
        bot.reply_to(m, f"✅ {uid} +{amt}⭐, jami {format_stars(ns)}")
    except Exception as e:
        bot.reply_to(m, f"❌ Xato: {e}")

@bot.message_handler(commands=["ban"])
def ban_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        uid = int(m.text.split()[1])
        db.ban_user(uid)
        bot.reply_to(m, f"✅ {uid} bloklandi")
    except:
        bot.reply_to(m, "❌ /ban [id]")

@bot.message_handler(commands=["unban"])
def unban_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        uid = int(m.text.split()[1])
        db.unban_user(uid)
        bot.reply_to(m, f"✅ {uid} blokdan chiqarildi")
    except:
        bot.reply_to(m, "❌ /unban [id]")

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
    except:
        bot.reply_to(m, "❌ /broadcast [matn]")

@bot.message_handler(commands=["addchannel"])
def addchannel(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        parts = m.text.split(maxsplit=5)
        if len(parts) < 6:
            bot.reply_to(m, "❌ /addchannel [tur] [chat_id yoki 0] [@] [nomi] [url]\nMasalan:\n/addchannel telegram -100123 @kanal Kanal https://t.me/kanal")
            return
        ctype = parts[1].lower()
        if ctype not in ('telegram','instagram','youtube'):
            bot.reply_to(m, "❌ Noto'g'ri tur. telegram/instagram/youtube")
            return
        ch_id = int(parts[2])
        uname = parts[3]
        name = parts[4]
        url = parts[5]
        db.add_forced_channel(ctype, ch_id, uname, name, url)
        bot.reply_to(m, f"✅ Majburiy obuna qo'shildi: {name} ({ctype})")
    except Exception as e:
        bot.reply_to(m, f"❌ Xato: {e}")

@bot.message_handler(commands=["removetask"])
def removetask(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        tid = int(m.text.split()[1])
        db.remove_task(tid)
        bot.reply_to(m, f"✅ {tid} o'chirildi")
    except:
        bot.reply_to(m, "❌ /removetask [id]")

@bot.message_handler(commands=["tasklist"])
def tasklist(m):
    if m.from_user.id != ADMIN_ID: return
    tasks = db.get_tasks()
    if tasks:
        text = "\n".join([f"{t[0]}: {t[1]} {t[4]} +{t[6]}⭐" for t in tasks])
        bot.reply_to(m, text)
    else:
        bot.reply_to(m, "Vazifalar yo'q")

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

# ================= FOYDALANUVCHI BUYRUG'LARI =================
@bot.message_handler(commands=["stats"])
def stats_cmd(m):
    uid = m.from_user.id
    try:
        u = db.get(uid)
        total_users = db.get_stats()["users"]
        vip_status = "✅ HA" if u["vip"] else "❌ YO'Q"
        text = f"📊 <b>Sizning statistikangiz</b>\n👥 Takliflar: {u['successful_invites']}\n⭐ Yulduzlar: {format_stars(u['stars'])}\n👑 VIP: {vip_status}\n🔥 Streak: {u['streak']} kun\n\n🌐 <b>Botda jami foydalanuvchilar:</b> {total_users}"
        bot.reply_to(m, add_footer(text))
    except Exception as e:
        bot.reply_to(m, f"❌ Xatolik: {e}")

@bot.message_handler(commands=["daily"])
def daily_cmd(m):
    uid = m.from_user.id
    try:
        ok, ns, bonus, streak, extra = db.give_daily_bonus(uid)
        if ok: bot.reply_to(m, add_footer(f"🎁 +{bonus}⭐ | Jami: {format_stars(ns)}⭐ | 🔥 Streak: {streak}"))
        else: bot.reply_to(m, "❌ Bugun olgansiz!")
    except Exception as e:
        bot.reply_to(m, f"❌ Xatolik: {e}")

@bot.message_handler(commands=["link"])
def link_cmd(m):
    try:
        bot.reply_to(m, f"🔗 {get_invite_link(m.from_user.id)}")
    except:
        bot.reply_to(m, "❌ Xatolik yuz berdi.")

@bot.message_handler(commands=["tasks"])
def tasks_cmd(m):
    try:
        tasks = db.get_tasks()
        if tasks:
            text = "\n".join([f"{t[4]} +{t[6]}⭐" for t in tasks])
            bot.reply_to(m, text)
        else:
            bot.reply_to(m, "Vazifalar yo'q")
    except:
        bot.reply_to(m, "❌ Xatolik yuz berdi.")

# ================= HTTP SERVER (Port uchun) =================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot ishlamoqda")
    def log_message(self, format, *args):
        pass

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"🌐 HTTP server {port} portda ishga tushdi")
    server.serve_forever()

# ================= ISHGA TUSHIRISH =================
if __name__ == "__main__":
    print("🚀 Bot ishga tushirilmoqda (Web Service)...")
    try:
        resp = requests.get(f"https://api.telegram.org/bot{API_TOKEN}/getMe", timeout=10)
        if resp.status_code != 200 or not resp.json().get("ok"):
            print("❌ Token noto'g'ri!"); exit(1)
        print(f"✅ Token to'g'ri: @{resp.json()['result']['username']}")
    except Exception as e:
        print(f"❌ Token tekshirib bo'lmadi: {e}"); exit(1)

    try:
        requests.get(f"https://api.telegram.org/bot{API_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
    except: pass

    Thread(target=run_http_server, daemon=True).start()
    time.sleep(2)

    while True:
        try:
            bot.infinity_polling(timeout=60, skip_pending=True)
        except KeyboardInterrupt:
            print("👋 To'xtatildi"); break
        except Exception as e:
            logger.error(f"Polling xatosi: {e}"); time.sleep(5)
