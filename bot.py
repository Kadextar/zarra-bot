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
import time
import asyncio
import logging
import tempfile
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import Counter, deque

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, BusinessConnection, CallbackQuery, BotCommand, FSInputFile,
    InputMediaPhoto, InputMediaVideo,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    BotCommandScopeDefault, BotCommandScopeChat, WebAppInfo, BufferedInputFile,
)
from groq import Groq

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("zarra")

MODEL = "llama-3.3-70b-versatile"

# Рабочие часы (время Ташкента, UTC+5). Вне этих часов бот предупреждает гостя.
WORK_START, WORK_END = 9, 23

# Праздничные дни Узбекистана — на эти даты цена +20%, как в выходные.
# Формат: "ГГГГ-ММ-ДД". Религиозные праздники (Хайит) сдвигаются каждый год —
# проверяй и обновляй список раз в год.
HOLIDAYS = {
    "2026-01-01",  # Новый год
    "2026-01-14",  # День защитников Родины
    "2026-03-08",  # Международный женский день
    "2026-03-20",  # Рамазан-хайит (ориентировочно — уточнить)
    "2026-03-21",  # Навруз
    "2026-05-09",  # День памяти и почестей
    "2026-05-27",  # Курбан-хайит (ориентировочно — уточнить)
    "2026-09-01",  # День независимости
    "2026-10-01",  # День учителя и наставника
    "2026-12-08",  # День Конституции
}


def is_surcharge_day(dt: datetime) -> bool:
    """+20% действует в субботу, воскресенье и в праздничные дни."""
    return dt.weekday() >= 5 or dt.strftime("%Y-%m-%d") in HOLIDAYS


# =============================================================================
#  БАЗА ЗНАНИЙ — это "память" бота. Здесь можно редактировать факты.
# =============================================================================
KNOWLEDGE = """
Zarra Resort & SPA — премиальный загородный резорт.
Девиз: «Где время становится роскошью».
Telegram: @zarra_resort | Instagram: @zarraresort

ТИПЫ ШАЛЕ (вилл):

1) ШАЛЕ КОМФОРТ — всего 9 вилл (можно бронировать до 9 одновременно на одну дату).
   - Спальных мест: 2 — С НОЧЁВКОЙ остаться могут максимум 2 человека.
   - Посадочных мест: 10 — днём/вечером можно принять до 10 гостей,
     но переночевать смогут только 2.
   ЦЕНЫ — формат «будни / выходные (Сб, Вс, праздники +20%)»:
   - Слот 1, с 10:00 до 17:00 (7 часов) — 1,5 млн / 1,8 млн сум
   - Слот 2, с 18:00 до 09:00 (15 часов) — 2 млн / 2,4 млн сум
   - Слот 3, ПОЛНЫЙ ДЕНЬ с 10:00 до 09:00 (23 часа) — 3 млн / 3,6 млн сум

2) ШАЛЕ ПРЕЗИДЕНТ ЛЮКС — всего 3 виллы (до 3 одновременно на одну дату).
   - Спальных мест: 7 — С НОЧЁВКОЙ остаться могут до 7 человек.
   - Посадочных мест: 20 — до 20 гостей на мероприятии; ночуют до 7.
   ЦЕНЫ — формат «будни / выходные (Сб, Вс, праздники +20%)»:
   - Слот 1, с 10:00 до 17:00 (7 часов) — 3 млн / 3,6 млн сум
   - Слот 2, с 18:00 до 09:00 (15 часов) — 4 млн / 4,8 млн сум
   - Слот 3, ПОЛНЫЙ ДЕНЬ с 10:00 до 09:00 (23 часа) — 6 млн / 7,2 млн сум

ВАЖНО ПРО ЦЕНЫ:
- По субботам, воскресеньям и в праздничные дни цены ВЫШЕ на 20% (см. суммы выше).
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
- Ресторан — уже работает.

МЕНЮ РЕСТОРАНА (цены в сумах):
Шашлыки:
- Молотый шашлык — 50 000
- Корейка — 85 000
- Куриное бедро — 45 000
- Куриное филе — 38 000
- Куриные крылышки — 40 000
Жиз (обжаренное мясо):
- Жиз Бон-филе (вырезка) — 400 000 за кг
- Жиз из корейки — 350 000 за кг
Пивной сет — 120 000 (курут, миндаль, чипсы, сырные палочки, кольца кальмара, кешью).
Копчёная рыба — 100 000.
Холодные закуски:
- Чакка — 20 000
- Свежий салат — 40 000
- Лимон — 15 000
Хлеб ассорти — 26 000.

Безалкогольные напитки:
- Кола (1,5 л) — 25 000
- Фанта (1,5 л) — 25 000
- Спрайт (1,5 л) — 25 000
- Минеральная вода (1,5 л, 2 вида) — 15 000
- Chortoq (0,5 л) — 25 000
- Сок ассорти — 20 000
Пиво:
- Президент (0,5 л) — 20 000
- Шымкент (0,5 л) — 25 000
- Злата 10 (0,5 л) — 20 000
- Эфес — 35 000
Чай:
- Чёрный — 10 000
- Зелёный — 10 000
- Лимонный — 20 000
Водка:
- E Factor (0,5 л) — 100 000
- New Uzbekistan (0,5 л) — 110 000
- Gold UZB (0,7 л) — 280 000
- Столичное (0,5 л) — 140 000

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

ПОДБОР ПОД МЕРОПРИЯТИЕ (важно, будь как консьерж):
- Если гость описывает событие (повод, число гостей, дата, пожелания) — АКТИВНО
  подбери: какое шале подходит по числу гостей (до 10 — Комфорт; 11–20 — Люкс;
  больше 20 — предложи несколько вилл и связь с сотрудником), какой слот уместен
  (день рождения днём — слот 1 или 3; ночёвка — слот 2/3), и назови ПРИМЕРНУЮ
  стоимость для нужной даты (учитывай +20% в выходные/праздники; бери цены из
  блока актуальных цен).
- Предложи 3–5 подходящих позиций из меню под повод (шашлыки, пивной сет и т.п.).
- В конце мягко предложи оформить бронь (собрать данные) — но не выдумывай итог
  и не занимайся оплатой. Пиши «примерно/ориентировочно», финал подтверждает сотрудник.

СЛУЖЕБНЫЕ ТЕГИ (гость их НЕ видит, не упоминай и не показывай их):
1) ФОТО/ВИДЕО: когда гость согласился посмотреть конкретное шале — добавь
   в конце ответа тег <gallery>lux</gallery> (или comfort, exterior, menu).
   Не пиши «отправляю/загружается», не описывай фото — они придут сами.
   Перед тегом достаточно короткой фразы: «Конечно! Смотрите 👇».
2) ЗАЯВКА НА БРОНЬ: собери шале, дату, слот, сколько гостей всего и с ночёвкой,
   повод (если есть), имя и телефон. Бронь НЕ подтверждай и оплатой НЕ занимайся:
   не считай предоплату, не проси перевести деньги, не объясняй, куда платить —
   этим займётся живой сотрудник.
   КАК ТОЛЬКО собраны 5 обязательных полей (ШАЛЕ, ДАТА, СЛОТ, ИМЯ, ТЕЛЕФОН), ты
   ОБЯЗАН в самом конце ответа отдельной строкой поставить тег заявки. Без этого
   тега заявка НЕ уйдёт сотруднику, поэтому говорить «передал заявку» без тега
   НЕЛЬЗЯ. Формат (заполни поля собранными данными, лишнее оставь пустым):
   <lead>{"chalet":"","date":"","slot":"","guests_total":"","guests_overnight":"","occasion":"","name":"","phone":"","notes":""}</lead>
   Только ВМЕСТЕ с этим тегом скажи гостю: «Заявку передал нашему сотруднику, он
   скоро свяжется для подтверждения». Если хотя бы одного из 5 полей нет — тег НЕ
   ставь и не пиши, что передал; вежливо уточни недостающее.
3) НУЖЕН ЧЕЛОВЕК: если гость просит живого сотрудника, недоволен, жалуется
   или вопрос срочный/нестандартный — добавь тег <human/>. При этом сам
   вежливо ответь и дай контакты для связи.
"""

SYSTEM_PROMPT = RULES + "\n\nБАЗА ЗНАНИЙ:\n" + KNOWLEDGE


# Персона для ГРУППОВОГО чата — тёплый дружелюбный помощник, который
# поддерживает беседу. Отвечает, только когда к нему обратились.
GROUP_RULES = """
Ты — Zarra, дружелюбный и отзывчивый помощник резорта Zarra Resort & SPA.
Ты участник этого группового чата и общаешься с людьми по-приятельски.
Представляйся именно как помощник (ассистент), а не как «хозяин» или владелец.

КАК ОБЩАТЬСЯ:
- Тепло, живо, по-человечески, с лёгким юмором в меру. Коротко — 1–3 предложения.
- Определи язык собеседника и ответь на нём (русский, узбекский, английский).
- Без markdown и спецсимволов (* _ # `). Эмодзи можно, в меру (1–2).
- Поддерживай беседу: можно поболтать на общие темы, дать дружеский совет
  (про отдых, досуг, как круто провести выходные, природу и т.п.).

ГЛАВНОЕ:
- Про резорт говори ТОЛЬКО факты из базы знаний. Цены и условия не выдумывай.
- Бронированием в чате НЕ занимайся и заявки не собирай. Если кто-то хочет
  забронировать — по-доброму предложи написать боту в личку и нажать
  «Забронировать» (или связаться: @zarra_resort).
- Не упоминай, что ты ИИ или языковая модель. Не пиши служебных тегов.
- Если вопрос не про резорт — просто дружелюбно поддержи разговор и помоги.
"""
GROUP_SYSTEM = GROUP_RULES + "\n\nБАЗА ЗНАНИЙ:\n" + KNOWLEDGE


# --- Готовые тексты для кнопок (3 языка) ---------------------------------------
# {c1..l3} — цены (будни / выходные), подставляются в build_prices_text().
PRICES_TEXT = {
    "ru": (
        "🏡 Наши шале (цены: будни / выходные)\n\n"
        "«Комфорт» (9 вилл) — ночёвка до 2 чел., днём до 10 гостей:\n"
        "• День 10:00–17:00 — {c1}\n• Ночь 18:00–09:00 — {c2}\n"
        "• Полный день — {c3}\n\n"
        "«Президент Люкс» (3 виллы) — ночёвка до 7 чел., до 20 гостей:\n"
        "• День 10:00–17:00 — {l1}\n• Ночь 18:00–09:00 — {l2}\n"
        "• Полный день — {l3}\n\n"
        "Выходные (Сб, Вс) и праздники +20%. Цены в сумах.\n"
        "Можно проводить дни рождения и мероприятия 🎉\n"
        "Предоплата 50%, возврат при отмене за 3+ дня.\n\n"
        "Хотите фото или забронировать? Просто напишите 🙂"),
    "uz": (
        "🏡 Bizning shalelar (narx: ish kuni / dam olish)\n\n"
        "«Komfort» (9 villa) — tunash 2 kishigacha, kunduzi 10 mehmongacha:\n"
        "• Kunduzi 10:00–17:00 — {c1}\n• Tunda 18:00–09:00 — {c2}\n"
        "• To‘liq kun — {c3}\n\n"
        "«Prezident Lyuks» (3 villa) — tunash 7 kishigacha, 20 mehmongacha:\n"
        "• Kunduzi 10:00–17:00 — {l1}\n• Tunda 18:00–09:00 — {l2}\n"
        "• To‘liq kun — {l3}\n\n"
        "Dam olish kunlari (Sha, Yak) va bayramlarda +20%. Narxlar so‘mda.\n"
        "Tug‘ilgan kun va tadbirlar o‘tkazish mumkin 🎉\n"
        "50% oldindan to‘lov, 3+ kun oldin bekor qilsangiz qaytariladi.\n\n"
        "Foto yoki bron kerakmi? Shunchaki yozing 🙂"),
    "en": (
        "🏡 Our chalets (prices: weekday / weekend)\n\n"
        "“Comfort” (9 villas) — overnight up to 2, daytime up to 10 guests:\n"
        "• Day 10:00–17:00 — {c1}\n• Night 18:00–09:00 — {c2}\n"
        "• Full day — {c3}\n\n"
        "“President Lux” (3 villas) — overnight up to 7, up to 20 guests:\n"
        "• Day 10:00–17:00 — {l1}\n• Night 18:00–09:00 — {l2}\n"
        "• Full day — {l3}\n\n"
        "Weekends (Sat, Sun) and holidays +20%. Prices in UZS (so‘m).\n"
        "Birthdays and events are welcome 🎉\n"
        "50% prepayment, refundable if cancelled 3+ days ahead.\n\n"
        "Want photos or to book? Just write 🙂"),
}
SLOTS_TEXT = {
    "ru": (
        "📅 Слоты бронирования\n\n"
        "• Слот 1 — день, 10:00–17:00\n"
        "• Слот 2 — ночь, 18:00–09:00\n"
        "• Слот 3 — полный день, 10:00–09:00\n\n"
        "Цены зависят от шале (см. «🏡 Шале и цены»). Сб/Вс/праздники +20%.\n"
        "Для брони нужна предоплата 50%. Возврат — при отмене за 3+ дня.\n\n"
        "Чтобы забронировать — нажмите «📝 Забронировать» 🙌"),
    "uz": (
        "📅 Bron vaqtlari\n\n"
        "• Slot 1 — kunduzi, 10:00–17:00\n"
        "• Slot 2 — tunda, 18:00–09:00\n"
        "• Slot 3 — to‘liq kun, 10:00–09:00\n\n"
        "Narx shalega bog‘liq («🏡 Shale va narxlar»). Shanba/yakshanba/bayram +20%.\n"
        "Bron uchun 50% oldindan to‘lov. 3+ kun oldin bekor — qaytariladi.\n\n"
        "Bron qilish uchun «📝 Bron qilish» tugmasini bosing 🙌"),
    "en": (
        "📅 Booking slots\n\n"
        "• Slot 1 — day, 10:00–17:00\n"
        "• Slot 2 — night, 18:00–09:00\n"
        "• Slot 3 — full day, 10:00–09:00\n\n"
        "Prices depend on the chalet (see “🏡 Chalets & prices”). Sat/Sun/holidays +20%.\n"
        "Booking needs a 50% prepayment. Refundable if cancelled 3+ days ahead.\n\n"
        "To book — tap “📝 Book now” 🙌"),
}
CONTACTS_TEXT = {
    "ru": ("💬 Связаться с нами\n\n"
           "📞 09:00–18:00: +998 87 591 33 30\n"
           "📞 18:00–23:00: +998 97 614 77 74\n"
           "Telegram: @zarra_resort\nInstagram: @zarraresort"),
    "uz": ("💬 Biz bilan bog‘lanish\n\n"
           "📞 09:00–18:00: +998 87 591 33 30\n"
           "📞 18:00–23:00: +998 97 614 77 74\n"
           "Telegram: @zarra_resort\nInstagram: @zarraresort"),
    "en": ("💬 Contact us\n\n"
           "📞 09:00–18:00: +998 87 591 33 30\n"
           "📞 18:00–23:00: +998 97 614 77 74\n"
           "Telegram: @zarra_resort\nInstagram: @zarraresort"),
}


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
group_history: dict[int, list[dict]] = {}   # болтовня в группах
pending_broadcast: dict[int, str] = {}      # {owner_id: текст рассылки на подтверждении}
BOT_ID: int | None = None                   # заполняется при старте
BOT_USERNAME: str | None = None

