"""Нажатие кнопки «Участвовать» под постом в канале."""
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

import db
from utils import is_subscribed_all

router = Router()


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
        await call.answer(f"✅ Вы участвуете! Всего участников: {total}.\nНе отписывайтесь до итогов.", show_alert=True)
    else:
        await call.answer(f"Вы уже участвуете. Всего участников: {total}.", show_alert=True)
