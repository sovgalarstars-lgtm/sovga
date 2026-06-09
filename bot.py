import os, time, random, logging, sqlite3, requests
from threading import Lock, Thread
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

DB_PATH = "bot.db"  # doimiy saqlanadi

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BOT")

lock = Lock()
pending_verifications = {}  # {user_id: {task_id: timestamp}}  for external tasks (10 sec wait)

# ================= MA'LUMOTLAR BAZASI =================
class DB:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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

    def check_duplicate_invite(self, inviter_id, invited_id):
        with lock:
            self.cur.execute("SELECT COUNT(*) FROM invite_history WHERE inviter_id=? AND invited_id=?", (inviter_id, invited_id))
            return self.cur.fetchone()[0] > 0

    def add_successful_invite(self, uid):
        with lock:
            # Invite hisobini oshirish va 0.5⭐ qo'shish
            self.cur.execute("UPDATE users SET successful_invites = successful_invites + 1, stars = stars + 0.5, total_earned = total_earned + 0.5 WHERE user_id=?", (uid,))
            self.conn.commit()
            # Yangi qiymatlarni olish
            self.cur.execute("SELECT successful_invites, stars FROM users WHERE user_id=?", (uid,))
            return self.cur.fetchone()

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
        with lock: self.cur.execute("UPDATE users SET vip=1 WHERE user_id=?", (uid,)); self.conn.commit()

    def get_top(self, limit=10):
        with lock:
            self.cur.execute("SELECT user_id, username, first_name, successful_invites, stars, vip, daily_streak FROM users WHERE is_banned=0 ORDER BY successful_invites DESC LIMIT ?", (limit,))
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
        with lock: self.cur.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (uid,)); self.conn.commit()

    def unban_user(self, uid):
        with lock: self.cur.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (uid,)); self.conn.commit()

    def get_all_users_for_ad(self):
        with lock:
            self.cur.execute("SELECT user_id FROM users WHERE is_banned=0")
            return [r[0] for r in self.cur.fetchall()]

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

    def add_forced_channel(self, ctype, ch_id, uname, name, url):
        with lock:
            self.cur.execute("INSERT INTO forced_channels(channel_type, channel_id, channel_username, channel_name, channel_url) VALUES(?,?,?,?,?)", (ctype, ch_id, uname, name, url))
            self.conn.commit()

    def remove_forced_channel(self, db_id):
        with lock: self.cur.execute("DELETE FROM forced_channels WHERE id=?", (db_id,)); self.conn.commit()

    def is_forced_completed(self, uid, db_id):
        with lock:
            self.cur.execute("SELECT 1 FROM user_forced WHERE user_id=? AND channel_id=?", (uid, db_id))
            return self.cur.fetchone() is not None

    def complete_forced(self, uid, db_id):
        with lock: self.cur.execute("INSERT OR IGNORE INTO user_forced(user_id, channel_id) VALUES(?,?)", (uid, db_id)); self.conn.commit()

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
        with lock: self.cur.execute("DELETE FROM tasks WHERE id=?", (tid,)); self.conn.commit()

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

    def get_user_completed_tasks(self, uid):
        with lock:
            self.cur.execute("SELECT task_id FROM user_tasks WHERE user_id=?", (uid,))
            return [r[0] for r in self.cur.fetchall()]

    # ---------- Qidiruv (admin) ----------
    def search_user(self, query):
        with lock:
            try:
                q = int(query)
                self.cur.execute("SELECT user_id, username, first_name, successful_invites, stars, vip, daily_streak FROM users WHERE user_id=?", (q,))
                row = self.cur.fetchone()
                if row: return [row]
            except: pass
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

# ================= YORDAMCHI FUNKSIYALAR =================
def check_sub(uid):
    """Majburiy kanallardan obuna bo'lmaganlarini qaytaradi"""
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
                if member.status not in ['member','administrator','creator']:
                    not_sub.append({"db_id": db_id, "type": ctype, "name": name, "url": url})
            except:
                not_sub.append({"db_id": db_id, "type": ctype, "name": name, "url": url})
        else:
            # Tashqi linklar (youtube, instagram) - hali tugmachani bosmagan
            not_sub.append({"db_id": db_id, "type": ctype, "name": name, "url": url})
    return not_sub

def all_forced_completed(uid):
    return len(check_sub(uid)) == 0

