# -*- coding: utf-8 -*-
# =============================================================================
#  ZARRA RESORT — Telegram AI-ассистент  (версия 6, на Groq)
#
#  Работает в двух режимах:
#   • ПРЯМОЙ БОТ (@zarra_resort_ai_bot) — с кнопками-меню, командами, картой,
#     галереями, меню ресторана. Это «парадный вход» (ссылка в Instagram/QR).
#   • ПРОФИЛЬ @zarra_resort (Автоматизация чатов) — умный авто-ответ текстом
#     (Telegram не показывает кнопки у аккаунта — это его ограничение).
#
#  ЧТО НОВОГО В v6:
#   - Кнопки-меню и команды в прямом боте.
#   - Карта/геолокация (/set_location), адрес (/set_address).
#   - Нерабочее время: ночью бот предупреждает про ответ утром.
#   - Алерт «нужен человек» в группу.
#   - /stats (сводка заявок), /export (выгрузка заявок в файл).
#   - Меню ресторана как галерея (/setup_menu).
#
#  МЕНЯТЬ РУКАМИ можно только блок "БАЗА ЗНАНИЙ" ниже. Остальное — не трогать.
#
#  Группа заявок: добавь бота в группу АДМИНОМ и отправь там /setgroup.
#  Геолокация: /set_location (в личке боту) -> пришли точку (📎 Геопозиция).
# =============================================================================

import os
import re
import csv
import json
import asyncio
import logging
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, BusinessConnection, CallbackQuery, BotCommand, FSInputFile,
    InputMediaPhoto, InputMediaVideo,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from groq import Groq

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("zarra")

MODEL = "llama-3.3-70b-versatile"

# Рабочие часы (время Ташкента, UTC+5). Вне этих часов бот предупреждает гостя.
WORK_START, WORK_END = 9, 23


# =============================================================================
#  БАЗА ЗНАНИЙ — это "память" бота. Здесь можно редактировать факты.
# =============================================================================
KNOWLEDGE = """
Zarra Resort & SPA — премиальный загородный резорт.
Девиз: «Где время становится роскошью».
Telegram: @zarra_resort | Instagram: @zarraresort

ТИПЫ ШАЛЕ (вилл):

1) ШАЛЕ КОМФОРТ — всего 9 вилл.
   - Спальных мест: 2 — С НОЧЁВКОЙ остаться могут максимум 2 человека.
   - Посадочных мест: 10 — днём/вечером можно принять до 10 гостей,
     но переночевать смогут только 2.
   ЦЕНЫ (будни):
   - Слот 1, с 10:00 до 17:00 — 1,5 млн сум
   - Слот 2, с 18:00 до 09:00 — 2 млн сум
   - Слот 3, ПОЛНЫЙ ДЕНЬ с 10:00 до 09:00 — 3 млн сум

2) ШАЛЕ ПРЕЗИДЕНТ ЛЮКС — всего 3 виллы.
   - Спальных мест: 7 — С НОЧЁВКОЙ остаться могут до 7 человек.
   - Посадочных мест: 20 — до 20 гостей на мероприятии; ночуют до 7.
   ЦЕНЫ (будни):
   - Слот 1, с 10:00 до 17:00 — 3 млн сум
   - Слот 2, с 18:00 до 09:00 — 4 млн сум
   - Слот 3, ПОЛНЫЙ ДЕНЬ с 10:00 до 09:00 — 6 млн сум

ВАЖНО ПРО ЦЕНЫ:
- По субботам, воскресеньям и в праздничные дни цены ВЫШЕ на 20%.
- Все цены — в узбекских сумах (сум).

МЕРОПРИЯТИЯ:
- На территории можно проводить дни рождения и мероприятия.
- Вместимость по посадочным местам: Комфорт — до 10, Президент Люкс — до 20.

БРОНИРОВАНИЕ И ОПЛАТА:
- Для подтверждения брони нужна предоплата 50%.
- Отмена и возврат:
  • отмена ЗА 3 ДНЯ И БОЛЬШЕ до заселения — предоплату возвращаем полностью;
  • позже, чем за 3 дня (например, за 1 день) — предоплата НЕ возвращается (штраф).
  • Чтобы вернуть деньги, отменить нужно минимум за 3 дня до заселения.

УДОБСТВА НА ТЕРРИТОРИИ:
- Бассейн, бар, тапчаны (зона отдыха).
- В каждом шале есть мангал и казан.
- Ресторан — откроется примерно 20 июня 2026 (пока ещё не работает).

КОНТАКТЫ ДЛЯ СВЯЗИ:
- Telegram: @zarra_resort
- Телефон с 09:00 до 18:00: +998 87 591 33 30
- Телефон с 18:00 до 23:00: +998 97 614 77 74

ДОПОЛНИТЕЛЬНО (Азамат, заполни сам, если знаешь):
- Можно ли с животными: (не указано)
- Парковка: (не указано)
- Что входит в стоимость: (не указано)
"""


