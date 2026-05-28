"""
Telegram-бот «Гид для студентов по Ростову»
Целевая аудитория: студенты ЮФУ, факультет ИВТиПТ
Библиотека: python-telegram-bot 20.x
"""

import logging
import math
import sqlite3
from datetime import datetime, time

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ─── Логирование ─────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── КОНФИГУРАЦИЯ ─────────────────────────────────
TOKEN =         
ADMIN_CHAT_ID = 573760085                  
# ─────────────────────────────────────────────────────────────────────────────

DB_PATH = "bot.db"

# Временное хранилище выбранной категории (до получения геолокации)
user_category: dict[int, str] = {}

# ─── Состояния ConversationHandler ───────────────────────────────────────────
SUGGEST_NAME, SUGGEST_ADDR, SUGGEST_CAT = range(3)
REVIEW_CHOOSE_PLACE, REVIEW_RATING, REVIEW_TEXT = range(10, 13)
SCHEDULE_CHOOSE = 20
NOTIF_CHOOSE_COURSE = 30
LOCATION_WAIT = 40
AP_NAME, AP_CAT, AP_ADDR, AP_LAT, AP_LON, AP_DESC = range(50, 56)
AF_Q, AF_A = range(60, 62)
APH_NAME, APH_PHONE, APH_DESC = range(70, 73)
AS_COURSE, AS_SUBJ, AS_TEACHER, AS_CONTACT = range(80, 84)
AH_NAME, AH_TG, AH_INFO = range(90, 93)


# ─── Вспомогательные функции ──────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние между двумя точками в километрах."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def yandex_maps_url(lat: float, lon: float) -> str:
    return f"https://yandex.ru/maps/?pt={lon},{lat}&z=17"


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_CHAT_ID


def main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        ["🍽️ Где поесть рядом", "☕ Кофейни с розетками"],
        ["📚 Печать / канцелярия", "🏧 Другое"],
        ["🧠 Лайфхаки + помощь", "⭐ Отзывы и рейтинги"],
        ["💡 Предложить место", "📍 Рядом со мной"],
        ["📅 Расписание", "🔔 Уведомления"],
        ["🗺️ Карта корпусов ЮФУ", "📞 Важные номера"],
        ["❓ FAQ"],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