# Анти-спам: не больше RATE_MAX сообщений за RATE_WINDOW секунд от одного чата.
_msg_times: dict[int, deque] = {}
RATE_MAX = 15
RATE_WINDOW = 60
# Отдельный, более мягкий лимит на ответы бота в группе (чтобы не флудил).
_group_times: dict[int, deque] = {}
GROUP_RATE_MAX = 8
GROUP_RATE_WINDOW = 60


def _group_throttled(chat_id: int) -> bool:
    now = time.monotonic()
    dq = _group_times.setdefault(chat_id, deque())
    while dq and now - dq[0] > GROUP_RATE_WINDOW:
        dq.popleft()
    if len(dq) >= GROUP_RATE_MAX:
        return True
    dq.append(now)
    return False


def is_rate_limited(chat_id: int) -> bool:
    now = time.monotonic()
    dq = _msg_times.setdefault(chat_id, deque())
    while dq and now - dq[0] > RATE_WINDOW:
        dq.popleft()
    if len(dq) >= RATE_MAX:
        return True
    dq.append(now)
    return False

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
    data.setdefault("chats", {})   # follow-up: {chat_key: {chat_id, bcid, is_business, last_ts, last_day, has_lead, followed_up, relay}}
    data.setdefault("daily", {})   # аналитика: {"YYYY-MM-DD": {"inq": N}}
    data.setdefault("admins", [])      # [{"username":.., "user_id":..}] — кому слать сводку
    data.setdefault("relay_map", {})   # {group_msg_id(str): chat_key} — для чата с гостем
    data.setdefault("langs", {})       # {chat_id(str): "ru"|"uz"|"en"}
    data.setdefault("booked", [])      # [{chalet,date(iso),slot,lead_no}] — занятые даты
    data.setdefault("src", {})         # {chat_id(str): "instagram"} — источник гостя
    data.setdefault("src_starts", {})  # {"instagram": N} — заходов по источнику
    data.setdefault("webapp_url", None)  # ссылка на мини-приложение (Netlify и т.п.)
    data.setdefault("prices", {})      # переопределение цен: {chalet:{"wd":{s:str},"we":{s:str}}}
    data.setdefault("announce", None)  # объявление/акция (текст) — в ответы ИИ и «Шале и цены»
    return data


def save_store() -> None:
    # Пишем во временный файл и атомарно подменяем — чтобы при падении/ребуте
    # в момент записи база заявок и галерей не повредилась.
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STORE_PATH)


store = load_store()
collecting: dict[int, str] = {}        # загрузка галереи: user_id -> категория
awaiting_location: set[int] = set()    # ждём геоточку от владельца


# --- Администраторы (получатели сводки, доступ к статистике) --------------------
def _norm_uname(u) -> str:
    return (str(u) if u else "").lstrip("@").lower()


def add_admin_username(username: str) -> None:
    uname = _norm_uname(username)
    if not uname:
        return
    for a in store["admins"]:
        if _norm_uname(a.get("username")) == uname:
            return
    store["admins"].append({"username": uname, "user_id": None})


def admin_ids() -> set:
    return {a["user_id"] for a in store.get("admins", []) if a.get("user_id")}


def staff_ids() -> set:
    ids = set(admin_ids())
    if store.get("owner_id"):
        ids.add(store["owner_id"])
    return ids


def _is_staff(message: Message) -> bool:
    owner = store.get("owner_id")
    uid = message.from_user.id if message.from_user else None
    if owner is None:
        return True   # пока владелец не задан — как раньше (бутстрап)
    return uid == owner or uid in admin_ids()


def capture_admin(message: Message) -> bool:
    """Если пишет пользователь с ником из списка админов — запоминаем его ID."""
    u = message.from_user
    if not u or not u.username:
        return False
    uname = u.username.lower()
    changed = False
    for a in store.get("admins", []):
        if _norm_uname(a.get("username")) == uname and a.get("user_id") != u.id:
            a["user_id"] = u.id
            changed = True
    if changed:
        save_store()
    return changed


# Администраторы добавляются вручную командой /add_admin @username.

# --- Бэкапы базы (заявки/галереи) ----------------------------------------------
BACKUP_DIR = Path(__file__).parent / "backups"
BACKUP_KEEP = 14   # сколько последних дневных копий хранить


def backup_store() -> None:
    """Раз в сутки кладёт копию базы в backups/ и чистит старые."""
    if not STORE_PATH.exists():
        return
    try:
        BACKUP_DIR.mkdir(exist_ok=True)
        day = tashkent_now().strftime("%Y-%m-%d")
        dest = BACKUP_DIR / f"store-{day}.json"
        if dest.exists():
            return  # сегодня уже делали
        dest.write_text(STORE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        backups = sorted(BACKUP_DIR.glob("store-*.json"))
        for old in backups[:-BACKUP_KEEP]:
            old.unlink()
    except Exception as e:
        log.warning(f"backup error: {e}")


# --- Время / рабочие часы ------------------------------------------------------
def tashkent_now() -> datetime:
    # Ташкент = UTC+5 круглый год (без перехода на летнее время).
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5)


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


async def send_location_card(chat_id: int, bcid, lang: str = "ru") -> None:
    loc = store.get("location")
    if loc and loc.get("lat") is not None:
        try:
            await bot.send_location(chat_id, latitude=loc["lat"], longitude=loc["lon"],
                                    business_connection_id=bcid)
        except Exception as e:
            log.warning(f"send_location error: {e}")
        addr = loc.get("address") or ""
        addr = (addr + "\n") if addr else ""
        await bot.send_message(chat_id, L(lang, "loc_card", addr=addr),
                               business_connection_id=bcid)
    else:
        await bot.send_message(chat_id, L(lang, "loc_no") + CONTACTS_TEXT[lang],
                               business_connection_id=bcid)


# =============================================================================
#  ЛОКАЛИЗАЦИЯ (ru / uz / en)
# =============================================================================
LANGS = ("ru", "uz", "en")
DEFAULT_LANG = "ru"

# Подписи кнопок нижнего меню на 3 языках (ключ = действие).
BTN = {
    "book":    {"ru": "📝 Забронировать", "uz": "📝 Bron qilish",      "en": "📝 Book now"},
    "prices":  {"ru": "🏡 Шале и цены",   "uz": "🏡 Shale va narxlar", "en": "🏡 Chalets & prices"},
    "photo":   {"ru": "📸 Фото и видео",  "uz": "📸 Foto va video",    "en": "📸 Photos & videos"},
    "slots":   {"ru": "📅 Слоты и бронь", "uz": "📅 Vaqt va bron",     "en": "📅 Slots & booking"},
    "map":     {"ru": "📍 Как добраться", "uz": "📍 Qanday borish",    "en": "📍 How to get there"},
    "rest":    {"ru": "🍽 Меню ресторана", "uz": "🍽 Restoran menyusi", "en": "🍽 Restaurant menu"},
    "event":   {"ru": "🎉 Мероприятие",   "uz": "🎉 Tadbir",           "en": "🎉 Event planner"},
    "contact": {"ru": "💬 Связаться",     "uz": "💬 Bog‘lanish",       "en": "💬 Contact us"},
}
# Обратный поиск: текст кнопки на любом языке -> ключ действия.
BTN_LOOKUP = {label: key for key, tr in BTN.items() for label in tr.values()}
MENU_TEXTS = set(BTN_LOOKUP.keys())
BOOK_LABELS = set(BTN["book"].values())

PLACEHOLDER = {"ru": "Выберите или напишите вопрос…",
               "uz": "Tugma tanlang yoki yozing…",
               "en": "Choose a button or type…"}