# =============================================================================
#  ПРАВИЛА ПОВЕДЕНИЯ
# =============================================================================
RULES = """
Ты — живой, тёплый и гостеприимный ассистент резорта Zarra Resort & SPA.
Ты общаешься от имени резорта в Telegram.

КАК ОБЩАТЬСЯ:
- Пиши простым, живым человеческим языком — как приветливый администратор,
  а не робот. Без канцелярита и «воды».
- Определи язык клиента и отвечай НА ТОМ ЖЕ языке (русский, узбекский,
  английский или таджикский).
- НИКОГДА не используй markdown и спецсимволы для выделения: никаких *, **,
  _, #, `. Пиши обычным текстом. Перечисление — с новой строки или через «–».
- Тон тёплый и премиальный, но дружелюбный. Кратко и по делу.
- Лёгкие эмодзи можно, в меру (1–2 на сообщение).

ГЛАВНЫЕ ПРАВИЛА:
- Используй ТОЛЬКО факты из базы знаний. НИЧЕГО не выдумывай.
- ТЫ НЕ ПОДТВЕРЖДАЕШЬ БРОНЬ. Бронь подтверждает только наш сотрудник.
- Если спрашивают то, чего НЕТ в базе знаний — честно скажи, что уточнишь,
  и дай контакты для связи.
- В начале тебе сообщают текущие день недели, дату и время — опирайся на них,
  не путай утро/день/вечер и не выдумывай, какой сейчас день.
- Наценка +20% применяется ТОЛЬКО когда ДАТА брони — суббота, воскресенье или
  официальный праздничный день. Будний день (пн–пт) — без наценки.
- ВАЖНО: «повод» гостя (праздник, день рождения, свадьба и т.п.) — это просто
  причина брони, на цену он НЕ влияет. Не путай «повод — праздник» с тем,
  что дата выпадает на праздничный день.

ПРО ВМЕСТИМОСТЬ (не путать):
- "Спальных мест" — сколько могут ОСТАТЬСЯ НА НОЧЬ (Комфорт 2, Люкс 7).
- "Посадочных мест" — сколько гостей днём/на мероприятии (Комфорт 10, Люкс 20).

СЛУЖЕБНЫЕ ТЕГИ (гость их НЕ видит, не упоминай и не показывай их):
1) ФОТО/ВИДЕО: когда гость согласился посмотреть конкретное шале — добавь
   в конце ответа тег <gallery>lux</gallery> (или comfort, exterior, menu).
   Не пиши «отправляю/загружается», не описывай фото — они придут сами.
   Перед тегом достаточно короткой фразы: «Конечно! Смотрите 👇».
2) ЗАЯВКА НА БРОНЬ: собери шале, дату, слот, сколько гостей всего и с ночёвкой,
   повод (если есть), имя и телефон. Бронь НЕ подтверждай и оплатой НЕ занимайся:
   не считай сумму предоплаты, не проси перевести деньги и не объясняй, куда
   платить — этим займётся живой сотрудник. Когда собраны хотя бы
   ШАЛЕ, ДАТА, СЛОТ, ИМЯ и ТЕЛЕФОН — добавь в конце ответа тег:
   <lead>{"chalet":"","date":"","slot":"","guests_total":"","guests_overnight":"","occasion":"","name":"","phone":"","notes":""}</lead>
   и коротко скажи гостю: заявку передал нашему сотруднику, он скоро свяжется
   для подтверждения. Если данных мало — тег не добавляй, вежливо уточни.
3) НУЖЕН ЧЕЛОВЕК: если гость просит живого сотрудника, недоволен, жалуется
   или вопрос срочный/нестандартный — добавь тег <human/>. При этом сам
   вежливо ответь и дай контакты для связи.
"""

SYSTEM_PROMPT = RULES + "\n\nБАЗА ЗНАНИЙ:\n" + KNOWLEDGE


