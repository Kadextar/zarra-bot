# -*- coding: utf-8 -*-
# =============================================================================
#  ZARRA RESORT — Telegram AI-ассистент  (версия 5, на Groq)
#  Работает и при прямом общении с ботом, и при подключении к профилю
#  (Настройки -> Автоматизация чатов).
#
#  ЧТО НОВОГО В v5:
#   - Исправлена отправка галереи: теперь решение "показать фото/видео"
#     принимает сам ИИ по контексту всего диалога (а не по словам в одном
#     сообщении). Реальные фото приходят надёжно, без заглушек.
#   - В заявке появилась кнопка-ссылка «✍️ Открыть чат гостя».
#
#  Из v4:
#   - Заявки на бронь уходят в рабочую ГРУППУ с кнопками
#     «✅ Подтвердить / ❌ Отклонить / 🙋 Беру в работу».
#   - В базе знаний: предоплата 50%, условия отмены, вместимость
#     (ночёвка vs посадочные), дни рождения и мероприятия.
#
#  Тебе НЕ нужно ничего здесь программировать. Менять руками можно только
#  блок "БАЗА ЗНАНИЙ" ниже (факты про резорт). Остальное трогать не надо.
#
#  Как подключить группу для заявок:
#   1) создай группу в Telegram (например, «ZARRA · Заявки на бронь»);
#   2) добавь туда бота @zarra_resort_ai_bot и сделай его АДМИНОМ;
#   3) в этой группе отправь команду  /setgroup  — бот её запомнит.
# =============================================================================

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, BusinessConnection, CallbackQuery,
    InputMediaPhoto, InputMediaVideo,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from groq import Groq

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("zarra")

MODEL = "llama-3.3-70b-versatile"


# =============================================================================
#  БАЗА ЗНАНИЙ — это "память" бота. Здесь можно редактировать факты.
# =============================================================================
KNOWLEDGE = """
ZARRA HOTEL & RESORT — премиальный загородный резорт.
Девиз: «Где время становится роскошью».
Telegram: @zarra_resort | Instagram: @zarraresort

ТИПЫ ШАЛЕ (вилл):

1) ШАЛЕ КОМФОРТ — всего 9 вилл.
   - Спальных мест: 2 — то есть С НОЧЁВКОЙ остаться могут максимум 2 человека.
   - Посадочных мест: 10 — днём/вечером можно принять до 10 гостей,
     но переночевать смогут только 2 (остальные — гости на время, без ночёвки).
   - Для семейного отдыха, встреч с близкими, уютных выходных на природе.
   ЦЕНЫ (будни):
   - Слот 1, с 10:00 до 17:00 — 1,5 млн сум
   - Слот 2, с 18:00 до 09:00 — 2 млн сум
   - Слот 3, ПОЛНЫЙ ДЕНЬ (Full day) с 10:00 до 09:00 — 3 млн сум

2) ШАЛЕ ПРЕЗИДЕНТ ЛЮКС — всего 3 виллы.
   - Спальных мест: 7 — С НОЧЁВКОЙ остаться могут до 7 человек.
   - Посадочных мест: 20 — до 20 гостей на мероприятии/днём; ночуют до 7.
   - Просторное премиальное шале для больших компаний и особых событий.
   ЦЕНЫ (будни):
   - Слот 1, с 10:00 до 17:00 — 3 млн сум
   - Слот 2, с 18:00 до 09:00 — 4 млн сум
   - Слот 3, ПОЛНЫЙ ДЕНЬ (Full day) с 10:00 до 09:00 — 6 млн сум

ВАЖНО ПРО ЦЕНЫ:
- По субботам, воскресеньям и в праздничные дни цены ВЫШЕ на 20%.
- Все цены — в узбекских сумах (сум).

МЕРОПРИЯТИЯ:
- На территории можно проводить дни рождения и мероприятия.
- Вместимость по посадочным местам: Комфорт — до 10 гостей, Президент Люкс — до 20.

БРОНИРОВАНИЕ И ОПЛАТА:
- Для подтверждения брони нужна предоплата 50%.
- Отмена и возврат:
  • если гость предупредит об отмене ЗА 3 ДНЯ И БОЛЬШЕ до даты заселения —
    предоплату возвращаем полностью;
  • если позже, чем за 3 дня (например, за 1 день) — предоплата НЕ возвращается (штраф).
  • Чтобы вернуть деньги, отменить нужно минимум за 3 дня до заселения.

УДОБСТВА НА ТЕРРИТОРИИ:
- Бассейн
- Бар
- Тапчаны (зона отдыха)
- В каждом шале есть мангал и казан
- Ресторан — откроется примерно 20 июня 2026 (пока ещё не работает)

КОНТАКТЫ ДЛЯ СВЯЗИ:
- Telegram: @zarra_resort
- Телефон с 09:00 до 18:00: +998 87 591 33 30
- Телефон с 18:00 до 23:00: +998 97 614 77 74

ДОПОЛНИТЕЛЬНО (Азамат, заполни сам, если знаешь — пока бот этого не знает):
- Точный адрес / как добраться: (не указано)
- Можно ли с животными: (не указано)
- Парковка: (не указано)
- Что входит в стоимость (постельное, посуда, дрова и т.п.): (не указано)
"""