# Прочие строки интерфейса (прямой бот + мастер брони).
T = {
    "greeting": {
        "ru": ("Assalomu alaykum! Welcome to Zarra Resort & SPA 🌿\n\n"
               "Здравствуйте! Я ассистент резорта. Выберите кнопку ниже или просто "
               "напишите вопрос — отвечу на вашем языке."),
        "uz": ("Assalomu alaykum! Zarra Resort & SPA ga xush kelibsiz 🌿\n\n"
               "Men rezortning yordamchisiman. Quyidagi tugmani tanlang yoki "
               "savolingizni yozing — tilingizda javob beraman."),
        "en": ("Assalomu alaykum! Welcome to Zarra Resort & SPA 🌿\n\n"
               "I'm the resort assistant. Tap a button below or just type your "
               "question — I'll reply in your language."),
    },
    "choose_lang": {
        "ru": "Выберите язык 👇", "uz": "Tilni tanlang 👇", "en": "Choose a language 👇"},
    "lang_set": {
        "ru": "Готово! Отвечаю на русском 🌿",
        "uz": "Tayyor! O‘zbek tilida javob beraman 🌿",
        "en": "Done! I'll reply in English 🌿"},
    "photo_ask": {
        "ru": "Какое шале показать? 📸", "uz": "Qaysi shaleni ko‘rsatay? 📸",
        "en": "Which chalet should I show? 📸"},
    "rest_closed": {
        "ru": "🍽 Ресторан работает! Напишите, что интересует из меню (шашлыки, напитки и т.д.) — подскажу цены. Фото-меню добавим скоро.",
        "uz": "🍽 Restoran ishlayapti! Menyudan nima qiziqtirsa yozing (shashlik, ichimliklar va h.k.) — narxini aytaman. Foto-menyu tez orada.",
        "en": "🍽 The restaurant is open! Tell me what you'd like from the menu (kebabs, drinks, etc.) and I'll share prices. Photo menu coming soon."},
    "ai_error": {
        "ru": ("Извините, сейчас не могу ответить. Свяжитесь с нами: "
               "+998 87 591 33 30 (09:00–18:00) или +998 97 614 77 74 (18:00–23:00)."),
        "uz": ("Kechirasiz, hozir javob bera olmayapman. Biz bilan bog‘laning: "
               "+998 87 591 33 30 (09:00–18:00) yoki +998 97 614 77 74 (18:00–23:00)."),
        "en": ("Sorry, I can't reply right now. Please contact us: "
               "+998 87 591 33 30 (09:00–18:00) or +998 97 614 77 74 (18:00–23:00).")},
    "voice_fail": {
        "ru": "Извините, голосовое не разобрал 🙈 Напишите, пожалуйста, текстом.",
        "uz": "Kechirasiz, ovozli xabarni tushunmadim 🙈 Iltimos, matn bilan yozing.",
        "en": "Sorry, I couldn't understand the voice message 🙈 Please type it."},
    "followup": {
        "ru": ("Здравствуйте! 🙂 Вы недавно интересовались отдыхом в Zarra Resort & SPA. "
               "Подсказать что-то ещё или придержать удобную дату? Будем рады помочь."),
        "uz": ("Assalomu alaykum! 🙂 Yaqinda Zarra Resort & SPA bilan qiziqgandingiz. "
               "Yana nimadir kerakmi yoki qulay sanani ushlab turaymi? Yordam beramiz."),
        "en": ("Hello! 🙂 You recently asked about a stay at Zarra Resort & SPA. "
               "Anything else I can help with, or shall we hold a date for you?")},
    "loc_no": {
        "ru": "📍 Точный адрес уточните, пожалуйста, у нас:\n",
        "uz": "📍 Aniq manzilni biz bilan aniqlang:\n",
        "en": "📍 Please check the exact address with us:\n"},
    "loc_card": {
        "ru": "📍 Zarra Resort & SPA\n{addr}Точка на карте — выше 👆\nНужна помощь с дорогой? +998 87 591 33 30",
        "uz": "📍 Zarra Resort & SPA\n{addr}Xarita nuqtasi — yuqorida 👆\nYo‘l kerakmi? +998 87 591 33 30",
        "en": "📍 Zarra Resort & SPA\n{addr}Map pin is above 👆\nNeed directions? +998 87 591 33 30"},
    # --- Мастер брони ---
    "bk_start": {
        "ru": "Отлично, давайте забронируем! 🌿\nВыберите шале:",
        "uz": "Ajoyib, bron qilamiz! 🌿\nShaleni tanlang:",
        "en": "Great, let's book! 🌿\nChoose a chalet:"},
    "bk_chalet_comfort": {
        "ru": "🏡 Комфорт (ночёвка до 2, до 10 гостей)",
        "uz": "🏡 Komfort (tunash 2 gacha, 10 mehmon)",
        "en": "🏡 Comfort (overnight up to 2, 10 guests)"},
    "bk_chalet_lux": {
        "ru": "👑 Президент Люкс (ночёвка до 7, до 20)",
        "uz": "👑 Prezident Lyuks (tunash 7 gacha, 20)",
        "en": "👑 President Lux (overnight up to 7, 20)"},
    "bk_slot_prompt": {
        "ru": "Выберите тариф (слот по времени) 👇",
        "uz": "Tarifni (vaqt slotini) tanlang 👇",
        "en": "Choose a tariff (time slot) 👇"},
    "bk_chalet_set": {"ru": "🏡 Шале: {v} ✅", "uz": "🏡 Shale: {v} ✅", "en": "🏡 Chalet: {v} ✅"},
    "bk_slot_set": {"ru": "⏰ Слот: {v} ✅", "uz": "⏰ Slot: {v} ✅", "en": "⏰ Slot: {v} ✅"},
    "bk_date": {
        "ru": "На какую дату планируете?\nНапишите день и месяц — например: 5 июля или 12.07",
        "uz": "Qaysi sanaga rejalashtiryapsiz?\nKun va oyni yozing — masalan: 5-iyul yoki 12.07",
        "en": "What date are you planning?\nWrite day and month — e.g. July 5 or 12.07"},
    "bk_guests": {
        "ru": "Сколько гостей всего ожидается? (числом)",
        "uz": "Jami nechta mehmon kutilyapti? (raqamda)",
        "en": "How many guests in total? (a number)"},
    "bk_name": {
        "ru": "На чьё имя оформить бронь? Напишите имя 🙂",
        "uz": "Bron kim nomiga? Ismni yozing 🙂",
        "en": "What name is the booking under? Type a name 🙂"},
    "bk_phone": {
        "ru": "Оставьте номер телефона для связи.\nМожно нажать кнопку ниже или написать вручную 👇",
        "uz": "Bog‘lanish uchun telefon raqamingizni qoldiring.\nTugmani bosing yoki qo‘lda yozing 👇",
        "en": "Leave a phone number for contact.\nTap the button below or type it 👇"},
    "bk_comment": {
        "ru": "Есть особые пожелания или повод? (день рождения, торт, оформление…)\nНапишите или нажмите «Пропустить».",
        "uz": "Maxsus istak yoki sabab bormi? (tug‘ilgan kun, tort, bezak…)\nYozing yoki «O‘tkazib yuborish»ni bosing.",
        "en": "Any special wishes or occasion? (birthday, cake, decor…)\nType it or tap “Skip”."},
    "bk_confirm_title": {
        "ru": "Проверьте заявку 👇", "uz": "Arizani tekshiring 👇", "en": "Please check your request 👇"},
    "bk_confirm_ask": {
        "ru": "Всё верно? Нажмите «✅ Отправить заявку».",
        "uz": "Hammasi to‘g‘rimi? «✅ Yuborish»ni bosing.",
        "en": "All correct? Tap “✅ Send request”."},
    "bk_done": {
        "ru": ("Готово! Заявку передал нашему сотруднику ✅\n"
               "Он скоро свяжется с вами для подтверждения. Спасибо, что выбрали "
               "Zarra Resort & SPA 🌿"),
        "uz": ("Tayyor! Arizangiz xodimimizga yuborildi ✅\n"
               "Tez orada tasdiqlash uchun bog‘lanadi. Zarra Resort & SPA ni "
               "tanlaganingiz uchun rahmat 🌿"),
        "en": ("Done! Your request was sent to our staff ✅\n"
               "They'll contact you shortly to confirm. Thank you for choosing "
               "Zarra Resort & SPA 🌿")},
    "bk_done_nogroup": {
        "ru": "Спасибо! Данные принял 🙌 Для подтверждения свяжитесь с нами:\n",
        "uz": "Rahmat! Ma'lumotlar qabul qilindi 🙌 Tasdiqlash uchun biz bilan bog‘laning:\n",
        "en": "Thank you! Got your details 🙌 To confirm, please contact us:\n"},
    "bk_cancelled": {
        "ru": "Бронирование отменено 🙂", "uz": "Bron bekor qilindi 🙂", "en": "Booking cancelled 🙂"},
    "bk_interrupted": {
        "ru": "Бронирование прервал. Нажмите «📝 Забронировать», чтобы начать заново 🙂",
        "uz": "Bron to‘xtatildi. Qaytadan boshlash uchun «📝 Bron qilish»ni bosing 🙂",
        "en": "Booking stopped. Tap “📝 Book now” to start again 🙂"},
    "bk_text_please": {
        "ru": "Напишите, пожалуйста, текстом 🙂", "uz": "Iltimos, matn bilan yozing 🙂",
        "en": "Please type it as text 🙂"},
    "bk_phone_please": {
        "ru": "Напишите номер текстом или нажмите кнопку 👇",
        "uz": "Raqamni yozing yoki tugmani bosing 👇",
        "en": "Type the number or tap the button 👇"},
    "bk_press": {
        "ru": "Нажмите «✅ Отправить заявку» или «❌ Отмена».",
        "uz": "«✅ Yuborish» yoki «❌ Bekor qilish»ni bosing.",
        "en": "Tap “✅ Send request” or “❌ Cancel”."},
    "bk_stale": {
        "ru": "Форма устарела. Нажмите «📝 Забронировать» ещё раз 🙂",
        "uz": "Forma eskirgan. «📝 Bron qilish»ni qayta bosing 🙂",
        "en": "This form expired. Tap “📝 Book now” again 🙂"},
    # Поля карточки-подтверждения (что видит гость)
    "f_chalet": {"ru": "🏡 Шале", "uz": "🏡 Shale", "en": "🏡 Chalet"},
    "f_slot":   {"ru": "⏰ Слот", "uz": "⏰ Slot", "en": "⏰ Slot"},
    "f_date":   {"ru": "📅 Дата", "uz": "📅 Sana", "en": "📅 Date"},
    "f_guests": {"ru": "👥 Гостей", "uz": "👥 Mehmonlar", "en": "👥 Guests"},
    "f_name":   {"ru": "🙍 Имя", "uz": "🙍 Ism", "en": "🙍 Name"},
    "f_phone":  {"ru": "📞 Телефон", "uz": "📞 Telefon", "en": "📞 Phone"},
    "f_comment": {"ru": "💬 Пожелания", "uz": "💬 Istaklar", "en": "💬 Wishes"},
    # --- Календарь дат ---
    "bk_date_pick": {
        "ru": "На какую дату планируете? Выберите ниже 👇\nИли напишите дату вручную.",
        "uz": "Qaysi sanaga rejalashtiryapsiz? Quyidan tanlang 👇\nYoki sanani qo‘lda yozing.",
        "en": "Which date are you planning? Pick below 👇\nOr type a date manually."},
    "bk_more_dates": {"ru": "➡️ Ещё даты", "uz": "➡️ Yana sanalar", "en": "➡️ More dates"},
    # --- Напоминание и отзыв ---
    "reminder": {
        "ru": ("Напоминаем: завтра ваш заезд в Zarra Resort & SPA 🌿\n"
               "{chalet}, {slot}.\nЖдём вас! Вопросы по дороге: +998 87 591 33 30"),
        "uz": ("Eslatma: ertaga Zarra Resort & SPA ga tashrifingiz 🌿\n"
               "{chalet}, {slot}.\nKutamiz! Yo‘l savollari: +998 87 591 33 30"),
        "en": ("Reminder: your check-in at Zarra Resort & SPA is tomorrow 🌿\n"
               "{chalet}, {slot}.\nSee you! Directions: +998 87 591 33 30")},
    "review_ask": {
        "ru": "Спасибо, что были у нас в Zarra Resort & SPA! 🌿\nКак всё прошло? Оцените, пожалуйста:",
        "uz": "Zarra Resort & SPA da bo‘lganingiz uchun rahmat! 🌿\nQanday o‘tdi? Iltimos, baholang:",
        "en": "Thank you for staying at Zarra Resort & SPA! 🌿\nHow was it? Please rate:"},
    "review_thanks_hi": {
        "ru": "Спасибо за высокую оценку! ⭐️ Будем рады, если оставите отзыв в Instagram @zarraresort 🙏",
        "uz": "Yuqori baho uchun rahmat! ⭐️ Instagram @zarraresort da fikr qoldirsangiz xursand bo‘lamiz 🙏",
        "en": "Thank you for the high rating! ⭐️ We'd love a review on Instagram @zarraresort 🙏"},
    "review_thanks_lo": {
        "ru": "Спасибо за отзыв. Жаль, что не всё идеально — мы передадим руководству, чтобы стало лучше 🙏",
        "uz": "Fikr uchun rahmat. Hammasi mukammal bo‘lmaganidan afsusdamiz — yaxshilanishi uchun rahbariyatga yetkazamiz 🙏",
        "en": "Thank you for the feedback. Sorry it wasn't perfect — we'll pass it to management to improve 🙏"},
    "review_done": {
        "ru": "Спасибо за оценку! 🙏", "uz": "Baho uchun rahmat! 🙏", "en": "Thanks for rating! 🙏"},
    "webapp_btn": {
        "ru": "🚀 Забронировать", "uz": "🚀 Bron qilish",
        "en": "🚀 Book now"},
    "webapp_done": {
        "ru": ("Готово! Заявку из приложения передал сотруднику ✅\n"
               "Он скоро свяжется для подтверждения. Спасибо! 🌿"),
        "uz": ("Tayyor! Ilovadagi arizangiz xodimga yuborildi ✅\n"
               "Tez orada tasdiqlash uchun bog‘lanadi. Rahmat! 🌿"),
        "en": ("Done! Your request from the app was sent to our staff ✅\n"
               "They'll contact you shortly to confirm. Thank you! 🌿")},
    "plan_intro": {
        "ru": ("🎉 С удовольствием помогу спланировать!\n"
               "Опишите одним сообщением: повод, сколько будет гостей, желаемую дату "
               "и пожелания — и я подберу шале, время и примерную стоимость."),
        "uz": ("🎉 Rejalashtirishga yordam beraman!\n"
               "Bitta xabarda yozing: sabab, nechta mehmon, qaysi sana va istaklar — "
               "men shale, vaqt va taxminiy narxni tanlab beraman."),
        "en": ("🎉 Happy to help you plan!\n"
               "In one message tell me: the occasion, how many guests, preferred date "
               "and wishes — I'll suggest a chalet, time and an approximate price.")},
}

# Кнопки мастера (для сравнения и клавиатур) на 3 языках.
WIZ = {
    "cancel":    {"ru": "❌ Отмена", "uz": "❌ Bekor qilish", "en": "❌ Cancel"},
    "skip":      {"ru": "Пропустить", "uz": "O‘tkazib yuborish", "en": "Skip"},
    "send":      {"ru": "✅ Отправить заявку", "uz": "✅ Yuborish", "en": "✅ Send request"},
    "phone_btn": {"ru": "📱 Отправить мой номер", "uz": "📱 Raqamni yuborish", "en": "📱 Share my number"},
}
CANCEL_LABELS = set(WIZ["cancel"].values())
SKIP_LABELS = set(WIZ["skip"].values())
SEND_LABELS = set(WIZ["send"].values())

# Слоты: значение для карточки сотрудникам храним на русском, гостю показываем локально.
SLOT_LABELS_L = {
    "1": {"ru": "День 10:00–17:00", "uz": "Kunduzi 10:00–17:00", "en": "Day 10:00–17:00"},
    "2": {"ru": "Ночь 18:00–09:00", "uz": "Tunda 18:00–09:00", "en": "Night 18:00–09:00"},
    "3": {"ru": "Полный день 10:00–09:00", "uz": "To‘liq kun 10:00–09:00", "en": "Full day 10:00–09:00"},
}

