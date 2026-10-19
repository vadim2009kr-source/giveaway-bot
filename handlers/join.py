"""Нажатие кнопки «Участвовать» под постом в канале."""
import asyncio
import time

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

import db
from utils import is_subscribed_all, limits_for, post_keyboard

router = Router()

# Счётчик на кнопке обновляем не чаще раза в 5 секунд, иначе Telegram начнёт ограничивать бота.
COUNTER_INTERVAL = 5
_last_update: dict[int, float] = {}
_pending: set[int] = set()
_dirty: set[int] = set()   # кто-то вступил, пока обновление уже шло
_tasks: set[asyncio.Task] = set()


async def _refresh_counter(bot: Bot, giveaway_id: int):
    wait = _last_update.get(giveaway_id, 0) + COUNTER_INTERVAL - time.monotonic()
    _dirty.discard(giveaway_id)
    try:
        if wait > 0:
            await asyncio.sleep(wait)
        giveaway = await db.get_giveaway(giveaway_id)
        if giveaway and giveaway["status"] == "active":
            total = await db.count_participants(giveaway_id)
            await bot.edit_message_reply_markup(
                chat_id=giveaway["channel_id"], message_id=giveaway["message_id"],
                reply_markup=await post_keyboard(bot, giveaway_id, giveaway["owner_id"], total),
            )
    except Exception:
        pass  # не страшно, если счётчик не обновился: обновится при следующем участнике
    finally:
        _last_update[giveaway_id] = time.monotonic()
        _pending.discard(giveaway_id)
        if giveaway_id in _dirty:
            schedule_counter_update(bot, giveaway_id)


def schedule_counter_update(bot: Bot, giveaway_id: int):
    """Запускает обновление счётчика в фоне. Несколько нажатий подряд дают одно обновление."""
    if giveaway_id in _pending:
        _dirty.add(giveaway_id)
        return
    _pending.add(giveaway_id)
    task = asyncio.create_task(_refresh_counter(bot, giveaway_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@router.callback_query(F.data.startswith("join:"))
async def join(call: CallbackQuery, bot: Bot):
    giveaway = await db.get_giveaway(int(call.data.split(":")[1]))
    if not giveaway or giveaway["status"] != "active":
        await call.answer("Этот розыгрыш уже завершён.", show_alert=True)
        return

    if not await is_subscribed_all(bot, giveaway, call.from_user.id):
        await call.answer("Сначала подпишитесь на все каналы из условий, потом нажмите кнопку ещё раз.",
                          show_alert=True)
        return

    added = await db.add_participant(giveaway["id"], call.from_user.id, call.from_user.full_name)
    total = await db.count_participants(giveaway["id"])
    if added:
        schedule_counter_update(bot, giveaway["id"])
        text = f"✅ Вы участвуете! Всего участников: {total}.\nНе отписывайтесь до итогов."
        if (await limits_for(giveaway["owner_id"]))["watermark"]:
            text += "\n\nХотите такой же розыгрыш в своём канале? Кнопка под постом 👇"
        await call.answer(text, show_alert=True)
    else:
        await call.answer(f"Вы уже участвуете. Всего участников: {total}.", show_alert=True)
