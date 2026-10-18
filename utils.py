"""Общие помощники, которые нужны в разных частях бота."""
from datetime import datetime
from html import escape

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import db
from config import FREE_LIMITS, MSK, PREMIUM_LIMITS


async def limits_for(user_id: int) -> dict:
    return PREMIUM_LIMITS if await db.is_premium(user_id) else FREE_LIMITS


async def is_subscribed(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Подписан ли человек на канал. Бот должен быть админом канала, иначе Telegram не ответит."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    if member.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER):
        return True
    # «Ограниченный» участник всё ещё может быть подписан.
    return member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False)


def format_time(ts: int) -> str:
    return datetime.fromtimestamp(ts, MSK).strftime("%d.%m.%Y %H:%M") + " (МСК)"


def post_text(text: str, winners: int, ends_at: int, bot_username: str, watermark: bool) -> str:
    result = (
        f"{text}\n\n"
        f"🏆 Победителей: <b>{winners}</b>\n"
        f"⏰ Итоги: <b>{format_time(ends_at)}</b>\n"
        f"Чтобы участвовать, подпишитесь на канал и нажмите кнопку ниже."
    )
    if watermark:
        result += f"\n\n<i>Розыгрыш проводится через @{escape(bot_username)}</i>"
    return result


def join_keyboard(giveaway_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎉 Участвовать", callback_data=f"join:{giveaway_id}")]
    ])


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{escape(name)}</a>'
