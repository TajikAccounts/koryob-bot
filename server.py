import html
import os
import re
import sqlite3
import threading
import time
from urllib.parse import quote

import telebot
from telebot import types

# ================= ТАНЗИМОТ =================
# Дар хостинг: тағйирёбандаи BOT_TOKEN-ро танзим кунед. Дар Pydroid: токенро дар ҷои дуюм нависед
TOKEN = next(
    (os.getenv(k) for k in ("BOT_TOKEN", "TELEGRAM_TOKEN", "8769343478:AAHh4Y6uhl8WVG3Jq5tvyA9vyQ63xM1zjXo", "TOKEN") if os.getenv(k)),
    "ТОКЕНИ_БОТИ_ТУ",
)
if ":" not in TOKEN:
    raise SystemExit("Токен ёфт нашуд: онро дар панели хостинг (BOT_TOKEN) ё дар хати TOKEN нависед.")
CHANNEL_ID = -1004379719940        # ID-и канал
CHANNEL_USERNAME = "@ali_dostaw"   # захира, агар ID кор накунад
CHANNEL_LINK = "https://t.me/ali_dostaw"
# ID-и Telegram-и админ(ҳо). ID-и худро аз @userinfobot гиред
ADMIN_IDS = [123456789]
# ============================================

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")


def esc(text):
    return html.escape(str(text), quote=False)


# Дар хостинг метавонед роҳи дигар диҳед (DB_PATH), масалан папкаи доимӣ
DB_FILE = os.getenv("DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "koryob.db"
)
PAGE_SIZE = 5
MAX_ADS_PER_USER = 10
MAX_PHOTOS = 5
AD_LIFETIME_DAYS = 15   # пас аз ин мӯҳлат эълон худаш нест мешавад

CAT_JOB = "job"
CAT_FLAT = "flat"
CAT_TITLE = {CAT_JOB: "💼 <b>Кор</b>", CAT_FLAT: "🏠 <b>Квартира</b>"}

BTN_CANCEL = "❌ Бекор кардан"
BTN_NO_LOCATION = "⏭ Бе харита"
BTN_SEND_LOCATION = "📍 Фиристодани ҷойгиршавии ман"

CITIES = [
    "Москва", "Санкт-Петербург", "Московская область", "Казань",
    "Екатеринбург", "Новосибирск", "Нижний Новгород", "Краснодар",
    "Самара", "Ростов-на-Дону", "Уфа", "Красноярск",
    "Челябинск", "Воронеж", "Пермь", "Тюмень",
]

# (калид, савол, дарозии максималӣ)
FIELDS = {
    CAT_JOB: [
        ("title", "💼 Номи кор (масалан: Курьер, Ошпаз, Сохтмончӣ):", 80),
        ("city", "📍 Шаҳрро аз тугмаҳо интихоб кунед ё худатон нависед:", 80),
        ("salary", "💰 Маош бо рубл (масалан: 60000 ₽ дар як моҳ ё 3000 ₽ дар як рӯз):", 60),
        ("contact", "📞 Рақами телефон (масалан: +7 900 123-45-67) ё @username:", 60),
        ("description", "📝 Шарҳи кӯтоҳ (талабот, соатҳои кор, хона/хӯрок ҳаст ё не):", 450),
    ],
    CAT_FLAT: [
        ("title", "🏠 Чӣ гуна эълон? (масалан: 2-хонагӣ, иҷора / ҳуҷра / фурӯш):", 80),
        ("city", "📍 Шаҳрро аз тугмаҳо интихоб кунед ё худатон нависед:", 80),
        ("salary", "💰 Нарх бо рубл (масалан: 35000 ₽ дар як моҳ):", 60),
        ("contact", "📞 Рақами телефон (масалан: +7 900 123-45-67) ё @username:", 60),
        ("description", "📝 Шарҳ (ошёна, мебел, ошхона, ба метро наздик ва ғайра):", 450),
    ],
}

LOCATION_PROMPT = (
    "🗺 Ҷой (манзил)-и эълонро нишон диҳед, то одамон дар харита бубинанд:\n\n"
    "• Агар ҳозир дар ҳамон ҷой бошед, «📍 Фиристодани ҷойгиршавии ман»-ро пахш кунед\n"
    "• Ё 📎 → «Ҷойгиршавӣ» → нуқтаро дар харита интихоб кунед\n"
    "• Ё манзилро бо матн нависед (масалан: ул. Тверская, д. 10)\n"
    "• Ё «⏭ Бе харита»-ро пахш кунед"
)

PHOTO_PROMPT = {
    CAT_JOB: "📷 Оё акси ҷои кор доред? То %d акс фиристед, баъд «✅ Тайёр»-ро пахш кунед.",
    CAT_FLAT: "📷 Оё акси квартира доред? То %d акс фиристед, баъд «✅ Тайёр»-ро пахш кунед.",
}

last_query = {}      # chat_id -> {"cat", "query", "city"}
post_state = {}      # user_id -> ҳолати гузоштани эълон
state_lock = threading.Lock()
sub_cache = {}       # user_id -> то кай обуна дуруст ҳисоб мешавад