# =============================================================================
#  ПРАВИЛА ПОВЕДЕНИЯ — как бот должен себя вести.
# =============================================================================
RULES = """
Ты — вежливый и гостеприимный ассистент резорта ZARRA HOTEL & RESORT.
Ты общаешься от имени резорта в Telegram.

КАК ОБЩАТЬСЯ:
- Определи язык клиента и отвечай НА ТОМ ЖЕ языке (русский, узбекский,
  английский или таджикский).
- Тон — тёплый, премиальный, дружелюбный, без лишней воды. Кратко и по делу.
- Можно использовать лёгкие эмодзи в меру.

ГЛАВНЫЕ ПРАВИЛА (очень важно, не нарушай):
- Используй ТОЛЬКО факты из базы знаний. НИЧЕГО не выдумывай:
  ни цен, ни скидок, ни услуг, ни свободных дат.
- ТЫ НЕ ПОДТВЕРЖДАЕШЬ БРОНЬ и не гарантируешь, что дата свободна.
  Бронь подтверждает только наш сотрудник.
- Если спрашивают то, чего НЕТ в базе знаний — не выдумывай.
  Честно скажи, что уточнишь, и дай контакты для связи.
- Если клиент называет день недели или дату — правильно посчитай цену
  с учётом наценки +20% в субботу, воскресенье и праздники.

ПРО ВМЕСТИМОСТЬ (важно не путать):
- "Спальных мест" — сколько человек могут ОСТАТЬСЯ НА НОЧЬ
  (Комфорт — 2, Президент Люкс — 7).
- "Посадочных мест" — сколько гостей можно принять днём/на мероприятии
  (Комфорт — 10, Президент Люкс — 20).
- Если гость хочет ночевать большим числом, чем есть спальных мест — мягко
  поясни: с ночёвкой могут остаться столько-то, а остальные могут быть гостями
  на время (в пределах посадочных мест).

ПРО ФОТО И ВИДЕО:
- У ассистента есть готовые галереи фото и видео: lux (Президент Люкс),
  comfort (Комфорт), exterior (территория/общие виды).
- Если гость интересуется, как выглядит шале — предложи посмотреть, уточнив,
  какое именно. Например: «Могу показать фото и видео — Люкс или Комфорт?»
- Когда гость согласился посмотреть КОНКРЕТНОЕ шале (или территорию) — добавь
  в самом конце ответа служебный тег: <gallery>lux</gallery>
  (или <gallery>comfort</gallery>, или <gallery>exterior</gallery>).
  Тег служебный — гость его не видит, реальные фото/видео придут автоматически.
- НЕ пиши «отправляю», «галерея загружается», не вставляй заглушки и не
  описывай фото словами. Перед тегом достаточно короткой фразы, например:
  «Конечно! Смотрите 👇». Тег ставь только если гость хочет посмотреть именно
  это шале, и только один тег за ответ.

СБОР ЗАЯВКИ НА БРОНЬ:
- Когда гость хочет забронировать, вежливо собери данные:
  какое шале, дата, слот, сколько гостей всего и сколько с ночёвкой,
  повод (если есть — например, день рождения или мероприятие), имя и телефон.
- Обязательно напомни про предоплату 50% и условия отмены
  (возврат — только при отмене за 3 дня и более до заселения).
- Бронь НЕ подтверждай сам — скажи, что передашь заявку и с гостем свяжутся
  для подтверждения.
- Когда собраны хотя бы: ШАЛЕ, ДАТА, СЛОТ, ИМЯ и ТЕЛЕФОН — добавь в САМОМ
  КОНЦЕ ответа служебный блок СТРОГО в таком формате и больше ничего после него:
  <lead>{"chalet":"","date":"","slot":"","guests_total":"","guests_overnight":"","occasion":"","name":"","phone":"","notes":""}</lead>
- Этот блок служебный, гость его видеть не должен — не упоминай и не показывай его.
  Пустые поля оставляй пустыми. Если не хватает шале/даты/слота/имени/телефона —
  блок НЕ добавляй, а вежливо уточни недостающее.
"""

SYSTEM_PROMPT = RULES + "\n\nБАЗА ЗНАНИЙ:\n" + KNOWLEDGE


