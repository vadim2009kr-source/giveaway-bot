"""Подведение итогов: выбор победителей и фоновая проверка по времени."""
import asyncio
import logging
import random
from html import escape

from aiogram import Bot

import db
from handlers.owner import notify_owner
from utils import is_subscribed_all, mention

# SystemRandom — «честный» генератор случайных чисел, его нельзя предсказать.
rng = random.SystemRandom()


async def draw(bot: Bot, giveaway) -> None:
    gid = giveaway["id"]
    await db.finish(gid)  # сразу помечаем, чтобы итоги не подвелись дважды

    people = list(await db.participants(gid))
    rng.shuffle(people)

    # Идём по перемешанному списку и берём тех, кто всё ещё подписан на все каналы.
    winners = []
    for user_id, name in people:
        if len(winners) >= giveaway["winners_count"]:
            break
        if await is_subscribed_all(bot, giveaway, user_id):
            winners.append((user_id, name))
        await asyncio.sleep(0.05)  # не спамим Telegram запросами

    if winners:
        lines = "\n".join(f"{i}. {mention(uid, name)}" for i, (uid, name) in enumerate(winners, 1))
        result = f"🎉 <b>Итоги розыгрыша!</b>\n\nУчастников: {len(people)}\nПобедители:\n{lines}\n\nПоздравляем!"
    else:
        result = "😔 Розыгрыш завершён, но подходящих участников не нашлось."

    try:
        await bot.send_message(giveaway["channel_id"], result, reply_to_message_id=giveaway["message_id"])
        await bot.edit_message_reply_markup(
            chat_id=giveaway["channel_id"], message_id=giveaway["message_id"], reply_markup=None
        )
    except Exception as e:
        logging.warning("Не удалось опубликовать итоги розыгрыша %s: %s", gid, e)

    try:
        await bot.send_message(giveaway["owner_id"], f"Итоги розыгрыша в «{escape(giveaway['channel_title'])}»:\n\n{result}")
    except Exception:
        pass  # админ мог заблокировать бота, это не страшно


async def scheduler(bot: Bot) -> None:
    """Каждые 20 секунд проверяет, не пора ли подвести итоги какого-нибудь розыгрыша."""
    while True:
        try:
            for giveaway in await db.due_giveaways():
                await draw(bot, giveaway)
        except Exception as e:
            logging.exception("Ошибка в планировщике")
            await notify_owner(bot, f"⚠️ Ошибка при подведении итогов: {escape(repr(e)[:3000])}")
        await asyncio.sleep(20)