# --- Готовые тексты для кнопок -------------------------------------------------
PRICES_TEXT = (
    "🏡 Наши шале\n\n"
    "«Комфорт» (9 вилл) — ночёвка до 2 чел., днём до 10 гостей:\n"
    "• День 10:00–17:00 — 1,5 млн\n• Ночь 18:00–09:00 — 2 млн\n"
    "• Полный день — 3 млн\n\n"
    "«Президент Люкс» (3 виллы) — ночёвка до 7 чел., до 20 гостей:\n"
    "• День 10:00–17:00 — 3 млн\n• Ночь 18:00–09:00 — 4 млн\n"
    "• Полный день — 6 млн\n\n"
    "Сб, Вс и праздники +20%. Цены в сумах.\n"
    "Можно проводить дни рождения и мероприятия 🎉\n"
    "Предоплата 50%, возврат при отмене за 3+ дня.\n\n"
    "Хотите фото или забронировать? Просто напишите 🙂"
)
SLOTS_TEXT = (
    "📅 Слоты бронирования\n\n"
    "• Слот 1 — день, 10:00–17:00\n"
    "• Слот 2 — ночь, 18:00–09:00\n"
    "• Слот 3 — полный день, 10:00–09:00\n\n"
    "Цены зависят от шале (см. «🏡 Шале и цены»). Сб/Вс/праздники +20%.\n"
    "Для брони нужна предоплата 50%. Возврат — при отмене за 3+ дня.\n\n"
    "Чтобы забронировать — напишите шале, дату, слот, число гостей, "
    "ваше имя и телефон, и я передам заявку 🙌"
)
CONTACTS_TEXT = (
    "💬 Связаться с нами\n\n"
    "📞 09:00–18:00: +998 87 591 33 30\n"
    "📞 18:00–23:00: +998 97 614 77 74\n"
    "Telegram: @zarra_resort\nInstagram: @zarraresort"
)


# =============================================================================
#  Конфиг
# =============================================================================
def load_config() -> tuple[str, str]:
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    token = os.getenv("BOT_TOKEN")
    groq_key = os.getenv("GROQ_API_KEY")
    if not token:
        print("\nНужен токен бота от BotFather.")
        token = input("Вставь токен бота и нажми Enter:\n> ").strip()
    if not groq_key:
        print("\nНужен бесплатный ключ Groq (console.groq.com -> API Keys).")
        groq_key = input("Вставь сюда Groq API ключ и нажми Enter:\n> ").strip()
    env_path.write_text(f"BOT_TOKEN={token}\nGROQ_API_KEY={groq_key}\n", encoding="utf-8")
    return token, groq_key


BOT_TOKEN, GROQ_API_KEY = load_config()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai = Groq(api_key=GROQ_API_KEY)

history: dict[str, list[dict]] = {}
owners: dict[str, int] = {}
last_lead: dict[str, str] = {}

# --- Хранилище -----------------------------------------------------------------
STORE_PATH = Path(__file__).parent / "media_store.json"

CAT_NAMES = {"lux": "Шале Люкс", "comfort": "Шале Комфорт",
             "exterior": "Территория", "menu": "Меню ресторана"}
GALLERY_CAPTIONS = {
    "lux": ("🌿 Шале «Президент Люкс»\nСмотрите фото и видео ниже 👇\n"
            "Захотите узнать цены или забронировать — просто напишите."),
    "comfort": ("🌿 Шале «Комфорт»\nСмотрите фото и видео ниже 👇\n"
                "Нужны цены или бронь — напишите."),
    "exterior": "🌿 ZARRA RESORT — наша территория\nСмотрите фото и видео ниже 👇",
    "menu": "🍽 Меню ресторана\nСмотрите ниже 👇",
}


def load_store() -> dict:
    if STORE_PATH.exists():
        try:
            data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    data.setdefault("owner_id", None)
    data.setdefault("leads_chat_id", None)
    data.setdefault("lead_counter", 0)
    data.setdefault("leads", [])
    data.setdefault("location", None)   # {"lat":..,"lon":..,"address":".."}
    data.setdefault("galleries", {})
    for c in ("lux", "comfort", "exterior", "menu"):
        data["galleries"].setdefault(c, [])
    return data


def save_store() -> None:
    STORE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


store = load_store()
collecting: dict[int, str] = {}        # загрузка галереи: user_id -> категория
awaiting_location: set[int] = set()    # ждём геоточку от владельца


# --- Время / рабочие часы ------------------------------------------------------
def tashkent_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=5)


def is_working_hours() -> bool:
    return WORK_START <= tashkent_now().hour < WORK_END


# --- Распознавание запросов ----------------------------------------------------
GAL_WORDS = ("фото", "видео", "посмотр", "покаж", "показа", "увидет",
             "как выглядит", "галере", "снимк", "rasm", "surat", "video",
             "photo", "ko'r", "ko‘r", "ko'rsat", "look", "picture", "image")
LUX_WORDS = ("люкс", "lux", "президент", "prezident")
COMF_WORDS = ("комфорт", "komfort", "comfort")
EXT_WORDS = ("территор", "бассейн", "снаружи", "exterior", "общие", "вид резорт")
LOC_WORDS = ("как добраться", "как доехать", "где вы наход", "где находит",
             "ваш адрес", "адрес резорт", "локац", "на карте", "manzil",
             "qayerda", "where are you", "location", "как приехать", "где это")


def detect_gallery_request(text: str):
    t = text.lower()
    if not any(w in t for w in GAL_WORDS):
        return None
    if any(w in t for w in LUX_WORDS):
        return "lux"
    if any(w in t for w in COMF_WORDS):
        return "comfort"
    if any(w in t for w in EXT_WORDS):
        return "exterior"
    return "ask"


