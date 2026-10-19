"""Настройки бота. Всё секретное берётся из файла .env, а не пишется в коде."""
import os
from datetime import timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PREMIUM_PRICE_STARS = int(os.getenv("PREMIUM_PRICE_STARS", "150"))
DB_PATH = os.getenv("DB_PATH", "bot.db")
# Ваш Telegram ID (узнать: отправьте боту /myid). Владельцу доступны /stats и /grant,
# ему приходят уведомления об оплатах и ошибках и ежедневная копия базы.
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

# Время показываем и принимаем по Москве (UTC+3, переходов на летнее время нет).
MSK = timezone(timedelta(hours=3))

# 30 дней в секундах: Telegram принимает подписку только на такой срок.
PREMIUM_PERIOD = 30 * 24 * 60 * 60

# Ограничения бесплатной и платной версии.
# max_channels — на сколько каналов нужно подписаться (основной + каналы-партнёры).
FREE_LIMITS = {"max_active": 1, "max_winners": 3, "max_channels": 1, "watermark": True}
PREMIUM_LIMITS = {"max_active": 20, "max_winners": 100, "max_channels": 10, "watermark": False}