# Короткие названия дней/месяцев для кнопок-дат.
WD_ABBR = {
    "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    "uz": ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
MON_ABBR = {
    "ru": ["", "янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"],
    "uz": ["", "yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek"],
    "en": ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}


def fmt_date_human(iso: str, lang: str) -> str:
    """'2026-07-05' -> 'Сб, 5 июл' на нужном языке."""
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
    except Exception:
        return iso
    return f"{WD_ABBR[lang][d.weekday()]}, {d.day} {MON_ABBR[lang][d.month]}"


# --- Занятость шале с учётом КОЛИЧЕСТВА вилл -----------------------------------
# Всего вилл каждого типа (одновременно столько броней можно взять на дату+слот).
CHALET_CAP = {"comfort": 9, "lux": 3}
# Слот занимает время: 1 — день, 2 — ночь, 3 (полный день) — и день, и ночь.


def _usage(chalet: str, iso: str) -> tuple:
    """Сколько вилл занято в этот день: (днём, ночью)."""
    day = night = 0
    for b in store.get("booked", []):
        if b.get("chalet") == chalet and b.get("date") == iso:
            s = str(b.get("slot"))
            if s in ("1", "3"):
                day += 1
            if s in ("2", "3"):
                night += 1
    return day, night


def free_counts(chalet: str, iso: str) -> tuple:
    """Сколько вилл ещё свободно: (днём, ночью)."""
    cap = CHALET_CAP.get(chalet, 1)
    day, night = _usage(chalet, iso)
    return max(0, cap - day), max(0, cap - night)


def is_date_busy(chalet: str, iso: str, slot: str) -> bool:
    """Нет ли свободной виллы под этот слот (все заняты)."""
    cap = CHALET_CAP.get(chalet, 1)
    day, night = _usage(chalet, iso)
    s = str(slot)
    if s == "1":
        return day >= cap
    if s == "2":
        return night >= cap
    if s == "3":
        return day >= cap or night >= cap
    return False


def add_booked(chalet: str, iso: str, slot: str, lead_no=None) -> bool:
    """Занимает ОДНУ виллу (на дату+слот можно несколько — по числу вилл)."""
    if not chalet or not iso or not slot:
        return False
    if lead_no is not None:   # не дублируем одну и ту же заявку
        for b in store.get("booked", []):
            if b.get("lead_no") == lead_no and b.get("chalet") == chalet \
                    and b.get("date") == iso and str(b.get("slot")) == str(slot):
                return False
    store.setdefault("booked", []).append(
        {"chalet": chalet, "date": iso, "slot": str(slot), "lead_no": lead_no})
    save_store()
    return True


def remove_booked(chalet: str, iso: str, slot: str) -> bool:
    """Освобождает ОДНУ виллу на дату+слот."""
    lst = store.get("booked", [])
    for i, b in enumerate(lst):
        if b.get("chalet") == chalet and b.get("date") == iso \
                and str(b.get("slot")) == str(slot):
            lst.pop(i)
            save_store()
            return True
    return False


def remove_booked_by_lead(lead_no) -> None:
    """Снимает занятость, добавленную конкретной заявкой (при отклонении)."""
    if lead_no is None:
        return
    before = len(store.get("booked", []))
    store["booked"] = [b for b in store.get("booked", []) if b.get("lead_no") != lead_no]
    if len(store["booked"]) != before:
        save_store()


def L(lang: str, key: str, **kw) -> str:
    tr = T.get(key, {})
    s = tr.get(lang) or tr.get(DEFAULT_LANG) or ""
    return s.format(**kw) if kw else s


def norm_lang(lang) -> str:
    return lang if lang in LANGS else DEFAULT_LANG


def lang_from_code(code) -> str:
    code = (code or "").lower()
    if code.startswith("uz"):
        return "uz"
    if code.startswith("en"):
        return "en"
    return DEFAULT_LANG


def get_lang(chat_id) -> str:
    return store.get("langs", {}).get(str(chat_id), DEFAULT_LANG)


def set_lang(chat_id, lang) -> None:
    store.setdefault("langs", {})[str(chat_id)] = norm_lang(lang)
    save_store()


def main_menu(lang=DEFAULT_LANG) -> ReplyKeyboardMarkup:
    lang = norm_lang(lang)
    b = lambda k: KeyboardButton(text=BTN[k][lang])
    # Одна кнопка брони: приложение (если задана ссылка) ИЛИ пошаговый мастер.
    url = store.get("webapp_url")
    if url:
        book_row = [KeyboardButton(text=L(lang, "webapp_btn"), web_app=WebAppInfo(url=url))]
    else:
        book_row = [b("book")]
    rows = [book_row,
            [b("prices"), b("photo")],
            [b("slots"), b("map")],
            [b("rest"), b("event")],
            [b("contact")]]
    return ReplyKeyboardMarkup(
        keyboard=rows, resize_keyboard=True, is_persistent=True,
        input_field_placeholder=PLACEHOLDER[lang],
    )


LANG_PICK_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
    InlineKeyboardButton(text="🇺🇿 O‘zbek", callback_data="lang:uz"),
    InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
]])

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
    if lead.get("conflict"):
        lines.append("⚠️ ВНИМАНИЕ: на эту дату уже есть бронь — возможно пересечение, проверьте!")
        lines.append("")
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


# --- Живой чат гость ↔ менеджер (реле через группу заявок) ---------------------
def relay_end_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔚 Завершить диалог (вернуть боту)",
                             callback_data="relay:end")]])


def map_relay(group_msg_id: int, chat_key: str) -> None:
    """Привязывает сообщение в группе к чату гостя, чтобы reply уходил гостю."""
    store.setdefault("relay_map", {})[str(group_msg_id)] = chat_key


def ensure_chat(chat_key: str, chat_id: int, is_business: bool, bcid) -> None:
    """Гарантирует запись чата (для доставки ответов менеджера), без счётчика обращений."""
    c = store.setdefault("chats", {}).setdefault(chat_key, {})
    c.update({"chat_id": chat_id, "is_business": is_business, "bcid": bcid})
    c.setdefault("has_lead", False)
    c.setdefault("followed_up", False)


def is_relay_active(chat_key: str) -> bool:
    return bool(store.get("chats", {}).get(chat_key, {}).get("relay"))


async def relay_to_group(chat_key: str, message: Message, text: str) -> None:
    """Пока диалог ведёт менеджер — пересылаем сообщения гостя в группу."""
    dest = store.get("leads_chat_id") or store.get("owner_id")
    if not dest:
        return
    try:
        sent = await bot.send_message(dest, f"💬 {guest_source(message)}:\n{text}",
                                      reply_markup=relay_end_kb())
    except Exception as e:
        log.warning(f"relay_to_group: {e}")
        return
    map_relay(sent.message_id, chat_key)
    save_store()


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
    c = store.setdefault("chats", {}).get(chat_key)
    guest_chat_id = c.get("chat_id") if c else None
    channel = store.get("src", {}).get(str(guest_chat_id)) if guest_chat_id else None
    store["leads"].append({
        "no": no, "ts": now.strftime("%Y-%m-%d %H:%M"),
        "day": now.strftime("%Y-%m-%d"), "status": "new", "by": "",
        "chat_id": sent.chat.id, "message_id": sent.message_id,
        "source": source, "data": lead,
        "chat_key": chat_key, "channel": channel or "",
    })
    if c:
        c["has_lead"] = True
    map_relay(sent.message_id, chat_key)   # менеджер может ответить reply на карточку
    save_store()


async def alert_human(chat_key: str, source: str, last_text: str):
    dest = store.get("leads_chat_id") or store.get("owner_id")
    if not dest:
        return
    txt = (f"🙋 ГОСТЮ НУЖЕН ЖИВОЙ СОТРУДНИК\n\n💬 Гость: {source}\n"
           f"Последнее сообщение: «{last_text[:300]}»\n\n"
           "Ответьте reply на это сообщение — бот перешлёт ваш текст гостю.")
    try:
        sent = await bot.send_message(dest, txt, reply_markup=relay_end_kb())
    except Exception as e:
        log.warning(f"alert_human error: {e}")
        return
    map_relay(sent.message_id, chat_key)
    save_store()


GROUP_MEMORY = 30   # сколько последних реплик чата помнит бот для контекста


def record_group_msg(chat_id: int, user_name: str, text: str) -> None:
    """Тихо запоминает реплику чата (для контекста), НЕ отвечая на неё."""
    turns = group_history.setdefault(chat_id, [])
    turns.append({"role": "user", "content": f"{user_name}: {text}"})
    turns[:] = turns[-GROUP_MEMORY:]


async def respond_group(chat_id: int):
    """Отвечает «хозяином» резорта, опираясь на ВСЮ запомненную беседу."""
    turns = group_history.get(chat_id, [])
    messages = [{"role": "system", "content": GROUP_SYSTEM}] + turns

    def _call():
        return ai.chat.completions.create(
            model=MODEL, messages=messages, temperature=0.7, max_tokens=400)

    try:
        resp = await asyncio.to_thread(_call)
        raw = (resp.choices[0].message.content or "").strip()
        clean, *_ = extract_controls(raw)   # на всякий случай убираем служебные теги
        clean = clean.strip()
        if not clean:
            return None
        group_history.setdefault(chat_id, []).append({"role": "assistant", "content": clean})
        return clean
    except Exception as e:
        log.warning(f"group AI error: {e}")
        return None


async def ask_ai(chat_key: str, user_text: str, lang: str = "ru"):
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
    weekend = ("Сегодня выходной/праздник — цены +20%."
               if is_surcharge_day(now_dt) else "Сегодня будний день.")
    when = f"Сейчас в резорте: {weekday}, {date_str}, {now}. {weekend}"
    if is_working_hours():
        time_note = f"{when} Рабочее время."
    else:
        time_note = (f"{when} НЕРАБОЧЕЕ время (работаем 09:00–23:00). "
                     "Если гость хочет бронь или живого сотрудника — мягко предупреди, "
                     "что подтверждение/ответ сотрудника может быть утром.")

    holidays_note = (
        "ПРАЗДНИЧНЫЕ ДНИ (если ДАТА брони попадает на одну из них — цена +20%, "
        "как в выходные): " + ", ".join(sorted(HOLIDAYS)) + ". "
        "В остальные будни (пн–пт) наценки нет."
    )
    # Актуальные цены (с учётом /setprice) — приоритет над базой знаний.
    prices_note = (
        "АКТУАЛЬНЫЕ ЦЕНЫ (будни / выходные +20%; приоритет над базой знаний):\n"
        f"Комфорт: день {get_price('comfort','1',False)}/{get_price('comfort','1',True)}, "
        f"ночь {get_price('comfort','2',False)}/{get_price('comfort','2',True)}, "
        f"полный день {get_price('comfort','3',False)}/{get_price('comfort','3',True)}. "
        f"Люкс: день {get_price('lux','1',False)}/{get_price('lux','1',True)}, "
        f"ночь {get_price('lux','2',False)}/{get_price('lux','2',True)}, "
        f"полный день {get_price('lux','3',False)}/{get_price('lux','3',True)}.")
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": time_note},
                {"role": "system", "content": holidays_note},
                {"role": "system", "content": prices_note}]
    if store.get("announce"):
        messages.append({"role": "system", "content":
                         "ОБЪЯВЛЕНИЕ/АКЦИЯ (упомяни, если уместно): " + store["announce"]})
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
        return L(lang, "ai_error"), None, None, False


async def transcribe_voice(file_id: str) -> str | None:
    """Скачивает голосовое и распознаёт текст через Groq Whisper (любой язык)."""
    try:
        f = await bot.get_file(file_id)
        dest = Path(tempfile.gettempdir()) / f"voice_{f.file_unique_id}.ogg"
        await bot.download_file(f.file_path, destination=dest)

        def _tr():
            with open(dest, "rb") as audio:
                return ai.audio.transcriptions.create(
                    file=(dest.name, audio.read()),
                    model="whisper-large-v3",
                )
        result = await asyncio.to_thread(_tr)
        try:
            dest.unlink()
        except Exception:
            pass
        text = (getattr(result, "text", "") or "").strip()
        return text or None
    except Exception as e:
        log.warning(f"transcribe error: {e}")
        return None


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
    if is_rate_limited(message.chat.id):
        return
    bcid = message.business_connection_id
    if message.voice or message.audio:
        await bot.send_chat_action(message.chat.id, "typing",
                                   business_connection_id=bcid)
        text = await transcribe_voice((message.voice or message.audio).file_id)
        if not text:
            await message.answer("Извините, голосовое не разобрал 🙈 "
                                 "Напишите, пожалуйста, текстом.")
            return
    elif message.text:
        text = message.text
    else:
        return

    chat_key = f"{bcid}:{message.chat.id}"
    # Если диалог ведёт живой менеджер — пересылаем сообщение гостя в группу, бот молчит.
    if is_relay_active(chat_key):
        await relay_to_group(chat_key, message, text)
        return

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

    track_inquiry(chat_key, message.chat.id, True, bcid,
                  message.from_user.id if message.from_user else None)
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
        await alert_human(chat_key, guest_source(message), text)


# =============================================================================
#  КОМАНДЫ
# =============================================================================
async def _start_from_web(message: Message, state: FSMContext,
                          payload: str, lang: str) -> bool:
    """Deep-link брони с сайта: w-<chalet>-<slot>-<ГГГГММДД>.
    Заполняет мастер выбранными на сайте полями и перескакивает вперёд."""
    parts = payload.split("-")
    if len(parts) < 4:
        return False
    villa, slot_word, datestr = parts[1], parts[2], parts[3]
    chalet = villa if villa in ("comfort", "lux") else None
    slot_no = {"day": "1", "night": "2", "full": "3"}.get(slot_word)
    if not chalet or not slot_no:
        return False

    await state.clear()
    data = {"lang": lang, "chalet": chalet,
            "slot": SLOT_LABELS_L[slot_no]["ru"],
            "slot_disp": SLOT_LABELS_L[slot_no][lang],
            "slot_no": slot_no}
    iso = ""
    if datestr.isdigit() and len(datestr) == 8:
        try:
            d = datetime.strptime(datestr, "%Y%m%d")
            iso = d.strftime("%Y-%m-%d")
            data.update(date=fmt_date_human(iso, "ru"),
                        date_disp=fmt_date_human(iso, lang),
                        date_iso=iso)
        except ValueError:
            iso = ""
    await state.update_data(**data)

    intro = {"ru": "👋 Заявка с сайта. Давайте оформим бронь:",
             "uz": "👋 Saytdan ariza. Keling, bronni rasmiylashtiramiz:",
             "en": "👋 Request from the website. Let's complete your booking:"}[lang]
    picked = f"🏡 {CHALET_SHORT[chalet][lang]} · {SLOT_LABELS_L[slot_no][lang]}"
    if iso:
        picked += f" · {fmt_date_human(iso, lang)}"
    await message.answer(f"{intro}\n{picked}")

    if iso:
        await state.set_state(Booking.guests)
        await message.answer(L(lang, "bk_guests"))
    else:
        await state.set_state(Booking.date)
        await message.answer(L(lang, "bk_date_pick"), reply_markup=date_pick_kb(lang))
    return True


