import os
import time
import random
import logging
import sqlite3
import requests
from threading import Lock
from datetime import datetime, timedelta
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
                channel_id INTEGER,
                channel_username TEXT,
                channel_name TEXT,
                channel_url TEXT
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
            # Default majburiy kanallar (faqat ishlaydiganlari)
            self.cur.execute("SELECT COUNT(*) FROM forced_channels")
            if self.cur.fetchone()[0] == 0:
                self.cur.execute("INSERT OR IGNORE INTO forced_channels(channel_id, channel_username, channel_name, channel_url) VALUES(?,?,?,?)",
                                 (-1002449896845, "@Stars_2_odam_1stars", "👥 GURUH", "https://t.me/Stars_2_odam_1stars"))
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
                old_cnt = 0
                stars = 0.0
                earned = 0.0
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
            if not row:
                return False, 0, 0, 0, 0
            last_daily, cs, streak, te = row
            cs = float(cs or 0); streak = streak or 0; te = float(te or 0)
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
            if streak % 7 == 0:
                extra = 0.5
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

    # ---------- Kanallar ----------
    def get_forced_channels(self):
        with lock:
            self.cur.execute("SELECT channel_id, channel_username, channel_name, channel_url FROM forced_channels")
            return self.cur.fetchall()

    def add_forced_channel(self, channel_id, username, name, url):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO forced_channels(channel_id, channel_username, channel_name, channel_url) VALUES(?,?,?,?)", (channel_id, username, name, url))
            self.conn.commit()

    def remove_forced_channel(self, channel_id):
        with lock:
            self.cur.execute("DELETE FROM forced_channels WHERE channel_id=?", (channel_id,))
            self.conn.commit()

    # ---------- Vazifalar ----------
    def get_tasks(self):
        with lock:
            self.cur.execute("SELECT id, task_type, channel_id, channel_username, channel_name, channel_url, reward FROM tasks")
            return self.cur.fetchall()

    def add_task(self, task_type, channel_id, username, name, url, reward=TASK_REWARD):
        with lock:
            self.cur.execute("INSERT OR IGNORE INTO tasks(task_type, channel_id, channel_username, channel_name, channel_url, reward) VALUES(?,?,?,?,?,?)", (task_type, channel_id, username, name, url, reward))
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
    for ch_id, username, name, url in channels:
        try:
            member = bot.get_chat_member(ch_id, uid)
            if member.status not in ['member', 'administrator', 'creator']:
                not_sub.append({"id": ch_id, "username": username, "name": name, "url": url})
        except Exception as e:
            error_msg = str(e)
            if "chat not found" in error_msg.lower():
                logger.warning(f"Kanal topilmadi, o'chirilmoqda: {ch_id} ({name})")
                db.remove_forced_channel(ch_id)
            else:
                logger.warning(f"Tekshirib bo'lmadi {ch_id}: {e}")
    return not_sub

def add_footer(text):
    mot = random.choice(["🔥 Siz zo'rsiz!","💪 Har bir taklif - yulduz","⭐ Yulduzlar kutmoqda"])
    return f"{text}\n\n{'─'*20}\n💡 <i>{mot}</i>"

def format_stars(stars):
    if stars == int(stars): return str(int(stars))
    return f"{stars:.2f}"

def get_invite_link(uid):
    return f"https://t.me/{BOT_USERNAME}?start={uid}"

def finalize_referral(invited_id):
    inviter_id = db.get_pending_inviter(invited_id)
    if inviter_id:
        db.create_user(inviter_id, None, "User")
        try:
            user = bot.get_chat(invited_id)
            name = user.first_name
        except:
            name = "User"
        db.add_history(inviter_id, invited_id, name, "link")
        new_cnt, new_stars = db.add_successful_invite(inviter_id)
        db.remove_pending(invited_id)
        try:
            bot.send_message(inviter_id, f"🎉 Sizning havolangiz orqali {name} qo'shildi! Sizda {new_cnt} ta taklif, {format_stars(new_stars)}⭐")
        except:
            pass

# ================= BOT HANDLERLAR =================
bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML", threaded=False)