def detect_location_request(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in LOC_WORDS)


def _chunks(lst, n=10):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


async def send_gallery(chat_id: int, bcid, category: str) -> bool:
    items = store["galleries"].get(category, [])
    if not items:
        return False
    caption = GALLERY_CAPTIONS.get(category, "")
    first = True
    for group in _chunks(items, 10):
        media = []
        for it in group:
            cap = caption if first else None
            first = False
            if it.get("t") == "video":
                media.append(InputMediaVideo(media=it["id"], caption=cap))
            else:
                media.append(InputMediaPhoto(media=it["id"], caption=cap))
        try:
            await bot.send_media_group(chat_id=chat_id, media=media,
                                       business_connection_id=bcid)
        except Exception as e:
            log.warning(f"send_media_group error: {e}")
            return False
        await asyncio.sleep(0.8)
    return True


async def send_location_card(chat_id: int, bcid) -> None:
    loc = store.get("location")
    if loc and loc.get("lat") is not None:
        try:
            await bot.send_location(chat_id, latitude=loc["lat"], longitude=loc["lon"],
                                    business_connection_id=bcid)
        except Exception as e:
            log.warning(f"send_location error: {e}")
        addr = loc.get("address") or ""
        txt = "📍 Zarra Resort & SPA\n"
        if addr:
            txt += addr + "\n"
        txt += "Точка на карте — выше 👆\nНужна помощь с дорогой? +998 87 591 33 30"
        await bot.send_message(chat_id, txt, business_connection_id=bcid)
    else:
        await bot.send_message(chat_id, "📍 Точный адрес уточните, пожалуйста, у нас:\n"
                               + CONTACTS_TEXT, business_connection_id=bcid)


# --- Кнопки / клавиатуры -------------------------------------------------------
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🏡 Шале и цены"), KeyboardButton(text="📸 Фото и видео")],
        [KeyboardButton(text="📅 Слоты и бронь"), KeyboardButton(text="📍 Как добраться")],
        [KeyboardButton(text="🍽 Меню ресторана"), KeyboardButton(text="💬 Связаться")],
    ],
    resize_keyboard=True, is_persistent=True,
    input_field_placeholder="Выберите или напишите вопрос…",
)

GALLERY_PICK = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Президент Люкс", callback_data="gal:lux"),
     InlineKeyboardButton(text="Комфорт", callback_data="gal:comfort")],
    [InlineKeyboardButton(text="Территория", callback_data="gal:exterior")],
])


# --- Заявки на бронь -----------------------------------------------------------
LEAD_RE = re.compile(r"<lead>\s*(\{.*?\})\s*</lead>", re.DOTALL | re.IGNORECASE)
GALLERY_RE = re.compile(r"<gallery>\s*(lux|comfort|exterior|menu)\s*</gallery>", re.IGNORECASE)
HUMAN_RE = re.compile(r"<human\s*/?>", re.IGNORECASE)


def extract_controls(text: str):
    """Возвращает (чистый_текст, заявка|None, галерея|None, нужен_человек:bool)."""
    lead = None
    m = LEAD_RE.search(text)
    if m:
        try:
            lead = json.loads(m.group(1))
        except Exception:
            lead = None
    gal = None
    mg = GALLERY_RE.search(text)
    if mg:
        gal = mg.group(1).lower()
    need_human = bool(HUMAN_RE.search(text))
    clean = LEAD_RE.sub("", text)
    clean = GALLERY_RE.sub("", clean)
    clean = HUMAN_RE.sub("", clean)
    clean = re.sub(r"</?lead>|</?gallery>", "", clean, flags=re.IGNORECASE)
    return clean.strip(), lead, gal, need_human


def lead_keyboard(username: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="lead:confirm"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data="lead:reject")],
        [InlineKeyboardButton(text="🙋 Беру в работу", callback_data="lead:take")],
    ]
    if username:
        rows.append([InlineKeyboardButton(text="✍️ Открыть чат гостя",
                                          url=f"https://t.me/{username}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def links_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Instagram",
                              url="https://instagram.com/zarraresort"),
         InlineKeyboardButton(text="📢 Канал",
                              url="https://t.me/zarraresort")],
        [InlineKeyboardButton(text="📍 Локация",
                              url="https://maps.app.goo.gl/V8U9eX28Fuzgoshy9")],
    ])


