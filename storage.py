"""Хранилище данных бота.

Вся работа с «базой» (файл media_store.json) собрана здесь: чтение, атомарная
запись и схема полей по умолчанию. Вынесено из bot.py, чтобы:
  1) вся работа с данными была в одном месте (легче читать и поддерживать);
  2) при переходе на настоящую БД (SQLite и т.п.) менять пришлось только
     ЭТОТ файл, а не десятки мест в bot.py.

Формат хранения — обычный JSON-словарь. bot.py держит его в глобальной
переменной `store` и вызывает save_store(store) после изменений.
"""
import os
import json
from pathlib import Path

# Файл базы лежит рядом с кодом. На сервере он НЕ перезаписывается из репозитория
# (в .gitignore), поэтому данные гостей и заявок сохраняются между обновлениями.
STORE_PATH = Path(__file__).parent / "media_store.json"


def load_store() -> dict:
    """Читает базу из файла и проставляет значения по умолчанию для всех полей.

    Если файла нет или он повреждён — начинаем с пустого словаря (но со схемой),
    чтобы бот всегда стартовал, а не падал.
    """
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
    data.setdefault("card", None)      # карта для предоплаты (текст: номер + имя)
    data.setdefault("pay_hours", 3)    # сколько часов на предоплату
    data.setdefault("waitlist", [])    # [{chat_key,chalet,date,slot,no,ts}]
    data.setdefault("guests", {})      # CRM: {chat_id: {name,phone,bookings,confirmed,last_chalet,...}}
    data.setdefault("dash_token", None)  # (устар.) секрет доступа к веб-панели
    data.setdefault("dash_user", "zarra")  # логин к веб-панели (Basic Auth)
    data.setdefault("dash_pass", None)     # пароль к веб-панели (Basic Auth)
    data.setdefault("dash_host", None)   # публичный IP сервера (определяется сам)
    return data


def save_store(data: dict) -> None:
    """Атомарно сохраняет базу на диск.

    Пишем во временный файл и подменяем им основной — чтобы при сбое/ребуте
    в момент записи база заявок и галерей не повредилась.
    """
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STORE_PATH)