@bot.message_handler(commands=["start"])
def start(m):
    uid = m.from_user.id
    if db.check_ban(uid):
        return bot.send_message(m.chat.id, "❌ Bloklangansiz!")
    if m.text and len(m.text.split()) > 1:
        try:
            ref = int(m.text.split()[1])
            if ref != uid and not db.check_duplicate(ref, uid):
                db.add_pending_referral(uid, ref)
        except: pass
    not_sub = check_sub(uid)
    if not_sub:
        markup = types.InlineKeyboardMarkup(row_width=1)
        for ch in not_sub:
            markup.add(types.InlineKeyboardButton(f"{ch['name']} - OBUNA", url=ch['url']))
        markup.add(types.InlineKeyboardButton("✅ OBUNA BO'LDIM", callback_data="check_sub"))
        channels = "\n".join([f"• {ch['name']}: {ch['username']}" for ch in not_sub])
        return bot.send_message(m.chat.id, f"❌ Obuna bo'ling:\n\n{channels}", reply_markup=markup)
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

@bot.callback_query_handler(func=lambda c: True)
def callback(call):
    uid = call.from_user.id
    data = call.data
    if data == "check_sub":
        not_sub = check_sub(uid)
        if not_sub:
            bot.answer_callback_query(call.id, "❌ Obuna bo'ling!", show_alert=True)
            return
        finalize_referral(uid)
        db.create_user(uid, call.from_user.username, call.from_user.first_name)
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        bot.answer_callback_query(call.id, "✅ Xush kelibsiz!", show_alert=True)
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
        bot.send_message(call.message.chat.id, add_footer(f"📊 Profil\n👤 {call.from_user.first_name}\n🆔 {uid}\n👑 VIP: {vip}\n🔥 Streak: {u['streak']}\n👥 Takliflar: {u['successful_invites']}\n⭐ Yulduz: {format_stars(u['stars'])}"))
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
                markup.add(types.InlineKeyboardButton(f"✅ {name}", callback_data=f"done"))
            else:
                if ttype == 'telegram':
                    markup.add(types.InlineKeyboardButton(f"📢 {name} (+{reward}⭐)", url=url))
                    markup.add(types.InlineKeyboardButton("🔍 Tekshirish", callback_data=f"task_{tid}_check"))
                else:
                    markup.add(types.InlineKeyboardButton(f"🎯 {name} (+{reward}⭐)", callback_data=f"task_{tid}_claim"))
        bot.send_message(call.message.chat.id, "✅ Vazifalar (Telegram kanallar tekshiriladi, boshqalar qo'lda)", reply_markup=markup)
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
        extra = ""
        if item['price'] >= 50:
            db.grant_vip(uid)
            extra = "\n👑 VIP berildi!"
        admin_link = f"tg://user?id={ADMIN_ID}"
        caption = f"""✅ Sovg'a berildi!
{item['emoji']} {item['name']}
💰 Sarflandi: {item['price']}⭐
⭐ Qoldi: {format_stars(ns)}{extra}
Admin: {ADMIN_USERNAME}"""
        bot.send_photo(call.message.chat.id, item['photo'], caption=caption)
        bot.answer_callback_query(call.id, "✅", show_alert=True)
        try:
            bot.send_message(ADMIN_ID, f"🛍 {call.from_user.first_name} ({uid}) {item['name']} {item['price']}⭐")
        except: pass
    bot.answer_callback_query(call.id)

# Admin buyruqlar
@bot.message_handler(commands=["admin"])
def admin_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    s = db.get_stats()
    text = f"👥 {s['users']} | ⭐ {format_stars(s['stars'])}\n/addstars /ban /broadcast /addchannel /addtask"
    bot.reply_to(m, text)