@dp.message(CommandStart())
async def on_start(message: Message, command: CommandObject, state: FSMContext):
    if message.chat.type != "private":
        return
    if capture_admin(message):
        await apply_commands()
    cid = message.chat.id
    raw = (command.args or "").strip()[:64]
    low = raw.lower()

    # Язык определяем ДО брони, чтобы тексты были на нужном языке.
    if str(cid) not in store.get("langs", {}):
        code = message.from_user.language_code if message.from_user else None
        set_lang(cid, lang_from_code(code))
    lang = get_lang(cid)

    # Источник из deep-link (запоминаем первый раз). Бронь с сайта = "website".
    src_label = "website" if low.startswith("w-") else low[:32]
    if src_label and str(cid) not in store.get("src", {}):
        store.setdefault("src", {})[str(cid)] = src_label
        s = store.setdefault("src_starts", {})
        s[src_label] = s.get(src_label, 0) + 1
        save_store()

    # Deep-link бронирования с сайта — открываем мастер сразу заполненным.
    if low.startswith("w-") and await _start_from_web(message, state, low, lang):
        return

    await message.answer(L(lang, "greeting"), reply_markup=main_menu(lang))
    await message.answer(L(lang, "choose_lang"), reply_markup=LANG_PICK_KB)


@dp.message(Command("lang"))
async def cmd_lang(message: Message):
    if message.chat.type != "private":
        return
    await message.answer(L(get_lang(message.chat.id), "choose_lang"),
                         reply_markup=LANG_PICK_KB)


@dp.message(Command("plan"))
async def cmd_plan(message: Message):
    if message.chat.type != "private":
        return
    await message.answer(L(get_lang(message.chat.id), "plan_intro"))


@dp.callback_query(F.data.startswith("lang:"))
async def on_lang_pick(cb: CallbackQuery):
    lang = norm_lang(cb.data.split(":")[1])
    set_lang(cb.message.chat.id, lang)
    await cb.answer()
    await cb.message.answer(L(lang, "lang_set"), reply_markup=main_menu(lang))


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


@dp.message(Command("set_webapp"))
async def cmd_set_webapp(message: Message):
    if message.chat.type != "private" or not _is_owner(message):
        return
    url = (message.text or "").partition(" ")[2].strip()
    if not url:
        cur = store.get("webapp_url") or "не задана"
        await message.answer(
            f"Текущая ссылка мини-приложения: {cur}\n\n"
            "Задать: /set_webapp https://ваш-адрес.netlify.app\n"
            "Убрать кнопку: /set_webapp off")
        return
    if url.lower() == "off":
        store["webapp_url"] = None
        save_store()
        await message.answer("Кнопка приложения убрана. Нажмите /start, чтобы обновить меню.")
        return
    if not url.startswith("https://"):
        await message.answer("Ссылка должна начинаться с https:// (Telegram требует HTTPS).")
        return
    store["webapp_url"] = url
    save_store()
    await message.answer(
        "✅ Ссылка сохранена! В меню появилась кнопка «🚀 Забронировать в приложении».",
        reply_markup=main_menu(get_lang(message.chat.id)))


# --- Редактирование цен без кода -----------------------------------------------
_CHALET_A = {"lux": "lux", "люкс": "lux", "comfort": "comfort", "комфорт": "comfort"}
_DAYTYPE_A = {"wd": "wd", "будни": "wd", "we": "we", "выходные": "we", "вых": "we"}


@dp.message(Command("prices"))
async def cmd_prices(message: Message):
    if message.chat.type != "private" or not _is_owner(message):
        return
    lines = ["💰 Текущие цены (будни / выходные):", ""]
    for ch, nm in (("comfort", "Комфорт"), ("lux", "Люкс")):
        lines.append(f"🏡 {nm}:")
        for s, sn in (("1", "День"), ("2", "Ночь"), ("3", "Полный день")):
            lines.append(f"  {sn}: {get_price(ch, s, False)} / {get_price(ch, s, True)}")
    lines += ["",
              "Изменить: /setprice <шале> <слот 1-3> <будни|вых> <цена>",
              "Пример: /setprice comfort 1 будни 1,6 млн",
              "⚠️ Цены в мини-приложении меняются отдельно — скажи мне, обновлю."]
    await message.answer("\n".join(lines))


@dp.message(Command("setprice"))
async def cmd_setprice(message: Message):
    if message.chat.type != "private" or not _is_owner(message):
        return
    parts = (message.text or "").split(maxsplit=4)
    if len(parts) < 5:
        await message.answer("Формат: /setprice <шале> <слот 1-3> <будни|вых> <цена>\n"
                             "Пример: /setprice lux 3 вых 7,5 млн")
        return
    chalet = _CHALET_A.get(parts[1].lower())
    slot = parts[2]
    key = _DAYTYPE_A.get(parts[3].lower())
    value = parts[4].strip()
    if not chalet or slot not in ("1", "2", "3") or not key or not value:
        await message.answer("Не понял. Шале: comfort/lux; слот: 1/2/3; тип: будни/вых.\n"
                             "Пример: /setprice comfort 2 будни 2,2 млн")
        return
    store.setdefault("prices", {}).setdefault(chalet, {}).setdefault(key, {})[slot] = value
    save_store()
    nm = "Комфорт" if chalet == "comfort" else "Люкс"
    sn = {"1": "День", "2": "Ночь", "3": "Полный день"}[slot]
    kn = "будни" if key == "wd" else "выходные"
    await message.answer(f"✅ {nm}, {sn}, {kn} → {value}\n\n"
                         "Проверить всё: /prices")


@dp.message(Command("announce"))
async def cmd_announce(message: Message):
    if message.chat.type != "private" or not _is_owner(message):
        return
    text = (message.text or "").partition(" ")[2].strip()
    if not text:
        cur = store.get("announce") or "нет"
        await message.answer(f"Текущее объявление: {cur}\n\n"
                             "Задать: /announce Акция: в июле −10% в будни\n"
                             "Убрать: /announce off")
        return
    if text.lower() == "off":
        store["announce"] = None
        save_store()
        await message.answer("Объявление убрано.")
        return
    store["announce"] = text
    save_store()
    await message.answer("✅ Объявление сохранено. Бот будет упоминать его и покажет "
                         "в «🏡 Шале и цены»:\n\n📣 " + text)


# --- Рассылка по гостям --------------------------------------------------------
def guest_chat_ids() -> set:
    ids = set()
    for c in store.get("chats", {}).values():
        if not c.get("is_business") and c.get("chat_id"):
            ids.add(c["chat_id"])
    for cid in store.get("langs", {}).keys():
        try:
            ids.add(int(cid))
        except Exception:
            pass
    return {i for i in ids if isinstance(i, int) and i > 0}   # только личные чаты


@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.chat.type != "private" or not _is_owner(message):
        return
    text = (message.text or "").partition(" ")[2].strip()
    if not text:
        await message.answer("Формат: /broadcast <текст сообщения>\n"
                             "Отправится всем гостям, кто писал боту.")
        return
    n = len(guest_chat_ids())
    if not n:
        await message.answer("Пока некому рассылать — нет гостей в базе.")
        return
    pending_broadcast[message.from_user.id] = text
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"📤 Отправить {n} гостям", callback_data="bcast:go"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="bcast:no")]])
    await message.answer("Предпросмотр рассылки:\n\n" + text, reply_markup=kb)


@dp.callback_query(F.data == "bcast:no")
async def on_bcast_no(cb: CallbackQuery):
    pending_broadcast.pop(cb.from_user.id, None)
    await cb.answer("Отменено")
    try:
        await cb.message.edit_text("Рассылка отменена.")
    except Exception:
        pass


@dp.callback_query(F.data == "bcast:go")
async def on_bcast_go(cb: CallbackQuery):
    text = pending_broadcast.pop(cb.from_user.id, None)
    if not text:
        await cb.answer("Нечего отправлять")
        return
    await cb.answer("Отправляю…")
    try:
        await cb.message.edit_text("📤 Рассылка запущена…")
    except Exception:
        pass
    sent = failed = 0
    for cid in guest_chat_ids():
        try:
            await bot.send_message(cid, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)   # бережём лимиты Telegram
    await cb.message.answer(f"✅ Рассылка завершена.\nДоставлено: {sent}\nНе доставлено: {failed}")


@dp.message(Command("add_admin"))
async def cmd_add_admin(message: Message):
    if message.chat.type != "private" or not _is_owner(message):
        return
    arg = (message.text or "").partition(" ")[2].strip()
    if not arg:
        await message.answer("Напишите так: /add_admin @username")
        return
    add_admin_username(arg)
    save_store()
    await message.answer(
        f"✅ Добавил администратора: @{_norm_uname(arg)}\n\n"
        "Попросите его открыть бота и нажать «Старт» (или написать любое сообщение) — "
        "после этого он начнёт получать ежедневную сводку и видеть статистику.")


@dp.message(Command("admins"))
async def cmd_admins(message: Message):
    if not _is_owner(message):
        return
    rows = store.get("admins", [])
    if not rows:
        await message.answer("Администраторов нет. Добавить: /add_admin @username")
        return
    lines = ["👥 Администраторы:"]
    for a in rows:
        status = "✅ активен" if a.get("user_id") else "⏳ ждёт первого захода в бота"
        lines.append(f"• @{a.get('username')} — {status}")
    lines.append("\nУдалить: /remove_admin @username")
    await message.answer("\n".join(lines))


@dp.message(Command("remove_admin"))
async def cmd_remove_admin(message: Message):
    if not _is_owner(message):
        return
    arg = _norm_uname((message.text or "").partition(" ")[2])
    before = len(store.get("admins", []))
    store["admins"] = [a for a in store.get("admins", [])
                       if _norm_uname(a.get("username")) != arg]
    save_store()
    await apply_commands()
    await message.answer("✅ Удалил администратора." if len(store["admins"]) < before
                         else "Такого администратора нет.")


# --- Управление занятостью дат (для своих) -------------------------------------
_CHALET_ALIASES = {"lux": "lux", "люкс": "lux", "президент": "lux",
                   "comfort": "comfort", "комфорт": "comfort"}


def _parse_busy_args(text: str):
    """'/block lux 2026-07-05 3' -> ('lux','2026-07-05','3') либо None."""
    parts = (text or "").split()[1:]
    if len(parts) < 3:
        return None
    chalet = _CHALET_ALIASES.get(parts[0].lower())
    iso, slot = parts[1], parts[2]
    if not chalet or slot not in ("1", "2", "3"):
        return None
    try:
        datetime.strptime(iso, "%Y-%m-%d")
    except Exception:
        return None
    return chalet, iso, slot


@dp.message(Command("block"))
async def cmd_block(message: Message):
    if not _is_staff(message):
        return
    p = _parse_busy_args(message.text)
    if not p:
        await message.answer("Формат: /block lux 2026-07-05 3\n"
                             "(шале: lux или comfort; слот: 1 день, 2 ночь, 3 полный)\n"
                             "Занимает ОДНУ виллу. Всего: Комфорт 9, Люкс 3.")
        return
    add_booked(*p, lead_no=None)
    fd, fn = free_counts(p[0], p[1])
    await message.answer(f"🔴 Занял 1 виллу: {CHALET_NAMES[p[0]]}, {fmt_date_human(p[1], 'ru')}, "
                         f"{SLOT_LABELS_L[p[2]]['ru']}.\nОсталось: день {fd}, ночь {fn}.")


@dp.message(Command("free"))
async def cmd_free(message: Message):
    if not _is_staff(message):
        return
    p = _parse_busy_args(message.text)
    if not p:
        await message.answer("Формат: /free lux 2026-07-05 3 (освобождает одну виллу)")
        return
    ok = remove_booked(*p)
    if ok:
        fd, fn = free_counts(p[0], p[1])
        await message.answer(f"🟢 Освободил 1 виллу. Свободно: день {fd}, ночь {fn}.")
    else:
        await message.answer("Такой занятой виллы в календаре нет.")


@dp.message(Command("busy"))
async def cmd_busy(message: Message):
    if not _is_staff(message):
        return
    arg = (message.text or "").partition(" ")[2].strip().lower()
    only = _CHALET_ALIASES.get(arg)   # /busy lux — только люкс
    chalets = [only] if only else ["comfort", "lux"]
    today = tashkent_now().date()
    # Показываем только даты, где что-то занято (чтобы не спамить пустыми днями).
    lines = ["📅 Загрузка (свободно вилл: день / ночь)\n"
             f"Всего: Комфорт {CHALET_CAP['comfort']}, Люкс {CHALET_CAP['lux']}\n"]
    any_row = False
    for i in range(60):
        d = today + timedelta(days=i)
        iso = d.strftime("%Y-%m-%d")
        parts = []
        for ch in chalets:
            day, night = _usage(ch, iso)
            if day or night:
                fd, fn = free_counts(ch, iso)
                tag = "Комфорт" if ch == "comfort" else "Люкс"
                parts.append(f"{tag} {fd}/{fn}")
        if parts:
            any_row = True
            lines.append(f"• {fmt_date_human(iso, 'ru')}: " + " · ".join(parts))
    if not any_row:
        await message.answer("Впереди всё свободно 🟢 Занятых дат нет.\n"
                             "Занять вручную: /block lux 2026-07-05 3")
        return
    lines.append("\nЗанять: /block lux 2026-07-05 3 · Освободить: /free …")
    await message.answer("\n".join(lines))


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
    await apply_commands()   # владелец задан -> показать ему команды «для своих»
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


@dp.message(Command("report"))
async def cmd_report(message: Message):
    if not _is_staff(message):
        return
    now = tashkent_now()
    leads = store.get("leads", [])
    daily = store.get("daily", {})
    today = now.strftime("%Y-%m-%d")
    days7 = {(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)}

    inq_today = daily.get(today, {}).get("inq", 0)
    leads_today = [l for l in leads if l.get("day") == today]
    inq7 = sum(daily.get(d, {}).get("inq", 0) for d in days7)
    leads7 = [l for l in leads if l.get("day") in days7]
    conf7 = sum(1 for l in leads7 if l.get("status") == "confirmed")
    conv = round(100 * len(leads7) / inq7) if inq7 else 0

    ch = Counter((l.get("data") or {}).get("chalet", "") for l in leads7
                 if (l.get("data") or {}).get("chalet"))
    top_ch = ch.most_common(1)[0][0] if ch else "—"

    # Источники заявок за 7 дней.
    src = Counter(l.get("channel") or "не указан" for l in leads7)
    src_line = "\n".join(f"   – {name}: {n}" for name, n in src.most_common(5)) or "   – нет данных"

    await message.answer(
        "📊 Отчёт\n\n"
        f"Сегодня: обращений {inq_today}, заявок {len(leads_today)}\n\n"
        "За 7 дней:\n"
        f"• Обращений: {inq7}\n"
        f"• Заявок: {len(leads7)}\n"
        f"• Подтверждено: {conf7}\n"
        f"• Конверсия (заявки/обращения): {conv}%\n"
        f"• Чаще спрашивают: {top_ch}\n"
        f"• Источники заявок:\n{src_line}"
    )


