# -*- coding: utf-8 -*-
# =============================================================================
#  ZARRA RESORT — Telegram AI-ассистент  (версия 3, на Groq)
#  Работает и при прямом общении с ботом, и при подключении к профилю
#  (Настройки -> Автоматизация чатов).
#
#  ЧТО НОВОГО В v3:
#   - Галерея фото/видео шале. Гость пишет "покажите люкс / есть фото?" —
#     бот присылает альбом (как обычные фото/видео, не файлы).
#   - Загрузка галереи делается прямо в Telegram: владелец отправляет боту
#     команду /setup_lux, затем сами фото/видео, затем /stop.
#   - Слово "менеджер" больше не используется.
#
#  Тебе НЕ нужно ничего здесь программировать. Менять руками можно только
#  блок "БАЗА ЗНАНИЙ" ниже (факты про резорт). Остальное трогать не надо.
# =============================================================================

import os
import json
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, BusinessConnection, InputMediaPhoto, InputMediaVideo,
)
from groq import Groq

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("zarra")

# Модель ИИ на Groq (бесплатно). llama-3.3-70b-versatile — умная и многоязычная.
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
   - Спальных мест: 2
   - Посадочных мест: 10
   - Для семейного отдыха, встреч с близкими, уютных выходных на природе.
   ЦЕНЫ (будни):
   - Слот 1, с 10:00 до 17:00 — 1,5 млн сум
   - Слот 2, с 18:00 до 09:00 — 2 млн сум
   - Слот 3, ПОЛНЫЙ ДЕНЬ (Full day) с 10:00 до 09:00 — 3 млн сум

2) ШАЛЕ ПРЕЗИДЕНТ ЛЮКС — всего 3 виллы.
   - Спальных мест: 7
   - Посадочных мест: 20
   - Просторное премиальное шале для больших компаний, семейных мероприятий и особых событий.
   ЦЕНЫ (будни):
   - Слот 1, с 10:00 до 17:00 — 3 млн сум
   - Слот 2, с 18:00 до 09:00 — 4 млн сум
   - Слот 3, ПОЛНЫЙ ДЕНЬ (Full day) с 10:00 до 09:00 — 6 млн сум

ВАЖНО ПРО ЦЕНЫ:
- По субботам, воскресеньям и в праздничные дни цены ВЫШЕ на 20%.
- Все цены — в узбекских сумах (сум).

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
- Нужна ли предоплата / депозит: (не указано)
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
- Если клиент готов бронировать — вежливо собери данные:
  какое шале, дата, какой слот, сколько гостей, имя и номер телефона.
  Затем скажи, что передашь заявку и с гостем свяжутся для подтверждения.
- Если спрашивают то, чего НЕТ в базе знаний — не выдумывай.
  Честно скажи, что уточнишь, и дай контакты для связи.
- Если клиент называет день недели или дату — правильно посчитай цену
  с учётом наценки +20% в субботу, воскресенье и праздники.
- Если просят живого человека — дай контакты для связи.

ПРО ФОТО И ВИДЕО:
- У ассистента есть галерея фото и видео шале. Если гость интересуется,
  как выглядит шале — предложи посмотреть фото и видео (галерея отправится
  сама, тебе не нужно вставлять ссылки). Например: «Могу показать фото и
  видео — какое шале интересует, Люкс или Комфорт?»
"""

SYSTEM_PROMPT = RULES + "\n\nБАЗА ЗНАНИЙ:\n" + KNOWLEDGE


# =============================================================================
#  Дальше — техника. Тут менять ничего не нужно.
# =============================================================================

def load_config() -> tuple[str, str]:
    """Читает токен и ключ из .env. Чего не хватает — спросит один раз."""
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

# Память диалогов (только пока бот запущен): { ключ_чата: [ {role, text}, ... ] }
history: dict[str, list[dict]] = {}
# Владельцы бизнес-подключений: { connection_id: id_владельца }
owners: dict[str, int] = {}

# --- Хранилище галереи (file_id фото/видео) — сохраняется в файл ---------------
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
    data.setdefault("galleries", {})
    for c in ("lux", "comfort", "exterior"):
        data["galleries"].setdefault(c, [])
    return data


def save_store() -> None:
    STORE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


store = load_store()
# Кто сейчас в режиме загрузки: { user_id: "lux"/"comfort"/"exterior" }
collecting: dict[int, str] = {}


# --- Определение запроса "покажи фото/видео" ----------------------------------
GAL_WORDS = (
    "фото", "видео", "посмотр", "покаж", "показа", "как выглядит", "галере",
    "снимк", "rasm", "surat", "video", "photo", "ko'r", "ko‘r", "look",
    "picture", "image", "rasmlar",
)
LUX_WORDS = ("люкс", "lux", "президент", "prezident", "люксовый")
COMF_WORDS = ("комфорт", "komfort", "comfort")
EXT_WORDS = ("территор", "бассейн", "снаружи", "exterior", "общие", "вид резорт")


def detect_gallery_request(text: str):
    """Возвращает 'lux'/'comfort'/'exterior' / 'ask' (не уточнено) / None."""
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
    """Отправляет фото/видео шале альбомами (как обычные медиа)."""
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


async def ask_ai(chat_key: str, user_text: str) -> str:
    """Отправляет сообщение в ИИ с учётом истории диалога и возвращает ответ."""
    turns = history.setdefault(chat_key, [])
    turns.append({"role": "user", "text": user_text})
    turns[:] = turns[-12:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": t["role"], "content": t["text"]} for t in turns]

    def _call():
        return ai.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.5,
            max_tokens=800,
        )

    try:
        resp = await asyncio.to_thread(_call)
        answer = (resp.choices[0].message.content or "").strip()
        if not answer:
            raise ValueError("пустой ответ")
        turns.append({"role": "assistant", "text": answer})
        return answer
    except Exception as e:
        log.warning(f"AI error: {e}")
        return ("Извините, я сейчас не могу ответить. Пожалуйста, свяжитесь с нами: "
                "+998 87 591 33 30 (09:00-18:00) или +998 97 614 77 74 (18:00-23:00).")


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
    """Сообщение от клиента в чате подключённого профиля (реальный режим)."""
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
    answer = await ask_ai(chat_key, message.text)
    await message.answer(answer)


# =============================================================================
#  КОМАНДЫ (работают в личном чате с ботом)
# =============================================================================
@dp.message(CommandStart())
async def on_start(message: Message):
    await message.answer(
        "Assalomu alaykum! Welcome to ZARRA HOTEL & RESORT.\n\n"
        "Здравствуйте! Я ассистент резорта. Спросите про шале, цены, "
        "удобства или бронирование — отвечу на вашем языке.\n"
        "Хотите увидеть шале? Напишите, например: «покажите люкс»."
    )


@dp.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"Ваш Telegram ID: {message.from_user.id}")


def _start_setup(message: Message, cat: str) -> bool:
    """Включает режим загрузки для категории. Первый запустивший — владелец."""
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
    await message.answer("📊 Загружено материалов:\n" + "\n".join(lines))


# =============================================================================
#  ЗАГРУЗКА ГАЛЕРЕИ: владелец прислал фото/видео в режиме /setup_*
# =============================================================================
@dp.message(F.photo | F.video | F.document)
async def on_owner_media(message: Message):
    uid = message.from_user.id if message.from_user else None
    cat = collecting.get(uid)
    if not cat:
        return  # не в режиме загрузки — игнорируем медиа
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
    answer = await ask_ai(chat_key, message.text)
    await message.answer(answer)


async def main():
    log.info("Бот запущен (v3). Останови командой Ctrl+C.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен.")
