"""Платная подписка через Telegram Stars."""
import time
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice,
                           Message, PreCheckoutQuery)

import db
from config import PREMIUM_PERIOD, PREMIUM_PRICE_STARS
from handlers.owner import notify_owner
from utils import format_time

router = Router()

BENEFITS = (
    "⭐ <b>Премиум</b>\n\n"
    "• до 20 розыгрышей одновременно (вместо 1)\n"
    "• до 100 победителей (вместо 3)\n"
    "• совместные розыгрыши: подписка ещё на 9 каналов-партнёров\n"
    "• без подписи бота под постом\n\n"
    f"Цена: {PREMIUM_PRICE_STARS} ⭐ в месяц, продлевается автоматически. Отменить можно в любой момент в настройках Telegram."
)


@router.message(Command("premium"))
async def premium(message: Message, bot: Bot):
    await db.touch_user(message.from_user.id)
    until = await db.premium_until(message.from_user.id)
    if until > time.time():
        await message.answer(f"{BENEFITS}\n\n✅ У вас премиум до {format_time(until)}.")
        return
    # Ссылка на оплату подписки: Telegram сам будет списывать Stars раз в 30 дней.
    link = await bot.create_invoice_link(
        title="Премиум на 30 дней",
        description="Розыгрыши без ограничений и без подписи бота",
        payload="premium_30",
        currency="XTR",  # XTR — это Telegram Stars
        prices=[LabeledPrice(label="Премиум", amount=PREMIUM_PRICE_STARS)],
        subscription_period=PREMIUM_PERIOD,
    )
    button = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Оформить ⭐", url=link)]])
    await message.answer(BENEFITS, reply_markup=button)


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    # Telegram спрашивает: «можно принять оплату?» Отвечаем «да».
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def paid(message: Message, bot: Bot):
    payment = message.successful_payment
    # При автопродлении Telegram присылает новое сообщение об оплате и новую дату окончания.
    until = payment.subscription_expiration_date or int(time.time()) + PREMIUM_PERIOD
    await db.add_payment(message.from_user.id, payment.telegram_payment_charge_id, payment.total_amount, until)
    await message.answer(f"Спасибо! Премиум активен до {format_time(until)} 🎉")
    user = message.from_user
    who = f"@{user.username}" if user.username else user.full_name
    await notify_owner(bot, f"💰 Оплата {payment.total_amount} ⭐ от {escape(who)} (ID {user.id})")


@router.message(Command("paysupport"))
async def paysupport(message: Message):
    # Telegram требует, чтобы у бота с платежами была команда поддержки.
    await message.answer(
        "Проблема с оплатой? Напишите сюда, что случилось, и укажите дату платежа. "
        "Мы ответим и при необходимости вернём Stars."
    )