@dp.message(Command("media_status"))
async def cmd_media_status(message: Message):
    if not _is_staff(message):
        return
    lines = [f"• {CAT_NAMES[c]}: {len(store['galleries'].get(c, []))}"
             for c in ("lux", "comfort", "exterior", "menu")]
    lines.append(f"• Группа заявок: {'подключена' if store.get('leads_chat_id') else 'нет'}")
    lines.append(f"• Геолокация: {'есть' if store.get('location') else 'нет'}")
    await message.answer("📊 Статус:\n" + "\n".join(lines))


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if not _is_staff(message):
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
    if not _is_staff(message):
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
#  БРЕНДОВАЯ КАРТОЧКА-ПОДТВЕРЖДЕНИЕ (картинка гостю при подтверждении брони)
# =============================================================================
CARD = {
    "confirmed": {"ru": "БРОНЬ ПОДТВЕРЖДЕНА", "uz": "BRON TASDIQLANDI", "en": "BOOKING CONFIRMED"},
    "chalet": {"ru": "Шале", "uz": "Shale", "en": "Chalet"},
    "date": {"ru": "Дата", "uz": "Sana", "en": "Date"},
    "slot": {"ru": "Тариф", "uz": "Tarif", "en": "Rate"},
    "guests": {"ru": "Гостей", "uz": "Mehmonlar", "en": "Guests"},
    "name": {"ru": "Гость", "uz": "Mehmon", "en": "Guest"},
    "footer": {"ru": "Ждём вас в Zarra Resort & SPA",
               "uz": "Zarra Resort & SPA da kutamiz",
               "en": "See you at Zarra Resort & SPA"},
    "caption": {"ru": "🎉 Ваша бронь подтверждена! Ждём вас 🌿",
                "uz": "🎉 Broningiz tasdiqlandi! Kutamiz 🌿",
                "en": "🎉 Your booking is confirmed! See you 🌿"},
}