# ---------- База ----------
def run(sql, params=(), fetch=None):
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        conn.commit()
        if fetch == "all":
            return cur.fetchall()
        if fetch == "one":
            return cur.fetchone()
        return cur.lastrowid
    finally:
        conn.close()


def init_db():
    run(
        """CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT, city TEXT, salary TEXT,
            contact TEXT, description TEXT,
            search_text TEXT,
            created_at INTEGER,
            category TEXT DEFAULT 'job',
            photos TEXT DEFAULT '',
            lat REAL, lon REAL,
            address TEXT DEFAULT ''
        )"""
    )
    cols = [r["name"] for r in run("PRAGMA table_info(jobs)", fetch="all")]
    if "category" not in cols:
        run("ALTER TABLE jobs ADD COLUMN category TEXT DEFAULT 'job'")
    if "photos" not in cols:
        run("ALTER TABLE jobs ADD COLUMN photos TEXT DEFAULT ''")
    if "lat" not in cols:
        run("ALTER TABLE jobs ADD COLUMN lat REAL")
    if "lon" not in cols:
        run("ALTER TABLE jobs ADD COLUMN lon REAL")
    if "address" not in cols:
        run("ALTER TABLE jobs ADD COLUMN address TEXT DEFAULT ''")
    run("CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)")


def cutoff_time():
    return int(time.time()) - AD_LIFETIME_DAYS * 86400


def fetch_page(cat, query, city, page):
    clauses, params = ["created_at > ?"], [cutoff_time()]
    if cat:
        clauses.append("category = ?")
        params.append(cat)
    if city:
        clauses.append("city = ?")
        params.append(city)
    if query:
        for w in query.lower().split():
            w = w.replace("%", "").replace("_", "")
            if w:
                clauses.append("search_text LIKE ?")
                params.append(f"%{w}%")
    where = "WHERE " + " AND ".join(clauses)
    total = run(f"SELECT COUNT(*) AS n FROM jobs {where}", params, "one")["n"]
    rows = run(
        f"SELECT * FROM jobs {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [PAGE_SIZE, page * PAGE_SIZE],
        "all",
    )
    return total, rows


# ---------- Ёвар ----------
def g(job, key, default=None):
    """Хондани майдон аз sqlite3.Row ё dict."""
    try:
        v = job[key]
    except (KeyError, IndexError):
        return default
    return default if v is None else v


def ago(created_at):
    if not created_at:
        return "имрӯз"
    days = int((time.time() - created_at) // 86400)
    if days <= 0:
        return "имрӯз"
    if days == 1:
        return "дирӯз"
    return f"{days} рӯз пеш"


def hashtag(text):
    return "#" + re.sub(r"\W+", "_", str(text).strip()).strip("_")


def tg_link(contact):
    m = re.match(r"^@([A-Za-z0-9_]{4,32})$", (contact or "").strip())
    return f"https://t.me/{m.group(1)}" if m else None


# ---------- Клавиатураҳо (inline) ----------
def menu_markup():
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("💼 Кор ҷустан", callback_data="m:job"),
        types.InlineKeyboardButton("🏠 Квартира ҷустан", callback_data="m:flat"),
    )
    markup.row(
        types.InlineKeyboardButton("➕ Эълон гузоштан", callback_data="m:post"),
        types.InlineKeyboardButton("📋 Эълонҳои ман", callback_data="m:my"),
    )
    markup.add(types.InlineKeyboardButton("📢 Канали мо", url=CHANNEL_LINK))
    return markup


def back_markup(target="home"):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Меню", callback_data=f"m:{target}"))
    return markup


def cat_markup(cat):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("🆕 Эълонҳои нав", callback_data=f"s:{cat}:new"),
        types.InlineKeyboardButton("🔎 Бо калима", callback_data=f"s:{cat}:q"),
    )
    markup.add(types.InlineKeyboardButton("📍 Аз рӯи шаҳр", callback_data=f"s:{cat}:city"))
    markup.add(types.InlineKeyboardButton("⬅️ Меню", callback_data="m:home"))
    return markup