# ─── Инициализация базы данных ────────────────────────────────────────────────

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            address TEXT,
            latitude REAL,
            longitude REAL,
            description TEXT,
            rating_avg REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            text TEXT,
            date TEXT
        );

        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course INTEGER NOT NULL,
            subject TEXT NOT NULL,
            teacher_name TEXT,
            teacher_contact TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            course INTEGER DEFAULT 1,
            notifications_enabled INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            place_name TEXT,
            place_address TEXT,
            category TEXT,
            status TEXT DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS faq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS important_phones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS helpers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            tg_username TEXT,
            info TEXT
        );
    """)
    conn.commit()
    _seed_data(conn)
    conn.close()


def _seed_data(conn: sqlite3.Connection):
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM places")
    if cur.fetchone()[0] == 0:
        places = [
            ("Столовая ЮФУ (ДГТУ)", "еда", "пер. Гвардейский", 47.229, 39.709, "Вкусно и недорого", 4.2),
            ("Burger King", "еда", "пр. Будённовский", 47.226, 39.712, "Бургеры и снеки", 4.0),
            ("Теремок", "еда", "ул. Большая Садовая", 47.223, 39.708, "Блины и каши", 4.3),
            ("Додо Пицца", "еда", "ул. Пушкинская", 47.228, 39.715, "Свежая пицца", 4.5),
            ("Кофе Хауз", "кофейни", "ул. Горького", 47.225, 39.710, "Есть розетки и Wi-Fi", 4.4),
            ("Сладкоежка", "кофейни", "пр. Соколова", 47.230, 39.714, "Уютная кофейня", 4.1),
            ("Копицентр у ЮФУ", "печать", "ул. Большая Садовая", 47.227, 39.711, "Печать, ламинирование, переплёт", 4.3),
            ("Аптека Русь", "другое", "ул. Красноармейская", 47.226, 39.709, "Лекарства, работает допоздна", 4.5),
            ("Банкомат Сбербанка", "другое", "ул. Пушкинская", 47.228, 39.714, "Без комиссии для клиентов СБ", 4.0),
            ("Прачечная Чистота", "другое", "ул. Горького", 47.229, 39.712, "Самообслуживание", 3.8),
        ]
        cur.executemany(
            "INSERT INTO places (name,category,address,latitude,longitude,description,rating_avg) VALUES (?,?,?,?,?,?,?)",
            places,
        )

    cur.execute("SELECT COUNT(*) FROM schedule")
    if cur.fetchone()[0] == 0:
        schedule = [
            (1, "Программирование", "Петров И.И.", "@petrov"),
            (1, "Математика", "Сидорова А.А.", "@sidorova"),
            (2, "Базы данных", "Козлов Д.М.", "@kozlov"),
            (2, "Веб-технологии", "Смирнова Е.В.", "@smirnova"),
            (3, "Машинное обучение", "Орлов Н.С.", "@orlov"),
            (3, "Сетевые технологии", "Зайцев А.А.", "@zaitsev"),
            (4, "Дипломное проектирование", "Васильева Л.М.", "@vasilieva"),
            (4, "Управление проектами", "Кузнецов И.В.", "@kuznetsov"),
        ]
        cur.executemany(
            "INSERT INTO schedule (course,subject,teacher_name,teacher_contact) VALUES (?,?,?,?)",
            schedule,
        )

    cur.execute("SELECT COUNT(*) FROM helpers")
    if cur.fetchone()[0] == 0:
        helpers = [
            ("Алексей Иванов", "@alex_help", "Помогу с программированием"),
            ("Мария Петрова", "@maria_study", "Ответит на вопросы по учёбе"),
        ]
        cur.executemany("INSERT INTO helpers (name,tg_username,info) VALUES (?,?,?)", helpers)

    cur.execute("SELECT COUNT(*) FROM faq")
    if cur.fetchone()[0] == 0:
        faqs = [
            ("Как получить пропуск?", "Обратиться в проходную ЮФУ с паспортом и студенческим билетом."),
            ("Где взять справку о стипендии?", "В бухгалтерии ЮФУ."),
            ("Как заказать справку об обучении?", "Через личный кабинет студента на сайте ЮФУ."),
            ("Как оформить академический отпуск?", "Обратиться в деканат с заявлением и документами."),
            ("Как получить стипендию?", "Подать справку об успеваемости в учебную часть."),
        ]
        cur.executemany("INSERT INTO faq (question,answer) VALUES (?,?)", faqs)

    cur.execute("SELECT COUNT(*) FROM important_phones")
    if cur.fetchone()[0] == 0:
        phones = [
            ("Деканат ИВТиПТ", "+7(863)123-45-67", "каб. 101"),
            ("Учебная часть", "+7(863)123-45-68", "каб. 102"),
            ("Медпункт", "+7(863)123-45-69", "1 этаж"),
        ]
        cur.executemany("INSERT INTO important_phones (name,phone,description) VALUES (?,?,?)", phones)

    conn.commit()


def ensure_user(user_id: int):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id,course,notifications_enabled) VALUES (?,1,0)",
        (user_id,),
    )
    conn.commit()
    conn.close()


# ─── Основное меню ────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user.id)
    name = update.effective_user.first_name or "студент"
    await update.message.reply_text(
        f"👋 Привет, {name}!\n\n"
        "Я — *Гид для студентов ЮФУ* по Ростову-на-Дону.\n"
        "Помогу найти, где поесть, поставить печать, почитать отзывы и не только.\n\n"
        f"Твой chat\\_id: `{update.effective_user.id}`",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# ─── Категории мест с геолокацией ────────────────────────────────────────────

async def _ask_for_location(update: Update, category: str):
    """Запрашивает геолокацию или текстовый адрес для поиска мест категории."""
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Отправить геолокацию", request_location=True)],
         ["❌ Отмена"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        f"📍 Чтобы показать «{category}» рядом — отправь геолокацию\n\n"
        f"Или напиши адрес текстом (например: Пушкинская 105)",
        reply_markup=kb,
    )
    return LOCATION_WAIT


async def handle_food(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_category[update.effective_user.id] = "еда"
    return await _ask_for_location(update, "еда")


async def handle_coffee(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_category[update.effective_user.id] = "кофейни"
    return await _ask_for_location(update, "кофейни")


async def handle_print(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_category[update.effective_user.id] = "печать"
    return await _ask_for_location(update, "печать")


async def handle_other(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_category[update.effective_user.id] = "другое"
    return await _ask_for_location(update, "другое")


async def handle_location(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработчик геолокации — ищет ближайшие места выбранной категории."""
    loc = update.message.location
    if not loc:
        await update.message.reply_text("Геолокация не получена.", reply_markup=main_keyboard())
        return ConversationHandler.END

    user_id = update.effective_user.id
    category = user_category.pop(user_id, None)
    lat, lon = loc.latitude, loc.longitude

    conn = get_db()
    query = "SELECT * FROM places WHERE category=?" if category else "SELECT * FROM places"
    params = (category,) if category else ()
    places = conn.execute(query, params).fetchall()
    conn.close()

    if not places:
        label = f"«{category}»" if category else "базе"
        await update.message.reply_text(f"Мест в {label} пока нет.", reply_markup=main_keyboard())
        return ConversationHandler.END

    scored = sorted(
        [(haversine(lat, lon, p["latitude"], p["longitude"]), p) for p in places],
        key=lambda x: x[0],
    )[:5]

    label = category or "все категории"
    await update.message.reply_text(f"🏃 Ближайшие места ({label}):", reply_markup=main_keyboard())

    for dist, place in scored:
        stars = "⭐" * round(place["rating_avg"])
        text = (
            f"*{place['name']}*\n"
            f"📍 {place['address']}\n"
            f"📏 {dist:.2f} км\n"
            f"{place['description'] or ''}\n"
            f"⭐ {place['rating_avg']:.1f} {stars}"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗺 Построить маршрут",
                                 url=yandex_maps_url(place["latitude"], place["longitude"]))
        ]])
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

    return ConversationHandler.END