def make_confirmation_card(data: dict, lang: str):
    """Рисует брендовую карточку подтверждения. Возвращает PNG-байты или None."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except Exception as e:
        log.warning(f"PIL недоступен: {e}")
        return None
    try:
        W, H = 1080, 1350
        GOLD, CREAM, MUTED = (216, 184, 120), (241, 234, 217), (155, 146, 128)

        fdir = Path(__file__).parent / "fonts"

        def font(sz, bold=False, serif=True):
            if serif:
                chain = (["DejaVuSerif-Bold.ttf", "DejaVuSerif.ttf"] if bold
                         else ["DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"])
            else:
                chain = ["DejaVuSans-Bold.ttf", "DejaVuSerif-Bold.ttf"]
            for nm in chain:
                try:
                    return ImageFont.truetype(str(fdir / nm), sz)
                except Exception:
                    continue
            return ImageFont.load_default()

        base = Image.new("RGB", (W, H), (10, 11, 8))
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([W * 0.15, -280, W * 0.85, 300], fill=(216, 184, 120, 60))
        gd.ellipse([-220, H - 340, 380, H + 200], fill=(216, 184, 120, 35))
        glow = glow.filter(ImageFilter.GaussianBlur(140))
        base = Image.alpha_composite(base.convert("RGBA"), glow).convert("RGB")
        d = ImageDraw.Draw(base)
        d.rounded_rectangle([34, 34, W - 34, H - 34], radius=42, outline=GOLD, width=2)

        def centered(y, s, f, fill, ls=0):
            w = sum(d.textlength(ch, font=f) + ls for ch in s) - (ls if s else 0)
            x = (W - w) / 2
            for ch in s:
                d.text((x, y), ch, font=f, fill=fill)
                x += d.textlength(ch, font=f) + ls

        centered(150, "ZARRA", font(112, bold=True), CREAM, ls=16)
        centered(285, "HOTEL & RESORT", font(30, serif=False), GOLD, ls=8)
        d.line([220, 360, W - 220, 360], fill=GOLD, width=1)
        centered(430, "✓ " + CARD["confirmed"][lang], font(50, bold=True, serif=False), GOLD, ls=3)

        rows = []
        if data.get("chalet"):
            rows.append((CARD["chalet"][lang], str(data["chalet"])))
        if data.get("date"):
            rows.append((CARD["date"][lang], str(data["date"])))
        if data.get("slot"):
            rows.append((CARD["slot"][lang], str(data["slot"])))
        if data.get("guests_total"):
            rows.append((CARD["guests"][lang], str(data["guests_total"])))
        if data.get("name"):
            rows.append((CARD["name"][lang], str(data["name"])))
        fl = font(36, serif=False)
        y = 600
        for label, value in rows:
            d.text((150, y + 8), label, font=fl, fill=MUTED)
            lw = d.textlength(label, font=fl)
            avail = (W - 150) - (150 + lw + 40)   # свободное место справа от подписи
            sz = 42
            vf = font(sz, bold=True)
            while sz > 24 and d.textlength(value, font=vf) > avail:
                sz -= 2
                vf = font(sz, bold=True)
            vw = d.textlength(value, font=vf)
            d.text((W - 150 - vw, y + (44 - sz) // 2), value, font=vf, fill=CREAM)
            d.line([150, y + 70, W - 150, y + 70], fill=(60, 55, 45), width=1)
            y += 108

        centered(H - 150, CARD["footer"][lang], font(32), GOLD, ls=2)
        buf = BytesIO()
        base.save(buf, "PNG")
        return buf.getvalue()
    except Exception as e:
        log.warning(f"card render error: {e}")
        return None


async def send_photo_to_guest(chat_key: str, data: bytes, caption: str) -> None:
    c = store.get("chats", {}).get(chat_key)
    if not c or not c.get("chat_id"):
        return
    photo = BufferedInputFile(data, "confirmed.png")
    try:
        if c.get("is_business") and c.get("bcid"):
            await bot.send_photo(c["chat_id"], photo, caption=caption,
                                 business_connection_id=c["bcid"])
        else:
            await bot.send_photo(c["chat_id"], photo, caption=caption)
    except Exception as e:
        log.warning(f"send card: {e}")


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
    blocked_note = ""
    lead_rec = None
    for rec in store.get("leads", []):
        if rec.get("message_id") == cb.message.message_id and rec.get("chat_id") == cb.message.chat.id:
            lead_rec = rec
            rec["status"] = status_map.get(action, rec.get("status"))
            rec["by"] = who
            data = rec.get("data", {})
            if action == "confirm" and data.get("date_iso") and data.get("chalet_key"):
                if add_booked(data["chalet_key"], data["date_iso"],
                              data.get("slot_no", ""), rec.get("no")):
                    fd, fn = free_counts(data["chalet_key"], data["date_iso"])
                    blocked_note = (f"\n📅 {fmt_date_human(data['date_iso'], 'ru')}: "
                                    f"свободно вилл — день {fd}, ночь {fn}.")
            elif action == "reject":
                remove_booked_by_lead(rec.get("no"))
            save_store()
            break

    if action == "take":
        await cb.message.edit_text(base + f"\n🙋 В работе · {who}",
                                   reply_markup=cb.message.reply_markup)
        await cb.answer("Взято в работу")
    elif action == "confirm":
        await cb.message.edit_text(base + f"\n\n✅ ПОДТВЕРЖДЕНО · {who} · {t}{blocked_note}")
        await cb.answer("Подтверждено ✅")
        # Красивая карточка-подтверждение гостю.
        ck = lead_rec.get("chat_key") if lead_rec else None
        if ck:
            glang = _guest_lang(ck)
            img = make_confirmation_card(lead_rec.get("data", {}), glang)
            if img:
                await send_photo_to_guest(ck, img, CARD["caption"][glang])
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


@dp.callback_query(F.data == "relay:end")
async def on_relay_end(cb: CallbackQuery):
    chat_key = store.get("relay_map", {}).get(str(cb.message.message_id))
    if chat_key:
        c = store.get("chats", {}).get(chat_key)
        if c:
            c["relay"] = False
            save_store()
    await cb.answer("Диалог завершён — дальше отвечает бот")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


# =============================================================================
#  ГРУППА: 1) реле «менеджер reply -> гостю»; 2) болтовня, когда к боту обратились
# =============================================================================
async def _do_relay(message: Message, chat_key: str) -> None:
    text = message.text or message.caption
    if not text or text.startswith("/"):
        return
    c = store.get("chats", {}).get(chat_key)
    if not c or not c.get("chat_id"):
        await message.reply("⚠️ Не нашёл чат гостя (возможно, бот перезапускался).")
        return
    try:
        if c.get("is_business") and c.get("bcid"):
            await bot.send_message(c["chat_id"], text, business_connection_id=c["bcid"])
        else:
            await bot.send_message(c["chat_id"], text)
    except Exception as e:
        await message.reply(f"⚠️ Не доставлено гостю: {e}")
        return
    c["relay"] = True   # включаем режим живого диалога
    save_store()
    sent = await message.reply(
        "✅ Отправлено гостю. Его дальнейшие сообщения будут приходить сюда. "
        "Когда закончите — нажмите «Завершить диалог».", reply_markup=relay_end_kb())
    map_relay(sent.message_id, chat_key)
    save_store()


def _bot_addressed(message: Message, text: str) -> bool:
    """Обратились ли к боту: упоминание @ник или ответ на сообщение бота."""
    if BOT_USERNAME and f"@{BOT_USERNAME}".lower() in text.lower():
        return True
    r = message.reply_to_message
    if r and r.from_user and BOT_ID and r.from_user.id == BOT_ID:
        return True
    return False


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message):
    # 1) Реле: ответ на карточку заявки / сообщение гостя -> уходит гостю.
    if message.reply_to_message:
        chat_key = store.get("relay_map", {}).get(str(message.reply_to_message.message_id))
        if chat_key:
            await _do_relay(message, chat_key)
            return

    text = message.text or message.caption
    if not text or text.startswith("/"):
        return

    # 2) Тихо запоминаем КАЖДУЮ реплику чата (если приватность в BotFather
    #    отключена — сюда приходят все сообщения). Так бот «в курсе беседы».
    name = (message.from_user.first_name if message.from_user else None) or "Гость"
    clean_text = text.replace(f"@{BOT_USERNAME}", "").strip() if BOT_USERNAME else text
    record_group_msg(message.chat.id, name, clean_text)

    # 3) Отвечаем ТОЛЬКО когда к боту обратились — но с учётом всей беседы.
    if not _bot_addressed(message, text):
        return
    if _group_throttled(message.chat.id):
        return
    await bot.send_chat_action(message.chat.id, "typing")
    answer = await respond_group(message.chat.id)
    if answer:
        await message.reply(answer)


# =============================================================================
#  МАСТЕР БРОНИРОВАНИЯ (кнопка «📝 Забронировать») — пошаговый сбор заявки.
#  В конце шлёт ту же карточку в группу заявок, что и ИИ-режим (post_lead).
# =============================================================================
class Booking(StatesGroup):
    chalet = State()
    slot = State()
    date = State()
    guests = State()
    name = State()
    phone = State()
    comment = State()
    confirm = State()


# Имена для карточки СОТРУДНИКАМ (всегда на русском — админы русскоязычные).
CHALET_NAMES = {"comfort": "Шале Комфорт", "lux": "Президент Люкс"}
# Короткие локализованные имена для гостя.
CHALET_SHORT = {"comfort": {"ru": "Комфорт", "uz": "Komfort", "en": "Comfort"},
                "lux": {"ru": "Президент Люкс", "uz": "Prezident Lyuks", "en": "President Lux"}}
SLOT_PRICES = {"comfort": {"1": "1,5 млн", "2": "2 млн", "3": "3 млн"},
               "lux": {"1": "3 млн", "2": "4 млн", "3": "6 млн"}}
# Цены на выходные (Сб/Вс) — +20%.
SLOT_PRICES_WE = {"comfort": {"1": "1,8 млн", "2": "2,4 млн", "3": "3,6 млн"},
                  "lux": {"1": "3,6 млн", "2": "4,8 млн", "3": "7,2 млн"}}
_SLOT_ICON = {"1": "☀️", "2": "🌙", "3": "🌗"}


def get_price(chalet: str, slot, weekend: bool) -> str:
    """Цена с учётом ручных переопределений (/setprice), иначе — из умолчаний."""
    s = str(slot)
    key = "we" if weekend else "wd"
    ov = (store.get("prices") or {}).get(chalet, {}).get(key, {}).get(s)
    if ov:
        return ov
    return (SLOT_PRICES_WE if weekend else SLOT_PRICES)[chalet][s]


def price_disp(chalet: str, slot, weekend: bool, lang: str) -> str:
    """Цена под язык: млн -> mln (uz) / M и точка (en)."""
    p = get_price(chalet, slot, weekend)
    if lang == "uz":
        return p.replace("млн", "mln")
    if lang == "en":
        return p.replace("млн", "M").replace(",", ".")
    return p


def _price_pair(chalet: str, slot, lang: str) -> str:
    return f"{price_disp(chalet, slot, False, lang)} / {price_disp(chalet, slot, True, lang)}"


def build_prices_text(lang: str) -> str:
    """Текст «Шале и цены» с актуальными ценами и объявлением (если задано)."""
    lang = norm_lang(lang)
    txt = PRICES_TEXT[lang].format(
        c1=_price_pair("comfort", "1", lang), c2=_price_pair("comfort", "2", lang),
        c3=_price_pair("comfort", "3", lang), l1=_price_pair("lux", "1", lang),
        l2=_price_pair("lux", "2", lang), l3=_price_pair("lux", "3", lang))
    ann = store.get("announce")
    if ann:
        txt = "📣 " + ann + "\n\n" + txt
    return txt


def book_chalet_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=L(lang, "bk_chalet_comfort"), callback_data="bk:ch:comfort")],
        [InlineKeyboardButton(text=L(lang, "bk_chalet_lux"), callback_data="bk:ch:lux")],
        [InlineKeyboardButton(text=WIZ["cancel"][lang], callback_data="bk:cancel")],
    ])


def slot_kb(chalet: str, lang: str, surcharge=None) -> InlineKeyboardMarkup:
    # surcharge: True -> цена выходного, False -> будни, None -> обе (дата неизвестна).
    rows = []
    for s in ("1", "2", "3"):
        if surcharge is True:
            price = get_price(chalet, s, True)
        elif surcharge is False:
            price = get_price(chalet, s, False)
        else:
            price = f"{get_price(chalet, s, False)} / {get_price(chalet, s, True)}"
        rows.append([InlineKeyboardButton(
            text=f"{_SLOT_ICON[s]} {SLOT_LABELS_L[s][lang]} — {price}",
            callback_data=f"bk:sl:{s}")])
    rows.append([InlineKeyboardButton(text=WIZ["cancel"][lang], callback_data="bk:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def phone_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=WIZ["phone_btn"][lang], request_contact=True)],
                  [KeyboardButton(text=WIZ["cancel"][lang])]],
        resize_keyboard=True, one_time_keyboard=True)


def comment_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=WIZ["skip"][lang])],
                  [KeyboardButton(text=WIZ["cancel"][lang])]],
        resize_keyboard=True, one_time_keyboard=True)


def confirm_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=WIZ["send"][lang])],
                  [KeyboardButton(text=WIZ["cancel"][lang])]],
        resize_keyboard=True, one_time_keyboard=True)


async def _wiz_lang(state: FSMContext) -> str:
    d = await state.get_data()
    return norm_lang(d.get("lang", DEFAULT_LANG))


async def _step_text(message: Message, state: FSMContext):
    """Текст шага, либо None если надо переспросить/прервать (меню или команда)."""
    lang = await _wiz_lang(state)
    t = (message.text or "").strip()
    if not t:
        await message.answer(L(lang, "bk_text_please"))
        return None
    if t in MENU_TEXTS or t.startswith("/"):
        await state.clear()
        await message.answer(L(lang, "bk_interrupted"), reply_markup=main_menu(lang))
        return None
    return t


async def _begin_booking(message: Message, state: FSMContext):
    lang = get_lang(message.chat.id)
    await state.clear()
    await state.update_data(lang=lang)
    await state.set_state(Booking.chalet)
    await message.answer(L(lang, "bk_start"), reply_markup=book_chalet_kb(lang))


@dp.message(F.text.in_(BOOK_LABELS))
async def on_book_button(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return
    await _begin_booking(message, state)


@dp.message(Command("book"))
async def cmd_book(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return
    await _begin_booking(message, state)


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if await state.get_state() is None:
        return
    lang = await _wiz_lang(state)
    await state.clear()
    await message.answer(L(lang, "bk_cancelled"), reply_markup=main_menu(lang))


@dp.callback_query(F.data == "bk:cancel")
async def bk_cancel(cb: CallbackQuery, state: FSMContext):
    lang = await _wiz_lang(state)
    await state.clear()
    await cb.answer()
    await cb.message.answer(L(lang, "bk_cancelled"), reply_markup=main_menu(lang))


def date_pick_kb(lang: str, offset: int = 0, span: int = 14) -> InlineKeyboardMarkup:
    # ВАЖНО: занятость гостю НЕ показываем (чтобы конкуренты не видели загрузку).
    # Все даты выглядят одинаково доступными; пересечения ловит сотрудник в заявке.
    today = tashkent_now().date()
    rows, row = [], []
    for i in range(offset, offset + span):
        d = today + timedelta(days=i)
        iso = d.strftime("%Y-%m-%d")
        label = f"{WD_ABBR[lang][d.weekday()]} {d.day} {MON_ABBR[lang][d.month]}"
        row.append(InlineKeyboardButton(text=label, callback_data=f"bk:dt:{iso}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text=L(lang, "bk_more_dates"),
                                      callback_data=f"bk:dtmore:{offset + span}")])
    rows.append([InlineKeyboardButton(text=WIZ["cancel"][lang], callback_data="bk:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _surcharge_of(iso: str):
    """True если дата — выходной/праздник, False если будни, None если неизвестно."""
    try:
        return is_surcharge_day(datetime.strptime(iso, "%Y-%m-%d"))
    except Exception:
        return None


async def _ask_slot(target, state: FSMContext, lang: str):
    d = await state.get_data()
    surcharge = _surcharge_of(d.get("date_iso", ""))
    await state.set_state(Booking.slot)
    await target.answer(L(lang, "bk_slot_prompt"),
                        reply_markup=slot_kb(d.get("chalet"), lang, surcharge))


# Поток: ШАЛЕ → ДАТА → СЛОТ → гости → имя → телефон → пожелания → подтверждение.
@dp.callback_query(F.data.startswith("bk:ch:"), Booking.chalet)
async def bk_chalet(cb: CallbackQuery, state: FSMContext):
    lang = await _wiz_lang(state)
    chalet = cb.data.split(":")[2]
    await state.update_data(chalet=chalet)
    await state.set_state(Booking.date)
    await cb.answer()
    await cb.message.edit_text(L(lang, "bk_chalet_set", v=CHALET_SHORT[chalet][lang]))
    await cb.message.answer(L(lang, "bk_date_pick"), reply_markup=date_pick_kb(lang))


@dp.callback_query(F.data.startswith("bk:dtmore:"), Booking.date)
async def bk_date_more(cb: CallbackQuery, state: FSMContext):
    lang = await _wiz_lang(state)
    offset = int(cb.data.split(":")[2])
    if offset > 120:   # дальше ~4 месяцев не уходим
        offset = 0
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=date_pick_kb(lang, offset))
    except Exception:
        pass


@dp.callback_query(F.data.startswith("bk:dt:"), Booking.date)
async def bk_date_pick(cb: CallbackQuery, state: FSMContext):
    lang = await _wiz_lang(state)
    iso = cb.data.split(":", 2)[2]
    # date — в карточку сотрудникам (рус), date_disp — гостю на его языке.
    await state.update_data(date=fmt_date_human(iso, "ru"),
                            date_disp=fmt_date_human(iso, lang), date_iso=iso)
    await cb.answer()
    await cb.message.edit_text(L(lang, "f_date") + ": " + fmt_date_human(iso, lang) + " ✅")
    # слот мог быть выбран заранее (бронь с сайта) — тогда не переспрашиваем
    if (await state.get_data()).get("slot_no"):
        await state.set_state(Booking.guests)
        await cb.message.answer(L(lang, "bk_guests"))
    else:
        await _ask_slot(cb.message, state, lang)


@dp.callback_query(F.data.startswith("bk:sl:"), Booking.slot)
async def bk_slot(cb: CallbackQuery, state: FSMContext):
    lang = await _wiz_lang(state)
    s = cb.data.split(":")[2]
    # slot — в карточку сотрудникам (русский), slot_disp — гостю; slot_no — для занятости.
    await state.update_data(slot=SLOT_LABELS_L[s]["ru"], slot_disp=SLOT_LABELS_L[s][lang],
                            slot_no=s)
    await state.set_state(Booking.guests)
    await cb.answer()
    await cb.message.edit_text(L(lang, "bk_slot_set", v=SLOT_LABELS_L[s][lang]))
    await cb.message.answer(L(lang, "bk_guests"))


@dp.callback_query(F.data.startswith("bk:"))
async def bk_stale(cb: CallbackQuery, state: FSMContext):
    # Сюда попадают «протухшие» кнопки брони (например, после перезапуска бота).
    lang = await _wiz_lang(state)
    await state.clear()
    await cb.answer(L(lang, "bk_stale"), show_alert=True)


@dp.message(Booking.date)
async def bk_date(message: Message, state: FSMContext):
    t = await _step_text(message, state)
    if t is None:
        return
    lang = await _wiz_lang(state)
    # Дата введена вручную — точную дату не знаем, поэтому слот покажем с двумя ценами.
    await state.update_data(date=t, date_disp=t, date_iso="")
    if (await state.get_data()).get("slot_no"):
        await state.set_state(Booking.guests)
        await message.answer(L(lang, "bk_guests"))
    else:
        await _ask_slot(message, state, lang)


@dp.message(Booking.guests)
async def bk_guests(message: Message, state: FSMContext):
    t = await _step_text(message, state)
    if t is None:
        return
    lang = await _wiz_lang(state)
    await state.update_data(guests=t)
    await state.set_state(Booking.name)
    await message.answer(L(lang, "bk_name"))


@dp.message(Booking.name)
async def bk_name(message: Message, state: FSMContext):
    t = await _step_text(message, state)
    if t is None:
        return
    lang = await _wiz_lang(state)
    await state.update_data(name=t)
    await state.set_state(Booking.phone)
    await message.answer(L(lang, "bk_phone"), reply_markup=phone_kb(lang))


@dp.message(Booking.phone, F.contact)
async def bk_phone_contact(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await _ask_comment(message, state)


@dp.message(Booking.phone)
async def bk_phone_text(message: Message, state: FSMContext):
    lang = await _wiz_lang(state)
    t = (message.text or "").strip()
    if t in CANCEL_LABELS:
        await state.clear()
        await message.answer(L(lang, "bk_cancelled"), reply_markup=main_menu(lang))
        return
    if not t:
        await message.answer(L(lang, "bk_phone_please"), reply_markup=phone_kb(lang))
        return
    await state.update_data(phone=t)
    await _ask_comment(message, state)


async def _ask_comment(message: Message, state: FSMContext):
    lang = await _wiz_lang(state)
    await state.set_state(Booking.comment)
    await message.answer(L(lang, "bk_comment"), reply_markup=comment_kb(lang))


@dp.message(Booking.comment)
async def bk_comment(message: Message, state: FSMContext):
    lang = await _wiz_lang(state)
    t = (message.text or "").strip()
    if t in CANCEL_LABELS:
        await state.clear()
        await message.answer(L(lang, "bk_cancelled"), reply_markup=main_menu(lang))
        return
    comment = "" if (not t or t in SKIP_LABELS) else t
    await state.update_data(comment=comment)
    await _show_confirm(message, state)


async def _show_confirm(message: Message, state: FSMContext):
    d = await state.get_data()
    lang = norm_lang(d.get("lang", DEFAULT_LANG))
    await state.set_state(Booking.confirm)
    chalet = d.get("chalet")
    lines = [
        L(lang, "bk_confirm_title"), "",
        f"{L(lang, 'f_chalet')}: {CHALET_SHORT.get(chalet, {}).get(lang, chalet)}",
        f"{L(lang, 'f_slot')}: {d.get('slot_disp') or d.get('slot')}",
        f"{L(lang, 'f_date')}: {d.get('date_disp') or d.get('date')}",
        f"{L(lang, 'f_guests')}: {d.get('guests')}",
        f"{L(lang, 'f_name')}: {d.get('name')}",
        f"{L(lang, 'f_phone')}: {d.get('phone')}",
    ]
    if d.get("comment"):
        lines.append(f"{L(lang, 'f_comment')}: {d['comment']}")
    lines += ["", L(lang, "bk_confirm_ask")]
    await message.answer("\n".join(lines), reply_markup=confirm_kb(lang))


@dp.message(Booking.confirm)
async def bk_confirm(message: Message, state: FSMContext):
    lang = await _wiz_lang(state)
    t = (message.text or "").strip()
    if t in CANCEL_LABELS:
        await state.clear()
        await message.answer(L(lang, "bk_cancelled"), reply_markup=main_menu(lang))
        return
    if t not in SEND_LABELS:
        await message.answer(L(lang, "bk_press"), reply_markup=confirm_kb(lang))
        return
    d = await state.get_data()
    await state.clear()
    lead = {
        "chalet": CHALET_NAMES.get(d.get("chalet"), d.get("chalet", "")),
        "date": d.get("date", ""), "slot": d.get("slot", ""),
        "guests_total": d.get("guests", ""), "guests_overnight": "",
        "occasion": "", "name": d.get("name", ""),
        "phone": d.get("phone", ""), "notes": d.get("comment", ""),
        # служебные поля для календаря/напоминаний (в карточке не показываются):
        "chalet_key": d.get("chalet", ""), "slot_no": d.get("slot_no", ""),
        "date_iso": d.get("date_iso", ""),
    }
    # Тихо проверяем занятость — предупреждение увидит ТОЛЬКО сотрудник в карточке.
    if d.get("date_iso") and is_date_busy(d.get("chalet"), d["date_iso"], d.get("slot_no", "")):
        lead["conflict"] = True
    dest = store.get("leads_chat_id") or store.get("owner_id")
    if not dest:
        await message.answer(L(lang, "bk_done_nogroup") + CONTACTS_TEXT[lang],
                             reply_markup=main_menu(lang))
        return
    chat_key = f"direct:{message.chat.id}"
    ensure_chat(chat_key, message.chat.id, False, None)  # для реле/ответов менеджера
    u = message.from_user
    await post_lead(lead, chat_key, guest_source(message), u.username if u else None)
    await message.answer(L(lang, "bk_done"), reply_markup=main_menu(lang))


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
#  ЗАЯВКА ИЗ МИНИ-ПРИЛОЖЕНИЯ (Telegram Web App -> web_app_data)
# =============================================================================
@dp.message(F.web_app_data)
async def on_webapp_data(message: Message):
    if message.chat.type != "private":
        return
    lang = get_lang(message.chat.id)
    try:
        d = json.loads(message.web_app_data.data)
    except Exception:
        return
    chalet = d.get("chalet")
    slot_no = str(d.get("slot", ""))
    iso = d.get("date", "")
    if chalet not in CHALET_NAMES or slot_no not in ("1", "2", "3"):
        return
    lead = {
        "chalet": CHALET_NAMES.get(chalet, chalet),
        "date": fmt_date_human(iso, "ru") if iso else "",
        "slot": SLOT_LABELS_L.get(slot_no, {}).get("ru", ""),
        "guests_total": str(d.get("guests", "")), "guests_overnight": "",
        "occasion": "", "name": str(d.get("name", "")).strip(),
        "phone": str(d.get("phone", "")).strip(), "notes": str(d.get("comment", "")).strip(),
        "chalet_key": chalet, "slot_no": slot_no, "date_iso": iso,
    }
    if iso and is_date_busy(chalet, iso, slot_no):
        lead["conflict"] = True
    dest = store.get("leads_chat_id") or store.get("owner_id")
    if not dest:
        await message.answer(L(lang, "bk_done_nogroup") + CONTACTS_TEXT[lang],
                             reply_markup=main_menu(lang))
        return
    chat_key = f"direct:{message.chat.id}"
    ensure_chat(chat_key, message.chat.id, False, None)
    u = message.from_user
    await post_lead(lead, chat_key, guest_source(message), u.username if u else None)
    await message.answer(L(lang, "webapp_done"), reply_markup=main_menu(lang))


# =============================================================================
#  ПРЯМОЕ СООБЩЕНИЕ БОТУ (кнопки-меню + диалог)
# =============================================================================
@dp.message()
async def on_direct_message(message: Message):
    if message.chat.type != "private":
        return
    if capture_admin(message):
        await apply_commands()
    if is_rate_limited(message.chat.id):
        return
    lang = get_lang(message.chat.id)
    if message.voice or message.audio:
        await bot.send_chat_action(message.chat.id, "typing")
        text = await transcribe_voice((message.voice or message.audio).file_id)
        if not text:
            await message.answer(L(lang, "voice_fail"))
            return
        text = text.strip()
    elif message.text:
        text = message.text.strip()
    else:
        return

    chat_key = f"direct:{message.chat.id}"
    # Если диалог ведёт живой менеджер — пересылаем сообщение гостя в группу, бот молчит.
    if is_relay_active(chat_key):
        await relay_to_group(chat_key, message, text)
        return

    # Кнопки нижнего меню (распознаём на любом из 3 языков).
    key = BTN_LOOKUP.get(text)
    if key == "prices":
        await message.answer(build_prices_text(lang))
        return
    if key == "slots":
        await message.answer(SLOTS_TEXT[lang])
        return
    if key == "contact":
        await message.answer(CONTACTS_TEXT[lang])
        return
    if key == "map":
        await send_location_card(message.chat.id, None, lang)
        return
    if key == "photo":
        await message.answer(L(lang, "photo_ask"), reply_markup=GALLERY_PICK)
        return
    if key == "rest":
        if store["galleries"].get("menu"):
            await send_gallery(message.chat.id, None, "menu")
        else:
            await message.answer(L(lang, "rest_closed"))
        return
    if key == "event":
        await message.answer(L(lang, "plan_intro"))
        return

    # Геолокация по тексту
    if detect_location_request(text):
        await send_location_card(message.chat.id, None, lang)
        return

    # Галерея по ключевым словам
    g = detect_gallery_request(text)
    if g == "ask":
        await message.answer(L(lang, "photo_ask"), reply_markup=GALLERY_PICK)
        return
    if g in ("lux", "comfort", "exterior") and store["galleries"].get(g):
        await bot.send_chat_action(message.chat.id, "upload_photo")
        if await send_gallery(message.chat.id, None, g):
            return

    # Иначе — ИИ
    track_inquiry(chat_key, message.chat.id, False, None,
                  message.from_user.id if message.from_user else None)
    await bot.send_chat_action(message.chat.id, "typing")
    answer, lead, gal, need_human = await ask_ai(chat_key, text, lang)
    if answer:
        await message.answer(answer, reply_markup=links_keyboard())
    elif gal:
        await message.answer("👇")
    if gal and store["galleries"].get(gal):
        await bot.send_chat_action(message.chat.id, "upload_photo")
        await send_gallery(message.chat.id, None, gal)
    u = message.from_user
    if lead:
        await post_lead(lead, chat_key, guest_source(message), u.username if u else None)
    if need_human:
        await alert_human(chat_key, guest_source(message), text)


# =============================================================================
#  АНАЛИТИКА И FOLLOW-UP (фон)
# =============================================================================
FOLLOWUP_ENABLED = True            # авто-напоминание гостям без заявки (off -> False)
FOLLOWUP_MIN_HOURS = 3             # писать не раньше, чем через столько часов
FOLLOWUP_MAX_HOURS = 48            # и не позже


def track_inquiry(chat_key: str, chat_id: int, is_business: bool, bcid, uid) -> None:
    """Запоминает диалог гостя для аналитики и follow-up. Владельца не трогаем."""
    if uid and uid == store.get("owner_id"):
        return
    now = tashkent_now()
    day = now.strftime("%Y-%m-%d")
    chats = store.setdefault("chats", {})
    c = chats.get(chat_key) or {}
    first_today = c.get("last_day") != day
    c.update({
        "chat_id": chat_id, "is_business": is_business, "bcid": bcid,
        "last_ts": now.strftime("%Y-%m-%d %H:%M"), "last_day": day,
    })
    c.setdefault("has_lead", False)
    c.setdefault("followed_up", False)
    chats[chat_key] = c
    if first_today:
        d = store.setdefault("daily", {}).setdefault(day, {"inq": 0})
        d["inq"] = d.get("inq", 0) + 1
    save_store()


async def send_followup(c: dict) -> bool:
    text = L(get_lang(c.get("chat_id")), "followup")
    try:
        if c.get("is_business") and c.get("bcid"):
            await bot.send_message(c["chat_id"], text,
                                   business_connection_id=c["bcid"],
                                   reply_markup=links_keyboard())
        else:
            await bot.send_message(c["chat_id"], text, reply_markup=links_keyboard())
        return True
    except Exception as e:
        log.warning(f"followup send error: {e}")
        return False


async def run_followups() -> None:
    """Один раз пишет гостям, кто общался, но не оставил заявку (только в рабочее время)."""
    if not FOLLOWUP_ENABLED or not is_working_hours():
        return
    now = tashkent_now()
    changed = False
    for c in list(store.get("chats", {}).values()):
        if c.get("has_lead") or c.get("followed_up") or not c.get("last_ts"):
            continue
        try:
            last_dt = datetime.strptime(c["last_ts"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        hours = (now - last_dt).total_seconds() / 3600
        if not (FOLLOWUP_MIN_HOURS <= hours <= FOLLOWUP_MAX_HOURS):
            continue
        if await send_followup(c):
            c["followed_up"] = True
            changed = True
            await asyncio.sleep(1)   # бережём лимиты Telegram
    if changed:
        save_store()


async def send_daily_digest() -> None:
    """Утренняя сводка за вчера — владельцу и всем активным админам."""
    recipients = staff_ids()
    if not recipients:
        return
    y = (tashkent_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    inq = store.get("daily", {}).get(y, {}).get("inq", 0)
    ld = [l for l in store.get("leads", []) if l.get("day") == y]
    conf = sum(1 for l in ld if l.get("status") == "confirmed")
    conv = round(100 * len(ld) / inq) if inq else 0
    text = (f"☀️ Сводка за вчера ({y})\n\n"
            f"• Обращений: {inq}\n• Заявок: {len(ld)}\n"
            f"• Подтверждено: {conf}\n• Конверсия: {conv}%")
    for dest in recipients:
        try:
            await bot.send_message(dest, text)
        except Exception as e:
            log.warning(f"digest error ({dest}): {e}")


async def send_to_guest(chat_key: str, text: str, reply_markup=None) -> bool:
    c = store.get("chats", {}).get(chat_key)
    if not c or not c.get("chat_id"):
        return False
    try:
        if c.get("is_business") and c.get("bcid"):
            await bot.send_message(c["chat_id"], text, business_connection_id=c["bcid"],
                                   reply_markup=reply_markup)
        else:
            await bot.send_message(c["chat_id"], text, reply_markup=reply_markup)
        return True
    except Exception as e:
        log.warning(f"send_to_guest: {e}")
        return False


def rating_kb(no) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐" * n, callback_data=f"rate:{no}:{n}") for n in (1, 2, 3)],
        [InlineKeyboardButton(text="⭐" * n, callback_data=f"rate:{no}:{n}") for n in (4, 5)],
    ])


def _guest_lang(chat_key: str) -> str:
    return get_lang(store.get("chats", {}).get(chat_key, {}).get("chat_id"))


async def run_reminders() -> None:
    """За день до заезда напоминаем гостю (по подтверждённым броням с датой)."""
    tomorrow = (tashkent_now() + timedelta(days=1)).strftime("%Y-%m-%d")
    changed = False
    for rec in store.get("leads", []):
        if rec.get("status") != "confirmed" or rec.get("reminded"):
            continue
        data = rec.get("data", {})
        chat_key = rec.get("chat_key")
        if data.get("date_iso") != tomorrow or not chat_key:
            continue
        lang = _guest_lang(chat_key)
        chalet = CHALET_SHORT.get(data.get("chalet_key"), {}).get(lang, data.get("chalet", ""))
        slot = SLOT_LABELS_L.get(str(data.get("slot_no")), {}).get(lang, data.get("slot", ""))
        if await send_to_guest(chat_key, L(lang, "reminder", chalet=chalet, slot=slot)):
            rec["reminded"] = True
            changed = True
            await asyncio.sleep(0.5)
    if changed:
        save_store()


async def run_reviews() -> None:
    """После выезда (на следующий день) просим оценку."""
    yest = (tashkent_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    changed = False
    for rec in store.get("leads", []):
        if rec.get("status") != "confirmed" or rec.get("review_asked"):
            continue
        data = rec.get("data", {})
        chat_key = rec.get("chat_key")
        if data.get("date_iso") != yest or not chat_key:
            continue
        lang = _guest_lang(chat_key)
        if await send_to_guest(chat_key, L(lang, "review_ask"), rating_kb(rec.get("no"))):
            rec["review_asked"] = True
            changed = True
            await asyncio.sleep(0.5)
    if changed:
        save_store()


@dp.callback_query(F.data.startswith("rate:"))
async def on_rate(cb: CallbackQuery):
    try:
        _, no, n = cb.data.split(":")
        n = int(n)
    except Exception:
        await cb.answer()
        return
    lang = get_lang(cb.message.chat.id)
    for rec in store.get("leads", []):
        if str(rec.get("no")) == no:
            rec["rating"] = n
            save_store()
            break
    await cb.answer(L(lang, "review_done"))
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.message.answer(L(lang, "review_thanks_hi") if n >= 4
                            else L(lang, "review_thanks_lo"))
    dest = store.get("leads_chat_id") or store.get("owner_id")
    if dest:
        try:
            await bot.send_message(
                dest, f"{'🌟' if n >= 4 else '⚠️'} Оценка по заявке #{no}: "
                      f"{'⭐' * n} ({n}/5)")
        except Exception as e:
            log.warning(f"rate alert: {e}")


async def scheduler() -> None:
    last_morning_day = None
    while True:
        try:
            now = tashkent_now()
            await run_followups()
            day = now.strftime("%Y-%m-%d")
            if now.hour == 9 and last_morning_day != day:
                backup_store()
                await send_daily_digest()
                await run_reminders()
                await run_reviews()
                last_morning_day = day
        except Exception as e:
            log.warning(f"scheduler error: {e}")
        await asyncio.sleep(900)   # каждые 15 минут


PUBLIC_COMMANDS = [
    BotCommand(command="start", description="Главное меню / Bosh menyu / Menu"),
    BotCommand(command="book", description="Забронировать / Bron qilish / Book"),
    BotCommand(command="plan", description="Подобрать под мероприятие / Event"),
    BotCommand(command="lang", description="Язык / Til / Language"),
]
STAFF_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand(command="stats", description="Статистика заявок"),
    BotCommand(command="report", description="Отчёт и конверсия"),
    BotCommand(command="busy", description="Занятые даты"),
    BotCommand(command="prices", description="Цены (изменить)"),
    BotCommand(command="announce", description="Объявление / акция"),
    BotCommand(command="broadcast", description="Рассылка по гостям"),
    BotCommand(command="export", description="Выгрузить заявки"),
    BotCommand(command="media_status", description="Что загружено"),
    BotCommand(command="admins", description="Администраторы"),
]


async def apply_commands() -> None:
    """Публичные команды видят все; «для своих» — только владелец и админы."""
    try:
        await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
    except Exception as e:
        log.warning(f"public commands: {e}")
    for uid in staff_ids():
        try:
            await bot.set_my_commands(STAFF_COMMANDS,
                                      scope=BotCommandScopeChat(chat_id=uid))
        except Exception as e:
            log.warning(f"staff commands {uid}: {e}")


async def main():
    global BOT_ID, BOT_USERNAME
    try:
        me = await bot.get_me()
        BOT_ID, BOT_USERNAME = me.id, me.username
        log.info(f"Я @{BOT_USERNAME} (id {BOT_ID})")
    except Exception as e:
        log.warning(f"get_me: {e}")
    await apply_commands()
    asyncio.create_task(scheduler())
    log.info("Бот запущен (v8). Останови командой Ctrl+C.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот остановлен.")