def format_lead(lead: dict, number: int, source: str) -> str:
    def g(key):
        v = lead.get(key)
        v = str(v).strip() if v is not None else ""
        return v if v and v not in ("-", "—") else None
    lines = [f"🆕 НОВАЯ ЗАЯВКА #{number}", ""]
    if g("chalet"):
        lines.append(f"🏡 Шале: {g('chalet')}")
    if g("date"):
        lines.append(f"📅 Дата: {g('date')}")
    if g("slot"):
        lines.append(f"⏰ Слот: {g('slot')}")
    if g("guests_total") or g("guests_overnight"):
        gl = f"👥 Гостей: {g('guests_total') or '—'}"
        if g("guests_overnight"):
            gl += f" (с ночёвкой: {g('guests_overnight')})"
        lines.append(gl)
    if g("occasion"):
        lines.append(f"🎉 Повод: {g('occasion')}")
    if g("name"):
        lines.append(f"🙍 Имя: {g('name')}")
    if g("phone"):
        lines.append(f"📞 Телефон: {g('phone')}")
    if g("notes"):
        lines.append(f"💬 Комментарий: {g('notes')}")
    if source:
        lines.append(f"———\n💬 Гость: {source}")
    lines.append("\n⚠️ Бронь подтверждает сотрудник. Предоплата 50%.")
    return "\n".join(lines)


def guest_source(message: Message) -> str:
    u = message.from_user
    if not u:
        return "—"
    return f"@{u.username}" if u.username else (u.full_name or "—")


async def post_lead(lead: dict, chat_key: str, source: str, username: str | None = None):
    signature = json.dumps(lead, ensure_ascii=False, sort_keys=True)
    if last_lead.get(chat_key) == signature:
        return
    last_lead[chat_key] = signature
    dest = store.get("leads_chat_id") or store.get("owner_id")
    if not dest:
        return
    store["lead_counter"] = int(store.get("lead_counter", 0)) + 1
    no = store["lead_counter"]
    text = format_lead(lead, no, source)
    try:
        sent = await bot.send_message(dest, text, reply_markup=lead_keyboard(username))
    except Exception as e:
        log.warning(f"post_lead error: {e}")
        return
    now = tashkent_now()
    store["leads"].append({
        "no": no, "ts": now.strftime("%Y-%m-%d %H:%M"),
        "day": now.strftime("%Y-%m-%d"), "status": "new", "by": "",
        "chat_id": sent.chat.id, "message_id": sent.message_id,
        "source": source, "data": lead,
    })
    save_store()


async def alert_human(source: str, last_text: str):
    dest = store.get("leads_chat_id") or store.get("owner_id")
    if not dest:
        return
    txt = (f"🙋 ГОСТЮ НУЖЕН ЖИВОЙ СОТРУДНИК\n\n💬 Гость: {source}\n"
           f"Последнее сообщение: «{last_text[:300]}»")
    try:
        await bot.send_message(dest, txt)
    except Exception as e:
        log.warning(f"alert_human error: {e}")


async def ask_ai(chat_key: str, user_text: str):
    """Возвращает (ответ, заявка|None, галерея|None, нужен_человек)."""
    turns = history.setdefault(chat_key, [])
    turns.append({"role": "user", "text": user_text})
    turns[:] = turns[-12:]

    now_dt = tashkent_now()
    now = now_dt.strftime("%H:%M")
    _WD = ["понедельник", "вторник", "среда", "четверг",
           "пятница", "суббота", "воскресенье"]
    weekday = _WD[now_dt.weekday()]
    date_str = now_dt.strftime("%d.%m.%Y")
    weekend = ("Сегодня выходной (Сб/Вс) — цены +20%."
               if now_dt.weekday() >= 5 else "Сегодня будний день.")
    when = f"Сейчас в резорте: {weekday}, {date_str}, {now}. {weekend}"
    if is_working_hours():
        time_note = f"{when} Рабочее время."
    else:
        time_note = (f"{when} НЕРАБОЧЕЕ время (работаем 09:00–23:00). "
                     "Если гость хочет бронь или живого сотрудника — мягко предупреди, "
                     "что подтверждение/ответ сотрудника может быть утром.")

    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": time_note}]
    messages += [{"role": t["role"], "content": t["text"]} for t in turns]

    def _call():
        return ai.chat.completions.create(
            model=MODEL, messages=messages, temperature=0.5, max_tokens=800)

    try:
        resp = await asyncio.to_thread(_call)
        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            raise ValueError("пустой ответ")
        answer, lead, gal, need_human = extract_controls(raw)
        turns.append({"role": "assistant", "text": answer})
        return answer, lead, gal, need_human
    except Exception as e:
        log.warning(f"AI error: {e}")
        return ("Извините, я сейчас не могу ответить. Пожалуйста, свяжитесь с нами: "
                "+998 87 591 33 30 (09:00-18:00) или +998 97 614 77 74 (18:00-23:00)."
                ), None, None, False


# =============================================================================
#  БИЗНЕС-РЕЖИМ (бот отвечает от имени профиля)
# =============================================================================
@dp.business_connection()
async def on_business_connection(conn: BusinessConnection):
    owners[conn.id] = conn.user.id
    log.info(f"Бизнес-подключение {'активно' if conn.is_enabled else 'выключено'} "
             f"(владелец {conn.user.id})")