def city_markup(prefix, back=None):
    """prefix: 'c:job' (ҷустуҷӯ) ё 'pc' (гузоштани эълон)."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(*[
        types.InlineKeyboardButton(c, callback_data=f"{prefix}:{i}")
        for i, c in enumerate(CITIES)
    ])
    if back:
        markup.add(types.InlineKeyboardButton("⬅️ Қафо", callback_data=back))
    else:
        markup.add(types.InlineKeyboardButton(BTN_CANCEL, callback_data="pcancel"))
    return markup


def cancel_inline():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(BTN_CANCEL, callback_data="pcancel"))
    return markup


def photo_inline():
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Тайёр", callback_data="pphoto:done"),
        types.InlineKeyboardButton("⏭ Бе акс", callback_data="pphoto:skip"),
    )
    markup.add(types.InlineKeyboardButton(BTN_CANCEL, callback_data="pcancel"))
    return markup


def nav_markup(page, pages):
    markup = types.InlineKeyboardMarkup()
    row = []
    if page > 0:
        row.append(types.InlineKeyboardButton("◀️ Қафо", callback_data=f"pg:{page - 1}"))
    row.append(types.InlineKeyboardButton(f"📄 {page + 1}/{pages}", callback_data="noop"))
    if page + 1 < pages:
        row.append(types.InlineKeyboardButton("Минбаъд ▶️", callback_data=f"pg:{page + 1}"))
    markup.row(*row)
    markup.add(types.InlineKeyboardButton("⬅️ Меню", callback_data="m:home"))
    return markup


def location_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton(BTN_SEND_LOCATION, request_location=True))
    markup.add(BTN_NO_LOCATION)
    markup.add(BTN_CANCEL)
    return markup


# ---------- Корт (карточка)-и эълон ----------
def map_links(job):
    """(Google, Яндекс) пайвандҳои харита, ё None."""
    lat, lon = g(job, "lat"), g(job, "lon")
    address = (g(job, "address", "") or "").strip()
    if lat is not None and lon is not None:
        return (
            f"https://www.google.com/maps/search/?api=1&query={lat},{lon}",
            f"https://yandex.ru/maps/?pt={lon},{lat}&z=16&l=map",
        )
    if address:
        q = quote(f"{g(job, 'city', '')}, {address}")
        return (
            f"https://www.google.com/maps/search/?api=1&query={q}",
            f"https://yandex.ru/maps/?text={q}",
        )
    return None


def job_markup(job, owner=False, admin=False):
    markup = types.InlineKeyboardMarkup()
    has = False
    link = tg_link(g(job, "contact", ""))
    if link:
        markup.add(types.InlineKeyboardButton("💬 Навиштан", url=link))
        has = True
    maps = map_links(job)
    if maps:
        markup.row(
            types.InlineKeyboardButton("🗺 Google Карта", url=maps[0]),
            types.InlineKeyboardButton("🗺 Яндекс Карта", url=maps[1]),
        )
        has = True
    if owner:
        markup.add(types.InlineKeyboardButton("🗑 Нест кардан", callback_data=f"del:{job['id']}"))
        has = True
    if admin:
        markup.row(
            types.InlineKeyboardButton("🗑 Нест (админ)", callback_data=f"adel:{job['id']}"),
            types.InlineKeyboardButton("🚫 Бан", callback_data=f"aban:{job['user_id']}"),
        )
        has = True
    return markup if has else None


def fmt(job):
    flat = g(job, "category", CAT_JOB) == CAT_FLAT
    icon = "🏠" if flat else "💼"
    lines = [f"{icon} <b>{esc(job['title'])}</b>", "", f"📍 {esc(job['city'])}"]
    address = (g(job, "address", "") or "").strip()
    if address:
        lines.append(f"🏘 {esc(address)}")
    elif g(job, "lat") is not None:
        lines.append("🗺 Ҷой дар харита нишон дода шудааст")
    lines += [
        f"💰 <b>{esc(job['salary'])}</b>",
        f"📞 {esc(job['contact'])}",
        "",
        f"📝 {esc(job['description'])}",
        "",
        f"{hashtag('квартира' if flat else 'кор')} {hashtag(job['city'])} · 🕒 {ago(g(job, 'created_at'))}",
    ]
    return "\n".join(lines)


def send_job(chat_id, job, owner=False, admin=False):
    """Эълонро бо акс (1-5 дона) ё бе акс, бо тугмаҳо мефиристад."""
    text = fmt(job)
    if owner:
        try:
            left = AD_LIFETIME_DAYS * 86400 - (time.time() - job["created_at"])
            days = max(1, int(-(-left // 86400)))
            text += f"\n\n⏳ Боқӣ мондааст: {days} рӯз"
        except Exception:
            pass
    if admin:
        text += f"\n\n🛡 №{job['id']} · корбар: {job['user_id']}"
    markup = job_markup(job, owner, admin)
    photos = [p for p in (g(job, "photos", "") or "").split(",") if p]
    short = len(text) <= 1000          # ҳадди caption дар Telegram: 1024
    try:
        if not photos:
            bot.send_message(chat_id, text, reply_markup=markup)
        elif len(photos) == 1:
            if short:
                bot.send_photo(chat_id, photos[0], caption=text, parse_mode="HTML", reply_markup=markup)
            else:
                bot.send_photo(chat_id, photos[0])
                bot.send_message(chat_id, text, reply_markup=markup)
        else:
            media = [
                types.InputMediaPhoto(
                    p,
                    caption=text if (i == 0 and short) else None,
                    parse_mode="HTML" if (i == 0 and short) else None,
                )
                for i, p in enumerate(photos)
            ]
            bot.send_media_group(chat_id, media)
            if not short:
                bot.send_message(chat_id, text, reply_markup=markup)
            elif markup:
                bot.send_message(chat_id, "👆 Эълони боло", reply_markup=markup)
    except Exception as e:
        print("Хатои фиристодани эълон:", e)
        bot.send_message(chat_id, text, reply_markup=markup)


# ---------- Санҷиши обуна ва бан ----------
def check_member(user_id):
    """True/False, ё None агар санҷиш имконнопазир бошад."""
    for chat in (CHANNEL_ID, CHANNEL_USERNAME):
        try:
            member = bot.get_chat_member(chat, user_id)
            return member.status in ("member", "administrator", "creator")
        except Exception as e:
            print("Хатои санҷиши обуна (%s): %s" % (chat, e))
    return None


def sub_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📢 Обуна шудан", url=CHANNEL_LINK))
    markup.add(types.InlineKeyboardButton("✅ Санҷидан", callback_data="check_sub"))
    return markup


def ensure_sub(chat_id, user_id):
    """True агар корбар обуна бошад; вагарна паёми обуна мефиристад."""
    if not is_admin(user_id) and is_banned(user_id):
        bot.send_message(chat_id, "🚫 Шумо аз истифодаи бот манъ шудаед.")
        return False
    now = time.time()
    if sub_cache.get(user_id, 0) > now:
        return True
    status = check_member(user_id)
    if status:
        sub_cache[user_id] = now + 120
        return True
    if status is None:
        bot.send_message(
            chat_id,
            "⚠️ Санҷиши обуна кор намекунад. Боварӣ ҳосил кунед, ки бот "
            "дар канал АДМИН аст.",
        )
    else:
        bot.send_message(
            chat_id,
            "📢 Барои истифодаи бот аввал ба канали мо обуна шавед, "
            "баъд тугмаи «Санҷидан»-ро пахш кунед.",
            reply_markup=sub_markup(),
        )
    return False


def welcome_text(name):
    return (
        f"👋 <b>Салом, {esc(name or 'дӯст')}!</b>\n\n"
        "🇷🇺 <b>КОРЁБ</b> — бот барои муҳоҷирон дар Русия.\n"
        "💼 Кор ва 🏠 квартира ёбед, ё эълони худро ройгон гузоред.\n\n"
        "Интихоб кунед 👇"
    )


def show_screen(call, text, markup=None):
    """Паёми ҳозираро иваз мекунад (чат тоза мемонад)."""
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup)


def guard(call):
    """Ба callback ҷавоб медиҳад, қадами интизориро тоза мекунад, обунаро месанҷад."""
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    return ensure_sub(call.message.chat.id, call.from_user.id)


@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def on_check_sub(call):
    status = check_member(call.from_user.id)
    if status:
        sub_cache[call.from_user.id] = time.time() + 120
        bot.answer_callback_query(call.id, "Ташаккур! Обуна тасдиқ шуд ✅")
        show_screen(call, welcome_text(call.from_user.first_name), menu_markup())
    elif status is None:
        bot.answer_callback_query(call.id, "Бот дар канал админ нест.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "Шумо ҳанӯз обуна нашудаед ❌", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data == "noop")
def on_noop(call):
    bot.answer_callback_query(call.id)


# ---------- Фармонҳо ва менюи асосӣ ----------
@bot.message_handler(commands=["start", "help", "menu"])
def start(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    # клавиатураи кӯҳнаи поёнро тоза мекунем
    try:
        tmp = bot.send_message(message.chat.id, "👋", reply_markup=types.ReplyKeyboardRemove())
        bot.delete_message(message.chat.id, tmp.message_id)
    except Exception:
        pass
    if ensure_sub(message.chat.id, message.from_user.id):
        bot.send_message(
            message.chat.id,
            welcome_text(message.from_user.first_name),
            reply_markup=menu_markup(),
        )


@bot.message_handler(commands=["cancel"])
def cancel_cmd(message):
    with state_lock:
        post_state.pop(message.from_user.id, None)
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bot.send_message(message.chat.id, "❌ Бекор шуд.", reply_markup=types.ReplyKeyboardRemove())
    bot.send_message(message.chat.id, "Меню 👇", reply_markup=menu_markup())


@bot.callback_query_handler(func=lambda c: c.data.startswith("m:"))
def on_menu(call):
    if not guard(call):
        return
    target = call.data[2:]
    chat_id = call.message.chat.id
    if target == "home":
        show_screen(call, welcome_text(call.from_user.first_name), menu_markup())
    elif target in (CAT_JOB, CAT_FLAT):
        show_screen(call, f"{CAT_TITLE[target]}\n\nЧӣ тавр меҷӯед?", cat_markup(target))
    elif target == "post":
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("💼 Эълони кор", callback_data="post:job"),
            types.InlineKeyboardButton("🏠 Эълони квартира", callback_data="post:flat"),
        )
        markup.add(types.InlineKeyboardButton("⬅️ Меню", callback_data="m:home"))
        show_screen(call, "➕ <b>Эълони нав</b>\n\nКадом навъро мегузоред?", markup)
    elif target == "my":
        my_jobs(chat_id, call.from_user.id)


# ---------- Ҷустуҷӯ ----------
@bot.callback_query_handler(func=lambda c: c.data.startswith("s:"))
def on_search_menu(call):
    if not guard(call):
        return
    _, cat, action = call.data.split(":")
    chat_id = call.message.chat.id
    if action == "new":
        last_query[chat_id] = {"cat": cat, "query": None, "city": None}
        show_page(chat_id, 0)
    elif action == "city":
        show_screen(call, f"{CAT_TITLE[cat]}\n\n📍 Шаҳрро интихоб кунед:", city_markup(f"c:{cat}", back=f"m:{cat}"))
    elif action == "q":
        if cat == CAT_JOB:
            prompt = "✍️ Нависед, ки чӣ гуна кор меҷӯед.\nМасалан: <i>Курьер Москва</i>"
        else:
            prompt = "✍️ Нависед, ки чӣ гуна квартира меҷӯед.\nМасалан: <i>2-хонагӣ Москва иҷора</i>"
        msg = bot.send_message(chat_id, prompt)
        bot.register_next_step_handler(msg, got_search, cat)


@bot.callback_query_handler(func=lambda c: c.data.startswith("c:"))
def on_city_search(call):
    if not guard(call):
        return
    _, cat, idx = call.data.split(":")
    last_query[call.message.chat.id] = {"cat": cat, "query": None, "city": CITIES[int(idx)]}
    show_page(call.message.chat.id, 0)


def got_search(message, cat):
    text = (message.text or "").strip()
    chat_id = message.chat.id
    if text.startswith("/"):
        bot.process_new_messages([message])   # фармони дигар (масалан /start)
        return
    if not text:
        bot.send_message(chat_id, "⚠️ Лутфан, матн нависед.", reply_markup=back_markup())
        return
    last_query[chat_id] = {"cat": cat, "query": text, "city": None}
    show_page(chat_id, 0)


def show_page(chat_id, page):
    q = last_query.get(chat_id)
    if not q:
        bot.send_message(chat_id, "Ҷустуҷӯро аз нав оғоз кунед.", reply_markup=back_markup())
        return
    total, rows = fetch_page(q["cat"], q["query"], q["city"], page)
    if not rows:
        bot.send_message(
            chat_id,
            "😕 Эълон ёфт нашуд. Калимаи дигар ё шаҳри дигарро санҷед.",
            reply_markup=back_markup(),
        )
        return
    admin = is_admin(chat_id)
    for job in rows:
        send_job(chat_id, job, admin=admin)
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    bot.send_message(
        chat_id,
        f"Ёфт шуд: <b>{total}</b> эълон",
        reply_markup=nav_markup(page, pages),
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("pg:"))
def on_page(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    page = int(call.data.split(":")[1])
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass
    show_page(chat_id, page)


# ---------- Эълонҳои ман ----------
def my_jobs(chat_id, user_id):
    rows = run(
        "SELECT * FROM jobs WHERE user_id = ? AND created_at > ? ORDER BY id DESC",
        (user_id, cutoff_time()),
        "all",
    )
    if not rows:
        bot.send_message(chat_id, "Шумо ҳанӯз эълони фаъол надоред.", reply_markup=back_markup())
        return
    for job in rows:
        send_job(chat_id, job, owner=True)
    bot.send_message(chat_id, f"📋 Эълонҳои шумо: <b>{len(rows)}</b>", reply_markup=back_markup())


@bot.callback_query_handler(func=lambda c: c.data.startswith("del:"))
def on_delete(call):
    job_id = int(call.data.split(":")[1])
    row = run("SELECT user_id FROM jobs WHERE id = ?", (job_id,), "one")
    if not row or row["user_id"] != call.from_user.id:
        bot.answer_callback_query(call.id, "Ин эълон ёфт нашуд.")
        return
    run("DELETE FROM jobs WHERE id = ?", (job_id,))
    bot.answer_callback_query(call.id, "Нест карда шуд ✅")
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass


# ---------- Гузоштани эълон (бо ҳолат) ----------
def new_state(cat):
    return {"category": cat, "step": 0, "data": {}, "photos": [],
            "lat": None, "lon": None, "address": ""}


def st_to_job(st):
    return dict(
        st["data"], category=st["category"], photos=",".join(st["photos"]),
        lat=st["lat"], lon=st["lon"], address=st["address"],
    )


def step_label(st):
    total = len(FIELDS[st["category"]]) + 2
    return f"<b>Қадами {min(st['step'] + 1, total)}/{total}</b>\n"


def ask_current(chat_id, st):
    fields = FIELDS[st["category"]]
    n = len(fields)
    step = st["step"]
    if step < n:
        key, prompt, _ = fields[step]
        markup = city_markup("pc") if key == "city" else cancel_inline()
        bot.send_message(chat_id, step_label(st) + prompt, reply_markup=markup)
    elif step == n:
        bot.send_message(chat_id, step_label(st) + LOCATION_PROMPT, reply_markup=location_keyboard())
    elif step == n + 1:
        bot.send_message(
            chat_id,
            step_label(st) + PHOTO_PROMPT[st["category"]] % MAX_PHOTOS,
            reply_markup=photo_inline(),
        )
    else:
        bot.send_message(chat_id, "👀 <b>Эълони шумо чунин намоён мешавад:</b>")
        send_job(chat_id, st_to_job(st))
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Нашр кардан", callback_data="pub:yes"),
            types.InlineKeyboardButton("🔄 Аз нав", callback_data="pub:redo"),
        )
        markup.add(types.InlineKeyboardButton(BTN_CANCEL, callback_data="pub:no"))
        bot.send_message(chat_id, "Эълонро нашр кунем?", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("post:"))
def on_post_category(call):
    if not guard(call):
        return
    chat_id, user_id = call.message.chat.id, call.from_user.id
    cat = call.data.split(":")[1]
    if cat not in FIELDS:
        return
    count = run(
        "SELECT COUNT(*) AS n FROM jobs WHERE user_id = ? AND created_at > ?",
        (user_id, cutoff_time()),
        "one",
    )["n"]
    if count >= MAX_ADS_PER_USER:
        show_screen(
            call,
            f"⚠️ Шумо аллакай {MAX_ADS_PER_USER} эълон доред. Аввал як эълони кӯҳнаро нест кунед.",
            back_markup(),
        )
        return
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass
    st = new_state(cat)
    with state_lock:
        post_state[user_id] = st
    ask_current(chat_id, st)


@bot.callback_query_handler(func=lambda c: c.data == "pcancel")
def on_post_cancel(call):
    bot.answer_callback_query(call.id)
    with state_lock:
        post_state.pop(call.from_user.id, None)
    show_screen(call, "❌ Бекор шуд.", back_markup())


@bot.callback_query_handler(func=lambda c: c.data.startswith("pc:"))
def on_post_city(call):
    """Интихоби шаҳр бо тугма ҳангоми гузоштани эълон."""
    bot.answer_callback_query(call.id)
    user_id, chat_id = call.from_user.id, call.message.chat.id
    idx = int(call.data.split(":")[1])
    with state_lock:
        st = post_state.get(user_id)
        fields = FIELDS[st["category"]] if st else []
        if not st or st["step"] >= len(fields) or fields[st["step"]][0] != "city":
            return
        st["data"]["city"] = CITIES[idx]
        st["step"] += 1
    try:
        bot.edit_message_text(f"📍 Шаҳр: <b>{esc(CITIES[idx])}</b>", chat_id, call.message.message_id)
    except Exception:
        pass
    ask_current(chat_id, st)


@bot.callback_query_handler(func=lambda c: c.data.startswith("pphoto:"))
def on_post_photo_buttons(call):
    bot.answer_callback_query(call.id)
    user_id, chat_id = call.from_user.id, call.message.chat.id
    action = call.data.split(":")[1]
    with state_lock:
        st = post_state.get(user_id)
        if not st or st["step"] != len(FIELDS[st["category"]]) + 1:
            return
        if action == "skip":
            st["photos"] = []
        st["step"] += 1
    ask_current(chat_id, st)


@bot.callback_query_handler(func=lambda c: c.data.startswith("pub:"))
def on_publish(call):
    bot.answer_callback_query(call.id)
    user_id, chat_id = call.from_user.id, call.message.chat.id
    action = call.data.split(":")[1]
    st = None
    with state_lock:
        cur = post_state.get(user_id)
        if cur and cur["step"] == len(FIELDS[cur["category"]]) + 2:
            if action == "redo":
                st = new_state(cur["category"])
                post_state[user_id] = st
            else:
                st = post_state.pop(user_id)
    if st is None:
        return
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass
    if action == "yes":
        save_job(chat_id, user_id, st)
    elif action == "redo":
        ask_current(chat_id, st)
    else:
        bot.send_message(chat_id, "❌ Бекор шуд.", reply_markup=back_markup())


@bot.message_handler(
    content_types=["text", "photo", "location"],
    func=lambda m: m.from_user.id in post_state,
)
def on_post_state(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    text = (message.text or "").strip() if message.content_type == "text" else ""

    if text in (BTN_CANCEL, "/cancel", "/start"):
        with state_lock:
            post_state.pop(user_id, None)
        if text == "/start":
            start(message)
        else:
            bot.send_message(chat_id, "❌ Бекор шуд.", reply_markup=types.ReplyKeyboardRemove())
            bot.send_message(chat_id, "Меню 👇", reply_markup=menu_markup())
        return

    action, reply, st = None, None, None
    with state_lock:
        st = post_state.get(user_id)
        if st is None:
            return
        fields = FIELDS[st["category"]]
        n = len(fields)

        if st["step"] < n:                      # --- саволҳои матнӣ
            key, _, max_len = fields[st["step"]]
            if not text or text.startswith("/"):
                action, reply = "say", "⚠️ Лутфан, матн нависед."
            elif len(text) > max_len:
                action, reply = "say", f"⚠️ Матн хеле дароз аст (ҳадди аксар {max_len} ҳарф)."
            else:
                if key == "city":    # «москва» -> «Москва» (барои филтри шаҳр)
                    text = next((c for c in CITIES if c.lower() == text.lower()), text)
                st["data"][key] = text
                st["step"] += 1
                action = "ask"

        elif st["step"] == n:                   # --- ҷой / харита
            ack = None
            if message.content_type == "location":
                st["lat"] = message.location.latitude
                st["lon"] = message.location.longitude
                ack = "📍 Ҷой қабул шуд ✅"
            elif text == BTN_NO_LOCATION:
                ack = "⏭ Бе харита"
            elif text and not text.startswith("/"):
                if len(text) > 120:
                    action, reply = "say_loc", "⚠️ Манзил хеле дароз аст (ҳадди аксар 120 ҳарф)."
                else:
                    st["address"] = text
                    ack = "🏘 Манзил қабул шуд ✅"
            else:
                action = "say_loc"
                reply = "🗺 Ҷойгиршавӣ фиристед, манзилро нависед ё «⏭ Бе харита»-ро пахш кунед."
            if ack:
                st["step"] += 1
                action, reply = "ack_ask", ack

        elif st["step"] == n + 1:               # --- акс
            if message.content_type == "photo":
                if len(st["photos"]) < MAX_PHOTOS:
                    st["photos"].append(message.photo[-1].file_id)
                if len(st["photos"]) >= MAX_PHOTOS:
                    st["step"] += 1
                    action = "ask"
                else:
                    gid = message.media_group_id
                    if gid is None or gid != st.get("last_group"):
                        st["last_group"] = gid
                        action = "say_photo"
                        reply = "📷 Акс қабул шуд. Боз акс фиристед ё «✅ Тайёр»-ро пахш кунед."
            else:
                action = "say_photo"
                reply = "📷 Акс фиристед, ё тугмаҳои поёнро пахш кунед."

        else:                                   # --- пешнамоиш
            action, reply = "say", "👆 Лутфан, тугмаҳои «Нашр кардан» ё «Бекор кардан»-ро пахш кунед."

    if action == "say":
        bot.send_message(chat_id, reply)
    elif action == "say_loc":
        bot.send_message(chat_id, reply, reply_markup=location_keyboard())
    elif action == "say_photo":
        bot.send_message(chat_id, reply, reply_markup=photo_inline())
    elif action == "ack_ask":
        bot.send_message(chat_id, reply, reply_markup=types.ReplyKeyboardRemove())
        ask_current(chat_id, st)
    elif action == "ask":
        ask_current(chat_id, st)


def save_job(chat_id, user_id, st):
    data, cat = st["data"], st["category"]
    photos = ",".join(st["photos"])
    lat, lon = st.get("lat"), st.get("lon")
    address = st.get("address", "")
    search_text = f"{data['title']} {data['city']} {address} {data['description']}".lower()
    run(
        """INSERT INTO jobs
           (user_id, title, city, salary, contact, description,
            search_text, created_at, category, photos, lat, lon, address)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id, data["title"], data["city"], data["salary"],
            data["contact"], data["description"], search_text,
            int(time.time()), cat, photos, lat, lon, address,
        ),
    )
    bot.send_message(
        chat_id,
        f"✅ <b>Эълони шумо нашр шуд!</b>\nОн {AD_LIFETIME_DAYS} рӯз дар бот мемонад.",
        reply_markup=back_markup(),
    )