def process_referral_after_forced(uid):
    """Agar foydalanuvchi barcha majburiy obunalarni tugatgan bo'lsa, referalni hisobga ol"""
    if not all_forced_completed(uid):
        return False
    inviter_id = db.get_pending_inviter(uid)
    if inviter_id and not db.check_duplicate_invite(inviter_id, uid):
        # Taklif qiluvchini tekshirish, u bloklanmagan bo'lishi kerak
        if not db.check_ban(inviter_id):
            db.create_user(inviter_id, None, "User")
            # Invited nomini olish
            try:
                user = bot.get_chat(uid)
                name = user.first_name
            except:
                name = "User"
            db.add_history(inviter_id, uid, name, "link")
            new_cnt, new_stars = db.add_successful_invite(inviter_id)
            db.remove_pending(uid)
            try:
                bot.send_message(inviter_id, f"🎉 Sizning havolangiz orqali {name} barcha obunalarni tugatdi! Endi sizda {new_cnt} ta taklif, {new_stars:.2f}⭐")
            except:
                pass
            return True
    return False

def add_footer(text):
    mot = random.choice(["🔥 Siz zo'rsiz!","💪 Har bir taklif - yulduz","⭐ Yulduzlar kutmoqda","🚀 Oldinga!"])
    return f"{text}\n\n{'─'*20}\n💡 <i>{mot}</i>"

def format_stars(stars):
    if stars == int(stars): return str(int(stars))
    return f"{stars:.2f}"

def get_invite_link(uid):
    return f"https://t.me/{BOT_USERNAME}?start={uid}"

# ================= BOT =================
bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML", threaded=False)

@bot.message_handler(commands=["start"])
def start(m):
    uid = m.from_user.id
    if db.check_ban(uid):
        return bot.send_message(m.chat.id, "❌ Siz bloklangansiz!")

    # Referal parametrni saqlash
    if m.text and len(m.text.split()) > 1:
        try:
            ref = int(m.text.split()[1])
            if ref != uid and not db.check_duplicate_invite(ref, uid):
                db.add_pending_referral(uid, ref)
        except:
            pass

    # Majburiy obuna tekshiruvi
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
        text = "❌ Botdan foydalanish uchun quyidagi kanal va sahifalarga obuna bo'ling:\n\n"
        for ch in not_sub:
            text += f"• {ch['name']}\n"
        return bot.send_message(m.chat.id, text, reply_markup=markup)

    # Referalni hisobga olish (agar obunalar tugallangan bo'lsa)
    process_referral_after_forced(uid)

    db.create_user(uid, m.from_user.username, m.from_user.first_name)
    u = db.get(uid)
    vip_status = "✅ HA" if u["vip"] else "❌ YO'Q"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("🛒 DO'KON", callback_data="shop"), types.InlineKeyboardButton(f"🎁 +{DAILY_BONUS}⭐", callback_data="daily"))
    markup.add(types.InlineKeyboardButton("🏆 TOP", callback_data="top"), types.InlineKeyboardButton("📊 PROFIL", callback_data="profile"))
    markup.add(types.InlineKeyboardButton("🔗 HAVOLA", callback_data="link"), types.InlineKeyboardButton("✅ VAZIFALAR", callback_data="tasks"))
    text = f"""🌟 <b>STARS BOT</b>

👤 <b>{m.from_user.first_name}</b>
👥 Takliflar: <b>{u['successful_invites']}</b> (2 ta = 1⭐)
⭐ Yulduzlar: <b>{format_stars(u['stars'])}</b>
👑 VIP: <b>{vip_status}</b>
🔥 Streak: {u['streak']} kun"""
    bot.send_message(m.chat.id, add_footer(text), reply_markup=markup)