@bot.message_handler(commands=["addstars"])
def addstars(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        _, uid, amt = m.text.split()
        uid, amt = int(uid), float(amt)
        db.create_user(uid, None, "User")
        ns = db.add_stars_admin(uid, amt)
        bot.reply_to(m, f"✅ {uid} +{amt}⭐, jami {format_stars(ns)}")
    except: bot.reply_to(m, "❌ /addstars id miqdor")

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
    except: bot.reply_to(m, "❌ /broadcast matn")

@bot.message_handler(commands=["addchannel"])
def addchannel(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        _, ch_id, uname, name, url = m.text.split(maxsplit=4)
        db.add_forced_channel(int(ch_id), uname, name, url)
        bot.reply_to(m, "✅ Kanal qo'shildi")
    except: bot.reply_to(m, "❌ /addchannel chat_id @username nomi url")

@bot.message_handler(commands=["addtask"])
def addtask(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        parts = m.text.split(maxsplit=6)
        if len(parts)<6:
            bot.reply_to(m, "❌ /addtask tur chat_id @ nomi url mukofot")
            return
        ttype = parts[1].lower()
        ch_id = int(parts[2])
        uname = parts[3]
        name = parts[4]
        url = parts[5]
        reward = float(parts[6]) if len(parts)>6 else TASK_REWARD
        if ttype not in ('telegram','instagram','youtube'):
            bot.reply_to(m, "❌ tur: telegram/instagram/youtube")
            return
        db.add_task(ttype, ch_id, uname, name, url, reward)
        bot.reply_to(m, f"✅ Vazifa qo'shildi: {name} +{reward}⭐")
    except: bot.reply_to(m, "❌ Format xato")

@bot.message_handler(commands=["removetask"])
def removetask(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        tid = int(m.text.split()[1])
        db.remove_task(tid)
        bot.reply_to(m, f"✅ {tid} o'chirildi")
    except: bot.reply_to(m, "❌ /removetask id")

@bot.message_handler(commands=["tasklist"])
def tasklist(m):
    if m.from_user.id != ADMIN_ID: return
    tasks = db.get_tasks()
    if tasks:
        text = "\n".join([f"{t[0]}: {t[1]} {t[4]} +{t[6]}⭐" for t in tasks])
        bot.reply_to(m, text)
    else: bot.reply_to(m, "Vazifalar yo'q")

# Foydalanuvchi buyruqlari
@bot.message_handler(commands=["stats","daily","link","tasks"])
def user_cmd(m):
    uid = m.from_user.id
    cmd = m.text.split()[0][1:]
    if cmd == "stats":
        u = db.get(uid)
        bot.reply_to(m, f"👥 {u['successful_invites']} taklif, ⭐ {format_stars(u['stars'])}")
    elif cmd == "daily":
        ok, ns, bonus, streak, extra = db.give_daily_bonus(uid)
        if ok:
            bot.reply_to(m, f"🎁 +{bonus}⭐, jami {format_stars(ns)}")
        else:
            bot.reply_to(m, "❌ Bugun olgansiz")
    elif cmd == "link":
        bot.reply_to(m, f"🔗 {get_invite_link(uid)}")
    elif cmd == "tasks":
        tasks = db.get_tasks()
        if tasks:
            text = "\n".join([f"{t[4]} +{t[6]}⭐" for t in tasks])
            bot.reply_to(m, text)
        else:
            bot.reply_to(m, "Vazifalar yo'q")

# ================= ISHGA TUSHIRISH =================
if __name__ == "__main__":
    print("🚀 Bot ishga tushirilmoqda (Background Worker)...")

    # 409 xatosini bartaraf qilish uchun tasodifiy kechikish
    delay = random.randint(5, 15)
    print(f"⏳ {delay} soniya kutilmoqda...")
    time.sleep(delay)

    try:
        print("Eski webhook o'chirilmoqda...")
        resp = requests.get(f"https://api.telegram.org/bot{API_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
        print(f"Webhook o'chirildi: {resp.json()}")
    except Exception as e:
        print(f"Webhook o'chirishda xatolik (e'tiborsiz): {e}")
    time.sleep(3)

    while True:
        try:
            bot.infinity_polling(timeout=60, skip_pending=True)
        except KeyboardInterrupt:
            print("👋 Bot to'xtatildi")
            break
        except Exception as e:
            logger.error(f"Polling xatosi: {e}")
            time.sleep(5)