# ---------- Панели админ ----------
def is_admin(user_id):
    return user_id in ADMIN_IDS


def is_banned(user_id):
    return run("SELECT 1 FROM banned WHERE user_id = ?", (user_id,), "one") is not None


def admin_delete_job(row):
    """Эълонро нест мекунад ва соҳибашро огоҳ мекунад."""
    run("DELETE FROM jobs WHERE id = ?", (row["id"],))
    try:
        bot.send_message(
            row["user_id"],
            f"⚠️ Эълони шумо «{esc(row['title'])}» аз тарафи админ нест карда шуд, "
            "чунки қоидаҳоро вайрон мекард.",
        )
    except Exception:
        pass


def ban_user(user_id):
    run("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (user_id,))
    n = run("SELECT COUNT(*) AS n FROM jobs WHERE user_id = ?", (user_id,), "one")["n"]
    run("DELETE FROM jobs WHERE user_id = ?", (user_id,))
    return n


def admin_arg(message):
    """Рақами баъд аз фармон: /del 12 -> 12, ё None."""
    parts = (message.text or "").split()
    if len(parts) >= 2 and parts[1].lstrip("-").isdigit():
        return int(parts[1])
    return None


@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if not is_admin(message.from_user.id):
        return
    total = run("SELECT COUNT(*) AS n FROM jobs", fetch="one")["n"]
    jobs = run("SELECT COUNT(*) AS n FROM jobs WHERE category = 'job'", fetch="one")["n"]
    flats = run("SELECT COUNT(*) AS n FROM jobs WHERE category = 'flat'", fetch="one")["n"]
    users = run("SELECT COUNT(DISTINCT user_id) AS n FROM jobs", fetch="one")["n"]
    banned = run("SELECT COUNT(*) AS n FROM banned", fetch="one")["n"]
    bot.send_message(
        message.chat.id,
        "🛡 <b>Панели админ</b>\n\n"
        f"📊 Эълонҳои фаъол: {total} (💼 {jobs} · 🏠 {flats})\n"
        f"👥 Соҳибони эълон: {users}\n"
        f"🚫 Манъшудагон: {banned}\n\n"
        "<b>Фармонҳо:</b>\n"
        "/last — 10 эълони охирин (бо тугмаи нест кардан)\n"
        "/del 12 — эълони №12-ро нест кардан\n"
        "/ban 123456 — манъ кардани корбар ва нест кардани эълонҳояш\n"
        "/unban 123456 — рафъи манъ\n\n"
        "Дар натиҷаи ҷустуҷӯ низ ба ҳар эълон тугмаҳои админ илова мешавад.",
    )


@bot.message_handler(commands=["last"])
def admin_last(message):
    if not is_admin(message.from_user.id):
        return
    rows = run("SELECT * FROM jobs ORDER BY id DESC LIMIT 10", fetch="all")
    if not rows:
        bot.send_message(message.chat.id, "Эълон нест.")
        return
    for job in rows:
        send_job(message.chat.id, job, admin=True)


@bot.message_handler(commands=["del"])
def admin_del_cmd(message):
    if not is_admin(message.from_user.id):
        return
    job_id = admin_arg(message)
    if job_id is None:
        bot.send_message(message.chat.id, "Истифода: /del 12")
        return
    row = run("SELECT * FROM jobs WHERE id = ?", (job_id,), "one")
    if not row:
        bot.send_message(message.chat.id, "Эълон бо ин рақам ёфт нашуд.")
        return
    admin_delete_job(row)
    bot.send_message(message.chat.id, f"🗑 Эълони №{job_id} нест карда шуд.")


@bot.message_handler(commands=["ban"])
def admin_ban_cmd(message):
    if not is_admin(message.from_user.id):
        return
    uid = admin_arg(message)
    if uid is None:
        bot.send_message(message.chat.id, "Истифода: /ban 123456789")
        return
    if is_admin(uid):
        bot.send_message(message.chat.id, "Админро манъ кардан мумкин нест.")
        return
    n = ban_user(uid)
    bot.send_message(message.chat.id, f"🚫 Корбар {uid} манъ шуд. Эълонҳои нестшуда: {n}.")


@bot.message_handler(commands=["unban"])
def admin_unban_cmd(message):
    if not is_admin(message.from_user.id):
        return
    uid = admin_arg(message)
    if uid is None:
        bot.send_message(message.chat.id, "Истифода: /unban 123456789")
        return
    run("DELETE FROM banned WHERE user_id = ?", (uid,))
    bot.send_message(message.chat.id, f"✅ Манъи корбар {uid} рафъ шуд.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("adel:"))
def on_admin_delete(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Танҳо барои админ.")
        return
    job_id = int(call.data.split(":")[1])
    row = run("SELECT * FROM jobs WHERE id = ?", (job_id,), "one")
    if not row:
        bot.answer_callback_query(call.id, "Аллакай нест шудааст.")
        return
    admin_delete_job(row)
    bot.answer_callback_query(call.id, "Нест карда шуд ✅")
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("aban:"))
def on_admin_ban(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Танҳо барои админ.")
        return
    uid = int(call.data.split(":")[1])
    if is_admin(uid):
        bot.answer_callback_query(call.id, "Админро манъ кардан мумкин нест.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Ҳа, манъ кун", callback_data=f"aban2:{uid}"),
        types.InlineKeyboardButton("↩️ Не", callback_data="acancel"),
    )
    bot.send_message(
        call.message.chat.id,
        f"Корбар {uid}-ро манъ карда, ҳамаи эълонҳояшро нест кунем?",
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("aban2:"))
def on_admin_ban_confirm(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Танҳо барои админ.")
        return
    uid = int(call.data.split(":")[1])
    if is_admin(uid):
        return
    n = ban_user(uid)
    bot.answer_callback_query(call.id, "Манъ шуд ✅")
    try:
        bot.edit_message_text(
            f"🚫 Корбар {uid} манъ шуд. Эълонҳои нестшуда: {n}.",
            call.message.chat.id,
            call.message.message_id,
        )
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data == "acancel")
def on_admin_cancel(call):
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass


# ---------- Ҳар матни дигар = ҷустуҷӯ дар ҳамаи эълонҳо ----------
@bot.message_handler(content_types=["text"])
def any_text(message):
    text = message.text.strip()
    if text.startswith("/"):
        return
    if not ensure_sub(message.chat.id, message.from_user.id):
        return
    last_query[message.chat.id] = {"cat": None, "query": text, "city": None}
    show_page(message.chat.id, 0)


# ---------- Нест кардани эълонҳои кӯҳна ----------
def cleanup_expired():
    rows = run(
        "SELECT id, user_id, title FROM jobs WHERE created_at <= ?",
        (cutoff_time(),),
        "all",
    )
    for r in rows:
        run("DELETE FROM jobs WHERE id = ?", (r["id"],))
        try:
            bot.send_message(
                r["user_id"],
                f"⌛ Мӯҳлати эълони «{esc(r['title'])}» ({AD_LIFETIME_DAYS} рӯз) гузашт "
                "ва он нест шуд.\nМетавонед эълони нав гузоред: /start",
            )
        except Exception:
            pass   # корбар бот-ро бастааст ё дигар хато
    return len(rows)


def cleanup_loop():
    while True:
        try:
            n = cleanup_expired()
            if n:
                print(f"Нест карда шуд: {n} эълони кӯҳна")
        except Exception as e:
            print("Хатои тозакунӣ:", e)
        time.sleep(3600)   # ҳар соат


if __name__ == "__main__":
    init_db()
    try:
        bot.set_my_commands([
            types.BotCommand("start", "🏠 Менюи асосӣ"),
            types.BotCommand("cancel", "❌ Бекор кардан"),
        ])
    except Exception as e:
        print("set_my_commands:", e)
    threading.Thread(target=cleanup_loop, daemon=True).start()
    print("Бот кор мекунад...")
    bot.infinity_polling(skip_pending=True)
