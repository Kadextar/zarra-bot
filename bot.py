# -*- coding: utf-8 -*-
# =============================================================================
#  ZARRA RESORT — Telegram AI-ассистент  (версия 2, на Groq)
#  Работает и при прямом общении с ботом, и при подключении к профилю
#  (Настройки -> Автоматизация чатов).
#
#  Тебе НЕ нужно ничего здесь программировать. Менять руками можно только
#  блок "БАЗА ЗНАНИЙ" ниже (факты про резорт). Остальное трогать не надо.
# =============================================================================

import os
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, BusinessConnection
from groq import Groq

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("zarra")

# Модель ИИ на Groq (бесплатно). llama-3.3-70b-versatile — умная и многоязычная.
# Можно попробовать другие: "llama-3.1-8b-instant" (быстрее), "qwen3-32b".
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

КОНТАКТЫ ДЛЯ СВЯЗИ С МЕНЕДЖЕРОМ:
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
  Бронь подтверждает только живой менеджер.
- Если клиент готов бронировать — вежливо собери данные:
  какое шале, дата, какой слот, сколько гостей, имя и номер телефона.
  Затем скажи, что передашь заявку менеджеру и он свяжется для подтверждения.
- Если спрашивают то, чего НЕТ в базе знаний — не выдумывай.
  Честно скажи, что уточнишь у менеджера, и дай контакты для связи.
- Если клиент называет день недели или дату — правильно посчитай цену
  с учётом наценки +20% в субботу, воскресенье и праздники.
- Если просят живого человека / оператора — дай контакты менеджера.
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


async def ask_ai(chat_key: str, user_text: str) -> str:
    """Отправляет сообщение в ИИ с учётом истории диалога и возвращает ответ."""
    turns = history.setdefault(chat_key, [])
    turns.append({"role": "user", "text": user_text})
    turns[:] = turns[-12:]  # помним последние ~6 пар реплик

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
        return ("Извините, я сейчас не могу ответить. Пожалуйста, свяжитесь с менеджером: "
                "+998 87 591 33 30 (09:00-18:00) или +998 97 614 77 74 (18:00-23:00).")


@dp.business_connection()
async def on_business_connection(conn: BusinessConnection):
    """Срабатывает при подключении/отключении бота к профилю. Запоминаем владельца."""
    owners[conn.id] = conn.user.id
    log.info(f"Бизнес-подключение {'активно' if conn.is_enabled else 'выключено'} (владелец {conn.user.id})")


async def is_owner_message(message: Message) -> bool:
    """True, если сообщение написал сам владелец профиля (ему не отвечаем)."""
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
    if not message.text:
        return
    if await is_owner_message(message):
        return
    chat_key = f"{message.business_connection_id}:{message.chat.id}"
    await bot.send_chat_action(message.chat.id, "typing",
                               business_connection_id=message.business_connection_id)
    answer = await ask_ai(chat_key, message.text)
    await message.answer(answer)


@dp.message(CommandStart())
async def on_start(message: Message):
    """Приветствие при прямом общении с ботом (для теста)."""
    await message.answer(
        "Assalomu alaykum! Welcome to ZARRA HOTEL & RESORT.\n\n"
        "Здравствуйте! Я ассистент резорта. Спросите про шале, цены, "
        "удобства или бронирование — отвечу на вашем языке."
    )


@dp.message()
async def on_direct_message(message: Message):
    """Прямое сообщение боту (режим теста)."""
    if not message.text:
        return
    chat_key = f"direct:{message.chat.id}"
    await bot.send_chat_action(message.chat.id, "typing")
    answer = await ask_ai(chat_key, message.text)
    await message.answer(answer)


async def main():
    log.info("Бот запущен. Останови командой Ctrl+C.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен.")