async def is_owner_message(message: Message) -> bool:
    if not message.business_connection_id or not message.from_user:
        return False
    owner_id = owners.get(message.business_connection_id)
    if owner_id is None:
        try:
            conn = await bot.get_business_connection(message.business_connection_id)
            owner_id = conn.user.id
            owners[message.business_connection_id] = owner_id
        except Exception:
            return False
    return message.from_user.id == owner_id


@dp.business_message()
async def on_business_message(message: Message):
    if await is_owner_message(message):
        return
    if not message.text:
        return
    bcid = message.business_connection_id
    text = message.text

    if detect_location_request(text):
        await send_location_card(message.chat.id, bcid)
        return

    g = detect_gallery_request(text)
    if g == "ask":
        await message.answer("С удовольствием покажу 📸 Какое шале интересует — "
                             "«Люкс» или «Комфорт»?")
        return
    if g in ("lux", "comfort", "exterior") and store["galleries"].get(g):
        await bot.send_chat_action(message.chat.id, "upload_photo",
                                   business_connection_id=bcid)
        if await send_gallery(message.chat.id, bcid, g):
            return

    chat_key = f"{bcid}:{message.chat.id}"
    await bot.send_chat_action(message.chat.id, "typing", business_connection_id=bcid)
    answer, lead, gal, need_human = await ask_ai(chat_key, text)
    if answer:
        await message.answer(answer, reply_markup=links_keyboard())
    elif gal:
        await message.answer("Конечно! Смотрите 👇")
    if gal and store["galleries"].get(gal):
        await bot.send_chat_action(message.chat.id, "upload_photo",
                                   business_connection_id=bcid)
        await send_gallery(message.chat.id, bcid, gal)
    u = message.from_user
    if lead:
        await post_lead(lead, chat_key, guest_source(message), u.username if u else None)
    if need_human:
        await alert_human(guest_source(message), text)


# =============================================================================
#  КОМАНДЫ
# =============================================================================
@dp.message(CommandStart())
async def on_start(message: Message):
    if message.chat.type != "private":
        return
    await message.answer(
        "Assalomu alaykum! Welcome to Zarra Resort & SPA 🌿\n\n"
        "Здравствуйте! Я ассистент резорта. Выберите кнопку ниже или просто "
        "напишите вопрос — отвечу на вашем языке.",
        reply_markup=MAIN_MENU,
    )


@dp.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"Ваш Telegram ID: {message.from_user.id}\n"
                         f"ID этого чата: {message.chat.id}")


