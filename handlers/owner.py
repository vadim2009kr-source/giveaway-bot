"""Админ-панель владельца бота: статистика, бесплатный премиум, уведомления и копия базы."""
import asyncio
import logging
import os
import tempfile
import time
from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import ErrorEvent, FSInputFile, Message

import db
from config import MSK, OWNER_ID
from utils import format_time

router = Router()

BACKUP_INTERVAL = 24 * 60 * 60
ERROR_NOTIFY_INTERVAL = 60  # об ошибках пишем не чаще раза в минуту, чтобы не засыпать сообщениями
_last_error_notify = 0.0


async def notify_owner(bot: Bot, text: str):
    """Пишет владельцу. Если OWNER_ID не задан или сообщение не ушло, молча пропускаем."""
    if not OWNER_ID:
        return
    try:
        await bot.send_message(OWNER_ID, text)
    except Exception:
        logging.warning("Не удалось написать владельцу")


@router.message(Command("myid"))
async def myid(message: Message):
    await message.answer(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n\n"
        "Если вы владелец бота, впишите это число в файл .env в строку OWNER_ID= и перезапустите бота."
    )


# Команды ниже работают только у владельца, остальным бот их просто не показывает.
owner_only = F.from_user.id == OWNER_ID


@router.message(Command("stats"), owner_only)
async def stats(message: Message):
    s = await db.stats()
    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"Пользователей: {s['users']}\n"
        f"С премиумом сейчас: {s['premium']}\n"
        f"Розыгрышей всего: {s['giveaways']} (идут сейчас: {s['active']})\n"
        f"Участий в розыгрышах: {s['participants']}\n\n"
        f"Оплат за 30 дней: {s['payments_month']} на {s['stars_month']} ⭐\n"
        f"Заработано за всё время: {s['stars_total']} ⭐"
    )


@router.message(Command("grant"), owner_only)
async def grant(message: Message, command: CommandObject, bot: Bot):
    """/grant <ID пользователя> [дней] — бесплатный премиум, например за отзыв."""
    args = (command.args or "").split()
    if not args or not args[0].isdigit() or (len(args) > 1 and not args[1].isdigit()):
        await message.answer(
            "Как пользоваться: <code>/grant 123456789 30</code>\n"
            "Первое число — ID человека (он может узнать его командой /myid), второе — дней премиума (по умолчанию 30)."
        )
        return
    user_id, days = int(args[0]), int(args[1]) if len(args) > 1 else 30
    until = await db.grant_premium(user_id, days)
    await message.answer(f"Готово: премиум для {user_id} до {format_time(until)}.")
    try:
        await bot.send_message(user_id, f"🎁 Вам подарили премиум до {format_time(until)}! Подробнее: /premium")
    except Exception:
        await message.answer("Сообщить ему не получилось: он ещё не писал боту. Премиум всё равно включён.")


async def on_error(event: ErrorEvent, bot: Bot):
    """Любая ошибка в боте: пишем в журнал и (не чаще раза в минуту) владельцу."""
    global _last_error_notify
    logging.exception("Ошибка при обработке сообщения", exc_info=event.exception)
    if time.monotonic() - _last_error_notify < ERROR_NOTIFY_INTERVAL:
        return
    _last_error_notify = time.monotonic()
    await notify_owner(bot, f"⚠️ Ошибка в боте:\n<code>{escape(repr(event.exception)[:3000])}</code>")


async def backup_loop(bot: Bot):
    """Раз в сутки присылает владельцу копию базы, чтобы данные не потерялись."""
    if not OWNER_ID:
        return
    while True:
        await asyncio.sleep(BACKUP_INTERVAL)
        path = os.path.join(tempfile.gettempdir(), f"bot-backup-{datetime.now(MSK):%Y-%m-%d}.db")
        try:
            await db.backup(path)
            await bot.send_document(OWNER_ID, FSInputFile(path), caption="Ежедневная копия базы бота")
        except Exception:
            logging.exception("Не удалось отправить копию базы")
        finally:
            if os.path.exists(path):
                os.remove(path)