async def handle_text_location(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстового адреса — показывает места категории (без геокодинга)."""
    user_id = update.effective_user.id
    category = user_category.pop(user_id, None)
    address_text = update.message.text.strip()

    conn = get_db()
    query = "SELECT * FROM places WHERE category=? ORDER BY rating_avg DESC" if category else \
            "SELECT * FROM places ORDER BY rating_avg DESC"
    params = (category,) if category else ()
    places = conn.execute(query, params).fetchall()
    conn.close()

    if not places:
        label = f"«{category}»" if category else "базе"
        await update.message.reply_text(f"Мест в {label} пока нет.", reply_markup=main_keyboard())
        return ConversationHandler.END

    await update.message.reply_text(f"🔍 Места рядом с «{address_text}»:", reply_markup=main_keyboard())

    for place in places[:3]:
        stars = "⭐" * round(place["rating_avg"])
        text = (
            f"*{place['name']}*\n"
            f"📍 {place['address']}\n"
            f"{place['description'] or ''}\n"
            f"⭐ {place['rating_avg']:.1f} {stars}"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗺 Построить маршрут",
                                 url=yandex_maps_url(place["latitude"], place["longitude"]))
        ]])
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

    return ConversationHandler.END


async def location_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_category.pop(update.effective_user.id, None)
    await update.message.reply_text("Отменено.", reply_markup=main_keyboard())
    return ConversationHandler.END


# ─── «Рядом со мной» (все категории) ─────────────────────────────────────────

async def handle_nearby(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Кнопка «📍 Рядом со мной» — показывает 5 ближайших мест всех категорий."""
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Отправить геолокацию", request_location=True)],
         ["❌ Отмена"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        "📍 Отправьте геолокацию — покажу 5 ближайших мест:",
        reply_markup=kb,
    )
    return LOCATION_WAIT


# ─── Карта, номера, FAQ, лайфхаки ────────────────────────────────────────────

async def handle_map(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🗺️ *Карта корпусов ЮФУ*\n\n"
        "• Главный корпус: пер. Университетский, 93\n"
        "• ИВТиПТ: ул. Большая Садовая, 105/42\n"
        "• Физфак: ул. Зорге, 5\n"
        "• Биофак: пр. Стачки, 194/1\n\n"
        "[Открыть карту корпусов ЮФУ](https://yandex.ru/maps/?text=ЮФУ+Ростов-на-Дону&z=13)"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())


async def handle_phones(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    rows = conn.execute("SELECT * FROM important_phones").fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Номера не добавлены.", reply_markup=main_keyboard())
        return
    lines = ["📞 *Важные номера:*\n"]
    for r in rows:
        lines.append(f"*{r['name']}*\n📱 {r['phone']}\nℹ️ {r['description'] or ''}\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())


async def handle_faq(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    rows = conn.execute("SELECT * FROM faq").fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("FAQ пока пуст.", reply_markup=main_keyboard())
        return
    lines = ["❓ *Часто задаваемые вопросы:*\n"]
    for r in rows:
        lines.append(f"*❔ {r['question']}*\n💬 {r['answer']}\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())


async def handle_lifehacks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    helpers = conn.execute("SELECT * FROM helpers").fetchall()
    conn.close()

    text = (
        "🧠 *Лайфхаки и помощь*\n\n"
        "*Как оформить академический отпуск:*\n"
        "Обратитесь в деканат с заявлением и документами (медицинская справка или иное основание).\n\n"
        "*Как получить стипендию:*\n"
        "Подайте справку об успеваемости в учебную часть до конца сессии.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "*👨‍🎓 Старшекурсники готовы помочь:*\n"
    )
    for h in helpers:
        text += f"\n• *{h['name']}* — {h['tg_username']}\n  {h['info']}"

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())


# ─── Отзывы ───────────────────────────────────────────────────────────────────

async def handle_reviews_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    rows = conn.execute("SELECT id, name, rating_avg FROM places ORDER BY name").fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Мест пока нет.", reply_markup=main_keyboard())
        return
    buttons = [
        [InlineKeyboardButton(f"{r['name']} ({r['rating_avg']:.1f}⭐)", callback_data=f"reviews:{r['id']}")]
        for r in rows
    ]
    await update.message.reply_text(
        "⭐ *Отзывы и рейтинги*\nВыберите место:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cb_reviews(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    place_id = int(query.data.split(":")[1])

    conn = get_db()
    place = conn.execute("SELECT * FROM places WHERE id=?", (place_id,)).fetchone()
    revs = conn.execute(
        "SELECT * FROM reviews WHERE place_id=? ORDER BY date DESC LIMIT 10", (place_id,)
    ).fetchall()
    conn.close()

    if not place:
        await query.edit_message_text("Место не найдено.")
        return

    text = f"⭐ *Отзывы: {place['name']}*\nРейтинг: {place['rating_avg']:.1f}\n\n"
    if revs:
        for r in revs:
            text += f"{'⭐' * r['rating']} — {r['text'] or '(без текста)'}\n📅 {r['date']}\n\n"
    else:
        text += "Отзывов пока нет. Будьте первым!\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Добавить отзыв", callback_data=f"add_review:{place_id}")]
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)


# ─── Добавить отзыв ───────────────────────────────────────────────────────────

async def cb_add_review_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    place_id = int(query.data.split(":")[1])
    ctx.user_data["review_place_id"] = place_id

    conn = get_db()
    place = conn.execute("SELECT name FROM places WHERE id=?", (place_id,)).fetchone()
    conn.close()

    await query.message.reply_text(
        f"✍️ Оставляем отзыв для *{place['name'] if place else '?'}*\n\nВведите оценку от 1 до 5:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [["1", "2", "3", "4", "5"]], resize_keyboard=True, one_time_keyboard=True
        ),
    )
    return REVIEW_RATING


async def review_rating(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 5):
        await update.message.reply_text("Введите число от 1 до 5:")
        return REVIEW_RATING
    ctx.user_data["review_rating"] = int(text)
    await update.message.reply_text(
        "Напишите комментарий (или отправьте «-» чтобы пропустить):",
        reply_markup=ReplyKeyboardRemove(),
    )
    return REVIEW_TEXT


async def review_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text.strip()
    if comment == "-":
        comment = ""
    place_id = ctx.user_data.get("review_place_id")
    rating = ctx.user_data.get("review_rating", 3)
    user_id = update.effective_user.id

    conn = get_db()
    conn.execute(
        "INSERT INTO reviews (place_id,user_id,rating,text,date) VALUES (?,?,?,?,?)",
        (place_id, user_id, rating, comment, datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    avg = conn.execute(
        "SELECT AVG(rating) FROM reviews WHERE place_id=?", (place_id,)
    ).fetchone()[0] or 0
    conn.execute("UPDATE places SET rating_avg=? WHERE id=?", (round(avg, 2), place_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Спасибо! Ваш отзыв {'⭐' * rating} сохранён.",
        reply_markup=main_keyboard(),
    )
    ctx.user_data.clear()
    return ConversationHandler.END


async def review_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Отменено.", reply_markup=main_keyboard())
    return ConversationHandler.END


# ─── Предложить место ─────────────────────────────────────────────────────────

async def suggest_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 *Предложить место*\n\nКак называется место?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return SUGGEST_NAME


async def suggest_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["suggest_name"] = update.message.text.strip()
    await update.message.reply_text("Введите адрес места:")
    return SUGGEST_ADDR


async def suggest_addr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["suggest_addr"] = update.message.text.strip()
    cats = [["еда", "кофейни"], ["печать", "другое"]]
    await update.message.reply_text(
        "Выберите категорию:",
        reply_markup=ReplyKeyboardMarkup(cats, resize_keyboard=True, one_time_keyboard=True),
    )
    return SUGGEST_CAT


async def suggest_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cat = update.message.text.strip()
    if cat not in ("еда", "кофейни", "печать", "другое"):
        await update.message.reply_text("Выберите одну из кнопок: еда / кофейни / печать / другое")
        return SUGGEST_CAT

    user_id = update.effective_user.id
    name = ctx.user_data.get("suggest_name", "")
    addr = ctx.user_data.get("suggest_addr", "")

    conn = get_db()
    conn.execute(
        "INSERT INTO suggestions (user_id,place_name,place_address,category,status) VALUES (?,?,?,?,'pending')",
        (user_id, name, addr, cat),
    )
    sug_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Спасибо! Предложение «{name}» отправлено на проверку.",
        reply_markup=main_keyboard(),
    )

    if ADMIN_CHAT_ID:
        try:
            await ctx.bot.send_message(
                ADMIN_CHAT_ID,
                f"📬 Новое предложение #{sug_id}\n"
                f"Место: {name}\nАдрес: {addr}\nКатегория: {cat}\nОт: {user_id}\n\n"
                f"/approve {sug_id} — одобрить\n/reject {sug_id} — отклонить",
            )
        except Exception as e:
            logger.warning("Не удалось уведомить админа: %s", e)

    ctx.user_data.clear()
    return ConversationHandler.END


async def suggest_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Отменено.", reply_markup=main_keyboard())
    return ConversationHandler.END


# ─── Расписание ───────────────────────────────────────────────────────────────

async def handle_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    user = conn.execute("SELECT course FROM users WHERE user_id=?", (update.effective_user.id,)).fetchone()
    conn.close()
    saved_course = user["course"] if user else None

    buttons = [["1 курс", "2 курс"], ["3 курс", "4 курс"]]
    msg = "📅 *Расписание*\nВыберите курс:"
    if saved_course:
        msg += f"\n_(последний выбор: {saved_course} курс)_"
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True),
    )
    return SCHEDULE_CHOOSE


async def schedule_choose(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        course = int(text.split()[0])
        assert 1 <= course <= 4
    except Exception:
        await update.message.reply_text("Выберите курс из кнопок.")
        return SCHEDULE_CHOOSE

    conn = get_db()
    rows = conn.execute("SELECT * FROM schedule WHERE course=?", (course,)).fetchall()
    conn.execute("UPDATE users SET course=? WHERE user_id=?", (course, update.effective_user.id))
    conn.commit()
    conn.close()

    if not rows:
        await update.message.reply_text("Расписание для этого курса не найдено.", reply_markup=main_keyboard())
        return ConversationHandler.END

    lines = [f"📅 *Расписание {course} курса:*\n"]
    for r in rows:
        lines.append(f"📖 *{r['subject']}*\n👨‍🏫 {r['teacher_name']} ({r['teacher_contact']})\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())
    return ConversationHandler.END


async def schedule_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=main_keyboard())
    return ConversationHandler.END


# ─── Уведомления ─────────────────────────────────────────────────────────────

async def handle_notifications(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db()
    user = conn.execute("SELECT notifications_enabled, course FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()

    if user and user["notifications_enabled"]:
        await update.message.reply_text(
            "🔔 Уведомления уже включены.\n\nВведите /unsubscribe чтобы отключить.",
            reply_markup=main_keyboard(),
        )
        return ConversationHandler.END

    buttons = [["1 курс", "2 курс"], ["3 курс", "4 курс"]]
    await update.message.reply_text(
        "🔔 *Уведомления о расписании*\n\nВыберите ваш курс для настройки напоминаний:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True),
    )
    return NOTIF_CHOOSE_COURSE


async def notif_choose_course(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        course = int(text.split()[0])
        assert 1 <= course <= 4
    except Exception:
        await update.message.reply_text("Выберите курс из кнопок.")
        return NOTIF_CHOOSE_COURSE

    user_id = update.effective_user.id
    conn = get_db()
    conn.execute(
        "UPDATE users SET notifications_enabled=1, course=? WHERE user_id=?",
        (course, user_id),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Уведомления включены для *{course} курса*.\n"
        "Каждый день в 8:00 буду напоминать о первой паре.",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )
    return ConversationHandler.END


async def notif_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=main_keyboard())
    return ConversationHandler.END


async def unsubscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    conn.execute("UPDATE users SET notifications_enabled=0 WHERE user_id=?", (update.effective_user.id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("🔕 Уведомления отключены.", reply_markup=main_keyboard())


# ─── Фоновая задача: утренние уведомления ────────────────────────────────────

async def morning_notification(ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    users = conn.execute(
        "SELECT user_id, course FROM users WHERE notifications_enabled=1"
    ).fetchall()

    for u in users:
        rows = conn.execute(
            "SELECT subject, teacher_name FROM schedule WHERE course=? LIMIT 1", (u["course"],)
        ).fetchall()
        if rows:
            subj = rows[0]["subject"]
            teacher = rows[0]["teacher_name"]
            try:
                await ctx.bot.send_message(
                    u["user_id"],
                    f"🔔 Доброе утро!\n\nСегодня у тебя:\n📖 *{subj}*\n👨‍🏫 {teacher}",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning("Не удалось отправить уведомление %s: %s", u["user_id"], e)

    conn.close()


# ─── Декоратор для админ-команд ───────────────────────────────────────────────

def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Нет доступа.")
            return ConversationHandler.END
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


# ─── Админ: /add_place ────────────────────────────────────────────────────────

@admin_only
async def add_place_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите название места:", reply_markup=ReplyKeyboardRemove())
    return AP_NAME

async def ap_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ap_name"] = update.message.text.strip()
    cats = [["еда", "кофейни"], ["печать", "другое"]]
    await update.message.reply_text("Категория:", reply_markup=ReplyKeyboardMarkup(cats, resize_keyboard=True, one_time_keyboard=True))
    return AP_CAT

async def ap_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ap_cat"] = update.message.text.strip()
    await update.message.reply_text("Адрес:", reply_markup=ReplyKeyboardRemove())
    return AP_ADDR

async def ap_addr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ap_addr"] = update.message.text.strip()
    await update.message.reply_text("Широта (например 47.226):")
    return AP_LAT

async def ap_lat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["ap_lat"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Введите число, например 47.226:")
        return AP_LAT
    await update.message.reply_text("Долгота (например 39.712):")
    return AP_LON

async def ap_lon(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["ap_lon"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Введите число, например 39.712:")
        return AP_LON
    await update.message.reply_text("Описание (или «-» пропустить):")
    return AP_DESC

async def ap_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    if desc == "-":
        desc = ""
    d = ctx.user_data
    conn = get_db()
    conn.execute(
        "INSERT INTO places (name,category,address,latitude,longitude,description,rating_avg) VALUES (?,?,?,?,?,?,0)",
        (d["ap_name"], d["ap_cat"], d["ap_addr"], d["ap_lat"], d["ap_lon"], desc),
    )
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Место «{d['ap_name']}» добавлено.", reply_markup=main_keyboard())
    ctx.user_data.clear()
    return ConversationHandler.END

async def admin_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Отменено.", reply_markup=main_keyboard())
    return ConversationHandler.END


# ─── Админ: /add_faq ─────────────────────────────────────────────────────────

@admin_only
async def add_faq_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите вопрос:", reply_markup=ReplyKeyboardRemove())
    return AF_Q

async def af_q(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["af_q"] = update.message.text.strip()
    await update.message.reply_text("Введите ответ:")
    return AF_A

async def af_a(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    conn.execute("INSERT INTO faq (question,answer) VALUES (?,?)",
                 (ctx.user_data["af_q"], update.message.text.strip()))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ FAQ добавлен.", reply_markup=main_keyboard())
    ctx.user_data.clear()
    return ConversationHandler.END


# ─── Админ: /add_phone ───────────────────────────────────────────────────────

@admin_only
async def add_phone_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Название:", reply_markup=ReplyKeyboardRemove())
    return APH_NAME

async def aph_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["aph_name"] = update.message.text.strip()
    await update.message.reply_text("Номер телефона:")
    return APH_PHONE

async def aph_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["aph_phone"] = update.message.text.strip()
    await update.message.reply_text("Описание (или «-»):")
    return APH_DESC

async def aph_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    conn = get_db()
    conn.execute("INSERT INTO important_phones (name,phone,description) VALUES (?,?,?)",
                 (ctx.user_data["aph_name"], ctx.user_data["aph_phone"], desc if desc != "-" else ""))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Номер добавлен.", reply_markup=main_keyboard())
    ctx.user_data.clear()
    return ConversationHandler.END


# ─── Админ: /add_schedule ────────────────────────────────────────────────────

@admin_only
async def add_schedule_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Курс (1-4):", reply_markup=ReplyKeyboardRemove())
    return AS_COURSE

async def as_course(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        course = int(update.message.text.strip())
        assert 1 <= course <= 4
        ctx.user_data["as_course"] = course
    except Exception:
        await update.message.reply_text("Введите число 1-4:")
        return AS_COURSE
    await update.message.reply_text("Название предмета:")
    return AS_SUBJ

async def as_subj(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["as_subj"] = update.message.text.strip()
    await update.message.reply_text("ФИО преподавателя:")
    return AS_TEACHER

async def as_teacher(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["as_teacher"] = update.message.text.strip()
    await update.message.reply_text("Контакт преподавателя (Telegram):")
    return AS_CONTACT

async def as_contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = ctx.user_data
    conn = get_db()
    conn.execute("INSERT INTO schedule (course,subject,teacher_name,teacher_contact) VALUES (?,?,?,?)",
                 (d["as_course"], d["as_subj"], d["as_teacher"], update.message.text.strip()))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Расписание добавлено.", reply_markup=main_keyboard())
    ctx.user_data.clear()
    return ConversationHandler.END


# ─── Админ: /add_helper ──────────────────────────────────────────────────────

@admin_only
async def add_helper_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Имя старшекурсника:", reply_markup=ReplyKeyboardRemove())
    return AH_NAME

async def ah_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ah_name"] = update.message.text.strip()
    await update.message.reply_text("Telegram username (с @):")
    return AH_TG

async def ah_tg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ah_tg"] = update.message.text.strip()
    await update.message.reply_text("Чем может помочь:")
    return AH_INFO

async def ah_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = ctx.user_data
    conn = get_db()
    conn.execute("INSERT INTO helpers (name,tg_username,info) VALUES (?,?,?)",
                 (d["ah_name"], d["ah_tg"], update.message.text.strip()))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Старшекурсник добавлен.", reply_markup=main_keyboard())
    ctx.user_data.clear()
    return ConversationHandler.END


# ─── Админ: предложения ───────────────────────────────────────────────────────

async def list_suggestions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    conn = get_db()
    rows = conn.execute("SELECT * FROM suggestions WHERE status='pending'").fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Нет необработанных предложений.")
        return
    lines = ["📋 *Необработанные предложения:*\n"]
    for r in rows:
        lines.append(f"#{r['id']} — *{r['place_name']}*\n📍 {r['place_address']} | {r['category']}\nОт: {r['user_id']}\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def approve_suggestion(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /approve <id>")
        return
    try:
        sug_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Укажите числовой id.")
        return
    conn = get_db()
    sug = conn.execute("SELECT * FROM suggestions WHERE id=?", (sug_id,)).fetchone()
    if not sug:
        await update.message.reply_text(f"Предложение #{sug_id} не найдено.")
        conn.close()
        return
    conn.execute(
        "INSERT INTO places (name,category,address,latitude,longitude,description,rating_avg) VALUES (?,?,?,0,0,'',0)",
        (sug["place_name"], sug["category"], sug["place_address"]),
    )
    conn.execute("UPDATE suggestions SET status='approved' WHERE id=?", (sug_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Предложение #{sug_id} одобрено и добавлено в базу.")
    try:
        await ctx.bot.send_message(
            sug["user_id"],
            f"✅ Ваше предложение «{sug['place_name']}» одобрено и добавлено в базу!"
        )
    except Exception:
        pass


async def reject_suggestion(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    if not ctx.args:
        await update.message.reply_text("Использование: /reject <id>")
        return
    try:
        sug_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Укажите числовой id.")
        return
    conn = get_db()
    sug = conn.execute("SELECT * FROM suggestions WHERE id=?", (sug_id,)).fetchone()
    conn.execute("UPDATE suggestions SET status='rejected' WHERE id=?", (sug_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"❌ Предложение #{sug_id} отклонено.")
    if sug:
        try:
            await ctx.bot.send_message(
                sug["user_id"],
                f"❌ К сожалению, предложение «{sug['place_name']}» не было принято."
            )
        except Exception:
            pass


# ─── Сборка приложения ────────────────────────────────────────────────────────

def build_app() -> Application:
    app = Application.builder().token(TOKEN).build()

    # Обычные команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("list_suggestions", list_suggestions))
    app.add_handler(CommandHandler("approve", approve_suggestion))
    app.add_handler(CommandHandler("reject", reject_suggestion))

    # Callback-кнопки (отзывы)
    app.add_handler(CallbackQueryHandler(cb_reviews, pattern=r"^reviews:\d+$"))

    # Диалог: добавить отзыв
    review_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_review_start, pattern=r"^add_review:\d+$")],
        states={
            REVIEW_RATING: [MessageHandler(filters.TEXT & ~filters.COMMAND, review_rating)],
            REVIEW_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, review_text)],
        },
        fallbacks=[CommandHandler("cancel", review_cancel)],
        per_message=False,
    )
    app.add_handler(review_conv)

    # Диалог: предложить место
    suggest_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^💡 Предложить место$"), suggest_start)],
        states={
            SUGGEST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggest_name)],
            SUGGEST_ADDR: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggest_addr)],
            SUGGEST_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggest_cat)],
        },
        fallbacks=[CommandHandler("cancel", suggest_cancel)],
    )
    app.add_handler(suggest_conv)

    # Диалог: категории мест с геолокацией (еда / кофейни / печать / другое)
    nearby_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^🍽️ Где поесть рядом$"), handle_food),
            MessageHandler(filters.Regex(r"^☕ Кофейни с розетками$"), handle_coffee),
            MessageHandler(filters.Regex(r"^📚 Печать / канцелярия$"), handle_print),
            MessageHandler(filters.Regex(r"^🏧 Другое$"), handle_other),
            MessageHandler(filters.Regex(r"^📍 Рядом со мной$"), handle_nearby),
        ],
        states={
            LOCATION_WAIT: [
                MessageHandler(filters.LOCATION, handle_location),
                MessageHandler(filters.Regex(r"^❌ Отмена$"), location_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_location),
            ],
        },
        fallbacks=[CommandHandler("cancel", location_cancel)],
    )
    app.add_handler(nearby_conv)

    # Диалог: расписание
    schedule_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^📅 Расписание$"), handle_schedule)],
        states={
            SCHEDULE_CHOOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_choose)],
        },
        fallbacks=[CommandHandler("cancel", schedule_cancel)],
    )
    app.add_handler(schedule_conv)

    # Диалог: уведомления
    notif_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🔔 Уведомления$"), handle_notifications)],
        states={
            NOTIF_CHOOSE_COURSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, notif_choose_course)],
        },
        fallbacks=[CommandHandler("cancel", notif_cancel)],
    )
    app.add_handler(notif_conv)

    # Диалог: admin add_place
    ap_conv = ConversationHandler(
        entry_points=[CommandHandler("add_place", add_place_start)],
        states={
            AP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_name)],
            AP_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_cat)],
            AP_ADDR: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_addr)],
            AP_LAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_lat)],
            AP_LON: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_lon)],
            AP_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_desc)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
    )
    app.add_handler(ap_conv)

    # Диалог: admin add_faq
    af_conv = ConversationHandler(
        entry_points=[CommandHandler("add_faq", add_faq_start)],
        states={
            AF_Q: [MessageHandler(filters.TEXT & ~filters.COMMAND, af_q)],
            AF_A: [MessageHandler(filters.TEXT & ~filters.COMMAND, af_a)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
    )
    app.add_handler(af_conv)

    # Диалог: admin add_phone
    aph_conv = ConversationHandler(
        entry_points=[CommandHandler("add_phone", add_phone_start)],
        states={
            APH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, aph_name)],
            APH_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, aph_phone)],
            APH_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, aph_desc)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
    )
    app.add_handler(aph_conv)

    # Диалог: admin add_schedule
    as_conv = ConversationHandler(
        entry_points=[CommandHandler("add_schedule", add_schedule_start)],
        states={
            AS_COURSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, as_course)],
            AS_SUBJ: [MessageHandler(filters.TEXT & ~filters.COMMAND, as_subj)],
            AS_TEACHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, as_teacher)],
            AS_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, as_contact)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
    )
    app.add_handler(as_conv)

    # Диалог: admin add_helper
    ah_conv = ConversationHandler(
        entry_points=[CommandHandler("add_helper", add_helper_start)],
        states={
            AH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ah_name)],
            AH_TG: [MessageHandler(filters.TEXT & ~filters.COMMAND, ah_tg)],
            AH_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ah_info)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
    )
    app.add_handler(ah_conv)

    # Прочие кнопки меню
    app.add_handler(MessageHandler(filters.Regex(r"^🧠 Лайфхаки \+ помощь$"), handle_lifehacks))
    app.add_handler(MessageHandler(filters.Regex(r"^⭐ Отзывы и рейтинги$"), handle_reviews_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^🗺️ Карта корпусов ЮФУ$"), handle_map))
    app.add_handler(MessageHandler(filters.Regex(r"^📞 Важные номера$"), handle_phones))
    app.add_handler(MessageHandler(filters.Regex(r"^❓ FAQ$"), handle_faq))

    # Фоновая задача: утренние уведомления в 8:00
    if app.job_queue:
        app.job_queue.run_daily(morning_notification, time=time(hour=8, minute=0))

    return app


def main():
    init_db()
    logger.info("База данных инициализирована: %s", DB_PATH)
    app = build_app()
    logger.info("Бот запущен. Напиши /start в Telegram")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    
    


if __name__ == "__main__":
    main()