@dp.message(Command("setgroup"))
async def cmd_setgroup(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эту команду нужно отправить В ГРУППЕ, куда слать заявки.")
        return
    owner = store.get("owner_id")
    if owner and message.from_user and message.from_user.id != owner:
        return
    store["leads_chat_id"] = message.chat.id
    save_store()
    await message.answer("✅ Готово! Заявки на бронь будут приходить в эту группу.")


def _is_owner(message: Message) -> bool:
    owner = store.get("owner_id")
    return (owner is None) or (message.from_user and message.from_user.id == owner)


def _start_setup(message: Message, cat: str) -> bool:
    uid = message.from_user.id
    if store.get("owner_id") is None:
        store["owner_id"] = uid
    if store["owner_id"] != uid:
        return False
    collecting[uid] = cat
    store["galleries"][cat] = []
    save_store()
    return True


async def _setup(message: Message, cat: str):
    if message.chat.type != "private":
        return
    if not _start_setup(message, cat):
        await message.answer("⛔️ Эта команда доступна только владельцу.")
        return
    await message.answer(
        f"📥 Режим загрузки: {CAT_NAMES[cat].upper()}.\n\n"
        "Отправляй фото/видео ПО ПОРЯДКУ — как обычные фото/видео (со сжатием), "
        "НЕ как «файл». Когда закончишь — /stop."
    )


@dp.message(Command("setup_lux"))
async def cmd_setup_lux(message: Message):
    await _setup(message, "lux")


@dp.message(Command("setup_comfort"))
async def cmd_setup_comfort(message: Message):
    await _setup(message, "comfort")


@dp.message(Command("setup_exterior"))
async def cmd_setup_exterior(message: Message):
    await _setup(message, "exterior")


@dp.message(Command("setup_menu"))
async def cmd_setup_menu(message: Message):
    await _setup(message, "menu")


@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    cat = collecting.pop(message.from_user.id, None)
    if not cat:
        await message.answer("Режим загрузки не был включён.")
        return
    n = len(store["galleries"].get(cat, []))
    await message.answer(f"Готово ✅ В «{CAT_NAMES[cat]}» сохранено: {n}.")


@dp.message(Command("set_location"))
async def cmd_set_location(message: Message):
    if message.chat.type != "private" or not _is_owner(message):
        return
    awaiting_location.add(message.from_user.id)
    await message.answer("📍 Пришли геоточку резорта: скрепка 📎 → «Геопозиция» → "
                         "выбери место на карте и отправь.")


@dp.message(Command("set_address"))
async def cmd_set_address(message: Message):
    if message.chat.type != "private" or not _is_owner(message):
        return
    addr = (message.text or "").partition(" ")[2].strip()
    if not addr:
        await message.answer("Напиши так: /set_address Самарканд, ул. ... (адрес текстом)")
        return
    loc = store.get("location") or {"lat": None, "lon": None}
    loc["address"] = addr
    store["location"] = loc
    save_store()
    await message.answer(f"✅ Адрес сохранён:\n{addr}")


@dp.message(Command("media_status"))
async def cmd_media_status(message: Message):
    if not _is_owner(message):
        return
    lines = [f"• {CAT_NAMES[c]}: {len(store['galleries'].get(c, []))}"
             for c in ("lux", "comfort", "exterior", "menu")]
    lines.append(f"• Группа заявок: {'подключена' if store.get('leads_chat_id') else 'нет'}")
    lines.append(f"• Геолокация: {'есть' if store.get('location') else 'нет'}")
    await message.answer("📊 Статус:\n" + "\n".join(lines))


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if not _is_owner(message):
        return
    leads = store.get("leads", [])
    today = tashkent_now().strftime("%Y-%m-%d")
    today_n = sum(1 for x in leads if x.get("day") == today)
    by = {"new": 0, "in_progress": 0, "confirmed": 0, "rejected": 0}
    for x in leads:
        by[x.get("status", "new")] = by.get(x.get("status", "new"), 0) + 1
    await message.answer(
        "📊 Заявки\n\n"
        f"Сегодня: {today_n}\nВсего: {len(leads)}\n\n"
        f"🆕 Новые: {by['new']}\n🙋 В работе: {by['in_progress']}\n"
        f"✅ Подтверждено: {by['confirmed']}\n❌ Отклонено: {by['rejected']}"
    )


@dp.message(Command("export"))
async def cmd_export(message: Message):
    if not _is_owner(message):
        return
    leads = store.get("leads", [])
    if not leads:
        await message.answer("Заявок пока нет.")
        return
    path = Path(tempfile.gettempdir()) / "zarra_leads.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["№", "Дата", "Шале", "Дата заезда", "Слот", "Гостей",
                    "С ночёвкой", "Повод", "Имя", "Телефон", "Статус",
                    "Обработал", "Гость", "Комментарий"])
        for x in leads:
            d = x.get("data", {})
            w.writerow([x.get("no"), x.get("ts"), d.get("chalet", ""),
                        d.get("date", ""), d.get("slot", ""), d.get("guests_total", ""),
                        d.get("guests_overnight", ""), d.get("occasion", ""),
                        d.get("name", ""), d.get("phone", ""), x.get("status", ""),
                        x.get("by", ""), x.get("source", ""), d.get("notes", "")])
    try:
        await bot.send_document(message.chat.id, FSInputFile(str(path)),
                                caption=f"📄 Заявки: {len(leads)} шт.")
    except Exception as e:
        log.warning(f"export error: {e}")
        await message.answer("Не удалось отправить файл.")


# =============================================================================
#  КНОПКИ (callback) — заявки и выбор галереи
# =============================================================================
@dp.callback_query(F.data.startswith("lead:"))
async def on_lead_action(cb: CallbackQuery):
    action = cb.data.split(":", 1)[1]
    who = cb.from_user.full_name
    if cb.from_user.username:
        who += f" (@{cb.from_user.username})"
    t = tashkent_now().strftime("%d.%m %H:%M")
    base = cb.message.text or ""

    status_map = {"take": "in_progress", "confirm": "confirmed", "reject": "rejected"}
    for rec in store.get("leads", []):
        if rec.get("message_id") == cb.message.message_id and rec.get("chat_id") == cb.message.chat.id:
            rec["status"] = status_map.get(action, rec.get("status"))
            rec["by"] = who
            save_store()
            break

    if action == "take":
        await cb.message.edit_text(base + f"\n🙋 В работе · {who}",
                                   reply_markup=cb.message.reply_markup)
        await cb.answer("Взято в работу")
    elif action == "confirm":
        await cb.message.edit_text(base + f"\n\n✅ ПОДТВЕРЖДЕНО · {who} · {t}")
        await cb.answer("Подтверждено ✅")
    elif action == "reject":
        await cb.message.edit_text(base + f"\n\n❌ ОТКЛОНЕНО · {who} · {t}")
        await cb.answer("Отклонено")
    else:
        await cb.answer()