# ================= CALLBACKLAR =================
@bot.callback_query_handler(func=lambda c: True)
def callback(call):
    uid = call.from_user.id
    data = call.data

    try:
        # Majburiy obuna uchun tekshiruv
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
                        # Yangilangan start
                        start(call.message)
                    else:
                        bot.answer_callback_query(call.id, "❌ Hali obuna bo'lmagansiz!", show_alert=True)
                except:
                    bot.answer_callback_query(call.id, "❌ Tekshirib bo'lmadi!", show_alert=True)
            return

        if data.startswith("forcesub_wait_"):
            db_id = int(data.split("_")[2])
            # 10 sekund kutish mexanizmi
            pending_verifications[uid] = {"type": "forced", "db_id": db_id, "timestamp": datetime.now()}
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"forcesub_confirm_{db_id}"))
            bot.send_message(call.message.chat.id, "⏳ Iltimos 10 soniya kuting, so‘ng «Tasdiqlash» tugmasini bosing.", reply_markup=markup)
            bot.answer_callback_query(call.id, "10 soniyadan keyin tasdiqlang", show_alert=False)
            return

        if data.startswith("forcesub_confirm_"):
            db_id = int(data.split("_")[2])
            if uid in pending_verifications and pending_verifications[uid].get("type") == "forced" and pending_verifications[uid]["db_id"] == db_id:
                elapsed = (datetime.now() - pending_verifications[uid]["timestamp"]).total_seconds()
                if elapsed >= 10:
                    db.complete_forced(uid, db_id)
                    del pending_verifications[uid]
                    bot.answer_callback_query(call.id, "✅ Majburiy obuna bajarildi!", show_alert=False)
                    start(call.message)
                else:
                    bot.answer_callback_query(call.id, f"⏳ {10 - int(elapsed)} soniya qoldi", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "❌ Avval «Obuna bo‘ldim» tugmasini bosing.", show_alert=True)
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
                for i, (top_uid, un, nm, inv, st, v, streak) in enumerate(top, 1):
                    user = f"@{un}" if un else (nm or f"ID:{top_uid}")
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
            try:
                user_info = bot.get_chat(uid)
                username = f"@{user_info.username}" if user_info.username else "🚫"
            except:
                username = "🚫"
            text = f"📊 <b>PROFIL</b>\n\n👤 {call.from_user.first_name}\n🆔 {uid}\n📛 {username}\n👑 VIP: {vip}\n🔥 Streak: {u['streak']}\n👥 Takliflar: {u['successful_invites']}\n⭐ Yulduzlar: {format_stars(u['stars'])}\n💰 Sarflangan: {format_stars(u['spent'])}⭐\n💎 Topgan: {format_stars(u['earned'])}⭐"
            bot.send_message(call.message.chat.id, add_footer(text))
            return

        # Havola
        if data == "link":
            link = get_invite_link(uid)
            bot.send_message(call.message.chat.id, add_footer(f"🔗 <code>{link}</code>\n\n📢 Guruh: {GROUP_LINK}"))
            return

        # Vazifalar menyusi
        if data == "tasks":
            tasks = db.get_tasks()
            completed = db.get_user_completed_tasks(uid)
            if not tasks:
                bot.send_message(call.message.chat.id, "❌ Hozircha vazifalar yo'q")
                return
            markup = types.InlineKeyboardMarkup(row_width=1)
            for tid, ttype, ch_id, uname, name, url, reward in tasks:
                if tid in completed:
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

        # Vazifalarni tekshirish (telegram kanali)
        if data.startswith("task_check_"):
            tid = int(data.split("_")[2])
            tasks = db.get_tasks()
            task = next((t for t in tasks if t[0] == tid), None)
            if not task:
                bot.answer_callback_query(call.id, "❌ Vazifa topilmadi")
                return
            ttype, ch_id, reward = task[1], task[2], task[6]
            if ttype == 'telegram':
                try:
                    member = bot.get_chat_member(ch_id, uid)
                    if member.status in ['member','administrator','creator']:
                        if db.complete_task(uid, tid, reward):
                            bot.answer_callback_query(call.id, f"✅ +{reward}⭐", show_alert=True)
                            bot.send_message(call.message.chat.id, f"✅ {task[4]} bajarildi! +{reward}⭐")
                        else:
                            bot.answer_callback_query(call.id, "❌ Siz bu vazifani allaqachon bajargan edingiz", show_alert=True)
                    else:
                        bot.answer_callback_query(call.id, "❌ Siz hali kanalga obuna bo'lmagansiz", show_alert=True)
                except:
                    bot.answer_callback_query(call.id, "❌ Kanalni tekshirib bo'lmadi", show_alert=True)
            return

        # Vazifalar uchun 10 sekund kutish (tashqi linklar)
        if data.startswith("task_wait_"):
            tid = int(data.split("_")[2])
            pending_verifications[uid] = {"type": "task", "task_id": tid, "timestamp": datetime.now()}
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"task_confirm_{tid}"))
            bot.send_message(call.message.chat.id, "⏳ Iltimos 10 soniya kuting, so‘ng «Tasdiqlash» tugmasini bosing.", reply_markup=markup)
            bot.answer_callback_query(call.id, "10 soniyadan keyin tasdiqlang", show_alert=False)
            return

        if data.startswith("task_confirm_"):
            tid = int(data.split("_")[2])
            if uid in pending_verifications and pending_verifications[uid].get("type") == "task" and pending_verifications[uid]["task_id"] == tid:
                elapsed = (datetime.now() - pending_verifications[uid]["timestamp"]).total_seconds()
                if elapsed >= 10:
                    tasks = db.get_tasks()
                    task = next((t for t in tasks if t[0] == tid), None)
                    if task and db.complete_task(uid, tid, task[6]):
                        bot.send_message(call.message.chat.id, f"✅ {task[4]} bajarildi! +{task[6]}⭐")
                        bot.answer_callback_query(call.id, f"✅ +{task[6]}⭐", show_alert=False)
                    else:
                        bot.answer_callback_query(call.id, "❌ Xatolik yoki allaqachon bajarilgan", show_alert=True)
                    del pending_verifications[uid]
                else:
                    bot.answer_callback_query(call.id, f"⏳ {10 - int(elapsed)} soniya qoldi", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "❌ Avval «Bajarildi» tugmasini bosing.", show_alert=True)
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
/addtask [tur] [chat_id] [@] [nomi] [url]
/removeforced [id] /removetask [id]
/listforced /listtasks
/search [id/username]
/userlink [id yoki @username]"""
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

@bot.message_handler(commands=["removeforced"])
def removeforced(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        fid = int(m.text.split()[1])
        db.remove_forced_channel(fid)
        bot.reply_to(m, f"✅ {fid} o'chirildi")
    except: bot.reply_to(m, "❌ /removeforced [id]")

@bot.message_handler(commands=["removetask"])
def removetask(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        tid = int(m.text.split()[1])
        db.remove_task(tid)
        bot.reply_to(m, f"✅ {tid} o'chirildi")
    except: bot.reply_to(m, "❌ /removetask [id]")

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

@bot.message_handler(commands=["userlink"])
def userlink_cmd(m):
    if m.from_user.id != ADMIN_ID: return
    try:
        query = m.text.split(maxsplit=1)[1]
        try:
            uid = int(query)
        except:
            results = db.search_user(query)
            if results:
                uid = results[0][0]
            else:
                bot.reply_to(m, "❌ Topilmadi!"); return
        profile_link = f"tg://user?id={uid}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔗 Profil", url=profile_link))
        bot.reply_to(m, f"Foydalanuvchi: {uid}", reply_markup=markup)
    except:
        bot.reply_to(m, "❌ /userlink [id yoki @username]")

# ================= FOYDALANUVCHI BUYRUG'LARI =================
@bot.message_handler(commands=["stats"])
def stats_cmd(m):
    uid = m.from_user.id
    u = db.get(uid)
    total_users = db.get_stats()["users"]
    vip_status = "✅ HA" if u["vip"] else "❌ YO'Q"
    text = f"📊 <b>Sizning statistikangiz</b>\n👥 Takliflar: {u['successful_invites']}\n⭐ Yulduzlar: {format_stars(u['stars'])}\n👑 VIP: {vip_status}\n🔥 Streak: {u['streak']} kun\n\n🌐 Botda jami: {total_users} foydalanuvchi"
    bot.reply_to(m, add_footer(text))

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
    bot.reply_to(m, f"🔗 {get_invite_link(m.from_user.id)}")

@bot.message_handler(commands=["tasks"])
def tasks_cmd(m):
    tasks = db.get_tasks()
    if tasks:
        text = "📋 Vazifalar ro'yxati:\n" + "\n".join([f"{t[4]} +{t[6]}⭐" for t in tasks])
        bot.reply_to(m, text)
    else:
        bot.reply_to(m, "Vazifalar yo'q")

@bot.message_handler(commands=["help"])
def help_cmd(m):
    bot.reply_to(m, f"🤖 {BOT_USERNAME}\n\n/start - Botni ishga tushirish\n/stats - Mening statistikam\n/daily - Kunlik bonus olish\n/link - Taklif havolam\n/tasks - Vazifalar ro'yxati\n/help - Yordam\n\n👥 2 ta taklif = 1⭐\n🎁 Kunlik bonus: {DAILY_BONUS}⭐\n📢 Guruh: {GROUP_LINK}")

# ================= HTTP SERVER (Render uchun) =================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot ishlamoqda")
    def log_message(self, format, *args): pass

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"🌐 HTTP server {port} portda ishga tushdi")
    server.serve_forever()

# ================= ISHGA TUSHIRISH =================
if __name__ == "__main__":
    print("🚀 Bot ishga tushirilmoqda...")
    try:
        resp = requests.get(f"https://api.telegram.org/bot{API_TOKEN}/getMe", timeout=10)
        if resp.status_code != 200 or not resp.json().get("ok"):
            print("❌ Token noto'g'ri!"); exit(1)
        print(f"✅ Token to'g'ri: @{resp.json()['result']['username']}")
    except Exception as e:
        print(f"❌ Token tekshirib bo'lmadi: {e}"); exit(1)

    # Webhookni o'chirish
    for _ in range(3):
        try:
            requests.get(f"https://api.telegram.org/bot{API_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=5)
            break
        except: time.sleep(2)

    # HTTP server thread
    Thread(target=run_http_server, daemon=True).start()
    time.sleep(2)

    # Botni polling bilan ishga tushirish
    while True:
        try:
            bot.infinity_polling(timeout=60, skip_pending=True)
        except KeyboardInterrupt:
            print("👋 Bot to'xtatildi")
            break
        except Exception as e:
            logger.error(f"Polling xatosi: {e}")
            time.sleep(5)