# =============================================================================
#  Дальше — техника. Тут менять ничего не нужно.
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
        print("\nНужен бесплатный ключ Groq.")
        print("Получить: зайди на console.groq.com -> API Keys -> Create API Key.")
        groq_key = input("Вставь сюда Groq API ключ и нажми Enter:\n> ").strip()
    env_path.write_text(f"BOT_TOKEN={token}\nGROQ_API_KEY={groq_key}\n", encoding="utf-8")
    return token, groq_key


BOT_TOKEN, GROQ_API_KEY = load_config()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai = Groq(api_key=GROQ_API_KEY)

history: dict[str, list[dict]] = {}
owners: dict[str, int] = {}        # бизнес-подключения: connection_id -> owner_id
last_lead: dict[str, str] = {}     # защита от повторной отправки одной заявки

# --- Хранилище (галереи, владелец, группа заявок, счётчик) ---------------------
STORE_PATH = Path(__file__).parent / "media_store.json"

CAT_NAMES = {"lux": "Шале Люкс", "comfort": "Шале Комфорт", "exterior": "Территория"}
GALLERY_CAPTIONS = {
    "lux": ("🌿 Шале «Президент Люкс»\nСмотрите фото и видео ниже 👇\n"
            "Захотите узнать цены или забронировать — просто напишите, помогу."),
    "comfort": ("🌿 Шале «Комфорт»\nСмотрите фото и видео ниже 👇\n"
                "Нужны цены или бронь — напишите, помогу."),
    "exterior": ("🌿 ZARRA RESORT — наша территория\nСмотрите фото и видео ниже 👇"),
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
    data.setdefault("galleries", {})
    for c in ("lux", "comfort", "exterior"):
        data["galleries"].setdefault(c, [])
    return data


def save_store() -> None:
    STORE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


store = load_store()
collecting: dict[int, str] = {}    # кто сейчас грузит галерею: user_id -> категория


# --- Распознавание "покажи фото/видео" ----------------------------------------
GAL_WORDS = (
    "фото", "видео", "посмотр", "покаж", "показа", "увидет", "как выглядит",
    "галере", "снимк", "rasm", "surat", "video", "photo", "ko'r", "ko‘r",
    "ko'rsat", "look", "picture", "image", "rasmlar",
)
LUX_WORDS = ("люкс", "lux", "президент", "prezident", "люксовый")
COMF_WORDS = ("комфорт", "komfort", "comfort")
EXT_WORDS = ("территор", "бассейн", "снаружи", "exterior", "общие", "вид резорт")


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


# --- Заявки на бронь -----------------------------------------------------------
LEAD_RE = re.compile(r"<lead>\s*(\{.*?\})\s*</lead>", re.DOTALL | re.IGNORECASE)
GALLERY_RE = re.compile(r"<gallery>\s*(lux|comfort|exterior)\s*</gallery>", re.IGNORECASE)


def extract_controls(text: str):
    """Вынимает служебные теги из ответа ИИ.
    Возвращает (чистый_текст, заявка|None, категория_галереи|None)."""
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
    clean = LEAD_RE.sub("", text)
    clean = GALLERY_RE.sub("", clean)
    clean = re.sub(r"</?lead>|</?gallery>", "", clean, flags=re.IGNORECASE)  # на всякий
    return clean.strip(), lead, gal


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
    if u.username:
        return f"@{u.username}"
    return u.full_name or "—"


async def post_lead(lead: dict, chat_key: str, source: str, username: str | None = None):
    """Отправляет заявку в группу (или владельцу), с защитой от дублей."""
    signature = json.dumps(lead, ensure_ascii=False, sort_keys=True)
    if last_lead.get(chat_key) == signature:
        return
    last_lead[chat_key] = signature

    dest = store.get("leads_chat_id") or store.get("owner_id")
    if not dest:
        return

    store["lead_counter"] = int(store.get("lead_counter", 0)) + 1
    save_store()
    text = format_lead(lead, store["lead_counter"], source)
    try:
        await bot.send_message(dest, text, reply_markup=lead_keyboard(username))
    except Exception as e:
        log.warning(f"post_lead error: {e}")


async def ask_ai(chat_key: str, user_text: str):
    """Возвращает (ответ_гостю, заявка|None, категория_галереи|None)."""
    turns = history.setdefault(chat_key, [])
    turns.append({"role": "user", "text": user_text})
    turns[:] = turns[-12:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": t["role"], "content": t["text"]} for t in turns]

    def _call():
        return ai.chat.completions.create(
            model=MODEL, messages=messages, temperature=0.5, max_tokens=800,
        )

    try:
        resp = await asyncio.to_thread(_call)
        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            raise ValueError("пустой ответ")
        answer, lead, gal = extract_controls(raw)
        turns.append({"role": "assistant", "text": answer})
        return answer, lead, gal
    except Exception as e:
        log.warning(f"AI error: {e}")
        return ("Извините, я сейчас не могу ответить. Пожалуйста, свяжитесь с нами: "
                "+998 87 591 33 30 (09:00-18:00) или +998 97 614 77 74 (18:00-23:00)."), None, None


# =============================================================================
#  БИЗНЕС-РЕЖИМ (бот отвечает от имени профиля @zarra_resort)
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
    g = detect_gallery_request(message.text)
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
    answer, lead, gal = await ask_ai(chat_key, message.text)
    if answer:
        await message.answer(answer)
    elif gal:
        await message.answer("Конечно! Смотрите 👇")
    if gal and store["galleries"].get(gal):
        await bot.send_chat_action(message.chat.id, "upload_photo",
                                   business_connection_id=bcid)
        await send_gallery(message.chat.id, bcid, gal)
    if lead:
        u = message.from_user
        await post_lead(lead, chat_key, guest_source(message), u.username if u else None)


# =============================================================================
#  КОМАНДЫ
# =============================================================================
@dp.message(CommandStart())
async def on_start(message: Message):
    if message.chat.type != "private":
        return
    await message.answer(
        "Assalomu alaykum! Welcome to ZARRA HOTEL & RESORT.\n\n"
        "Здравствуйте! Я ассистент резорта. Спросите про шале, цены, "
        "удобства или бронирование — отвечу на вашем языке.\n"
        "Хотите увидеть шале? Напишите, например: «покажите люкс»."
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
        "Отправляй фото и видео ПО ПОРЯДКУ — как обычные фото/видео "
        "(со сжатием), НЕ как «файл». Можно партиями.\n"
        "Когда закончишь — отправь команду /stop."
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


@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    cat = collecting.pop(message.from_user.id, None)
    if not cat:
        await message.answer("Режим загрузки не был включён.")
        return
    n = len(store["galleries"].get(cat, []))
    await message.answer(f"Готово ✅ В «{CAT_NAMES[cat]}» сохранено материалов: {n}.\n"
                         "Можешь проверить: напиши, например, «покажите люкс».")


@dp.message(Command("media_status"))
async def cmd_media_status(message: Message):
    owner = store.get("owner_id")
    if owner and message.from_user.id != owner:
        return
    lines = [f"• {CAT_NAMES[c]}: {len(store['galleries'].get(c, []))}"
             for c in ("lux", "comfort", "exterior")]
    grp = store.get("leads_chat_id")
    lines.append(f"• Группа заявок: {'подключена' if grp else 'не подключена'}")
    await message.answer("📊 Статус:\n" + "\n".join(lines))


# =============================================================================
#  КНОПКИ ПОД ЗАЯВКОЙ (нажатия в группе)
# =============================================================================
@dp.callback_query(F.data.startswith("lead:"))
async def on_lead_action(cb: CallbackQuery):
    action = cb.data.split(":", 1)[1]
    who = cb.from_user.full_name
    if cb.from_user.username:
        who += f" (@{cb.from_user.username})"
    t = (datetime.utcnow() + timedelta(hours=5)).strftime("%d.%m %H:%M")
    base = cb.message.text or ""

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


# =============================================================================
#  ЗАГРУЗКА ГАЛЕРЕИ: владелец прислал фото/видео в режиме /setup_*
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
        await message.answer("⚠️ Отправляй как ФОТО или ВИДЕО (со сжатием), "
                             "а не как «файл». Этот файл я пропустил.")
        return
    save_store()
    await message.answer(f"✅ {len(store['galleries'][cat])}")


# =============================================================================
#  ПРЯМОЕ СООБЩЕНИЕ БОТУ (режим теста)
# =============================================================================
@dp.message()
async def on_direct_message(message: Message):
    if message.chat.type != "private":
        return
    if not message.text:
        return
    g = detect_gallery_request(message.text)
    if g == "ask":
        await message.answer("С удовольствием покажу 📸 Какое шале интересует — "
                             "«Люкс» или «Комфорт»?")
        return
    if g in ("lux", "comfort", "exterior") and store["galleries"].get(g):
        await bot.send_chat_action(message.chat.id, "upload_photo")
        if await send_gallery(message.chat.id, None, g):
            return
    chat_key = f"direct:{message.chat.id}"
    await bot.send_chat_action(message.chat.id, "typing")
    answer, lead, gal = await ask_ai(chat_key, message.text)
    if answer:
        await message.answer(answer)
    elif gal:
        await message.answer("Конечно! Смотрите 👇")
    if gal and store["galleries"].get(gal):
        await bot.send_chat_action(message.chat.id, "upload_photo")
        await send_gallery(message.chat.id, None, gal)
    if lead:
        u = message.from_user
        await post_lead(lead, chat_key, guest_source(message), u.username if u else None)


async def main():
    log.info("Бот запущен (v5). Останови командой Ctrl+C.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен.")