@dp.callback_query(F.data.startswith("gal:"))
async def on_gallery_pick(cb: CallbackQuery):
    cat = cb.data.split(":", 1)[1]
    await cb.answer()
    if store["galleries"].get(cat):
        await bot.send_chat_action(cb.message.chat.id, "upload_photo")
        await send_gallery(cb.message.chat.id, None, cat)
    else:
        await bot.send_message(cb.message.chat.id, "Фото этого раздела скоро добавим 🙌")


# =============================================================================
#  ГЕОТОЧКА от владельца (после /set_location)
# =============================================================================
@dp.message(F.location)
async def on_location(message: Message):
    if message.chat.type != "private":
        return
    uid = message.from_user.id if message.from_user else None
    if uid not in awaiting_location:
        return
    awaiting_location.discard(uid)
    loc = store.get("location") or {}
    loc["lat"] = message.location.latitude
    loc["lon"] = message.location.longitude
    store["location"] = loc
    save_store()
    await message.answer("✅ Геолокация сохранена! Теперь на вопрос «как добраться» "
                         "бот пришлёт точку на карте.\n"
                         "Адрес текстом можно добавить: /set_address ваш адрес")


# =============================================================================
#  ЗАГРУЗКА ГАЛЕРЕИ (фото/видео от владельца в режиме /setup_*)
# =============================================================================
@dp.message(F.photo | F.video | F.document)
async def on_owner_media(message: Message):
    if message.chat.type != "private":
        return
    uid = message.from_user.id if message.from_user else None
    cat = collecting.get(uid)
    if not cat:
        return
    if message.photo:
        store["galleries"][cat].append({"t": "photo", "id": message.photo[-1].file_id})
    elif message.video:
        store["galleries"][cat].append({"t": "video", "id": message.video.file_id})
    else:
        await message.answer("⚠️ Отправляй как ФОТО/ВИДЕО (со сжатием), не как «файл».")
        return
    save_store()
    await message.answer(f"✅ {len(store['galleries'][cat])}")


# =============================================================================
#  ПРЯМОЕ СООБЩЕНИЕ БОТУ (кнопки-меню + диалог)
# =============================================================================
MENU_PRICES = "🏡 Шале и цены"
MENU_PHOTO = "📸 Фото и видео"
MENU_SLOTS = "📅 Слоты и бронь"
MENU_MAP = "📍 Как добраться"
MENU_REST = "🍽 Меню ресторана"
MENU_CONTACT = "💬 Связаться"


@dp.message()
async def on_direct_message(message: Message):
    if message.chat.type != "private":
        return
    if not message.text:
        return
    text = message.text.strip()

    # Кнопки нижнего меню
    if text == MENU_PRICES:
        await message.answer(PRICES_TEXT)
        return
    if text == MENU_SLOTS:
        await message.answer(SLOTS_TEXT)
        return
    if text == MENU_CONTACT:
        await message.answer(CONTACTS_TEXT)
        return
    if text == MENU_MAP:
        await send_location_card(message.chat.id, None)
        return
    if text == MENU_PHOTO:
        await message.answer("Какое шале показать? 📸", reply_markup=GALLERY_PICK)
        return
    if text == MENU_REST:
        if store["galleries"].get("menu"):
            await send_gallery(message.chat.id, None, "menu")
        else:
            await message.answer("🍽 Ресторан откроется примерно 20 июня 2026 — "
                                 "меню добавим к открытию.")
        return

    # Геолокация по тексту
    if detect_location_request(text):
        await send_location_card(message.chat.id, None)
        return

    # Галерея по ключевым словам
    g = detect_gallery_request(text)
    if g == "ask":
        await message.answer("Какое шале показать? 📸", reply_markup=GALLERY_PICK)
        return
    if g in ("lux", "comfort", "exterior") and store["galleries"].get(g):
        await bot.send_chat_action(message.chat.id, "upload_photo")
        if await send_gallery(message.chat.id, None, g):
            return

    # Иначе — ИИ
    chat_key = f"direct:{message.chat.id}"
    await bot.send_chat_action(message.chat.id, "typing")
    answer, lead, gal, need_human = await ask_ai(chat_key, text)
    if answer:
        await message.answer(answer, reply_markup=links_keyboard())
    elif gal:
        await message.answer("Конечно! Смотрите 👇")
    if gal and store["galleries"].get(gal):
        await bot.send_chat_action(message.chat.id, "upload_photo")
        await send_gallery(message.chat.id, None, gal)
    u = message.from_user
    if lead:
        await post_lead(lead, chat_key, guest_source(message), u.username if u else None)
    if need_human:
        await alert_human(guest_source(message), text)


async def main():
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="stats", description="Статистика заявок (для своих)"),
            BotCommand(command="export", description="Выгрузить заявки (для своих)"),
            BotCommand(command="media_status", description="Что загружено (для своих)"),
        ])
    except Exception as e:
        log.warning(f"set_my_commands: {e}")
    log.info("Бот запущен (v6). Останови командой Ctrl+C.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен.")
