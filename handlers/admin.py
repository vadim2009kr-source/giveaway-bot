"""Всё, что делает админ канала: создание розыгрыша и список своих розыгрышей."""
import time
from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message, MessageOriginChannel)

import db
from config import MSK, REFERRAL_BONUS_DAYS
from draw import draw
from utils import channel_link, format_time, limits_for, post_keyboard, post_text

router = Router()
# Этот файл отвечает только на личные сообщения боту.
router.message.filter(F.chat.type == ChatType.PRIVATE)

HELP = (
    "👋 Я помогаю проводить розыгрыши в Telegram-каналах.\n\n"
    "Как начать:\n"
    "1. Добавьте меня в свой канал администратором (с правом публиковать сообщения).\n"
    "2. Отправьте /new и ответьте на несколько вопросов.\n\n"
    "Команды:\n"
    "/new — создать розыгрыш\n"
    "/my — мои активные розыгрыши\n"
    "/premium — премиум без ограничений\n"
    "/invite — пригласить админа и получить премиум\n"
    "/cancel — отменить создание"
)


class NewGiveaway(StatesGroup):
    channel = State()
    partners = State()
    text = State()
    winners = State()
    ends_at = State()
    confirm = State()


@router.message(CommandStart())
@router.message(Command("help"))
async def start(message: Message, command: CommandObject):
    # Ссылка вида t.me/бот?start=ref_123 значит, что человека пригласил пользователь 123.
    referrer = None
    if command.args and command.args.startswith("ref_") and command.args[4:].isdigit():
        referrer = int(command.args[4:])
    await db.touch_user(message.from_user.id, referrer)
    await message.answer(HELP)


@router.message(Command("invite"))
async def invite(message: Message, bot: Bot):
    await db.touch_user(message.from_user.id)
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=ref_{message.from_user.id}"
    came, active = await db.referral_stats(message.from_user.id)
    await message.answer(
        "🤝 <b>Пригласите админа другого канала</b>\n\n"
        f"Когда он придёт по вашей ссылке и проведёт первый розыгрыш, вы оба получите "
        f"{REFERRAL_BONUS_DAYS} дней премиума бесплатно.\n\n"
        f"Ваша ссылка:\n{link}\n\n"
        f"Пришло по ссылке: {came}, провели розыгрыш: {active}"
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено. Чтобы начать заново, отправьте /new")


# ---------- Мои розыгрыши ----------
# Эти команды стоят выше шагов создания, чтобы работать и посреди создания розыгрыша.

@router.message(Command("my"))
async def my(message: Message):
    items = await db.active_giveaways(message.from_user.id)
    if not items:
        await message.answer("Активных розыгрышей нет. Создать: /new")
        return
    for g in items:
        button = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🏁 Подвести итоги сейчас", callback_data=f"draw:{g['id']}")
        ]])
        await message.answer(
            f"«{escape(g['channel_title'])}»\nУчастников: {g['members']}\n"
            f"Победителей: {g['winners_count']}\nИтоги: {format_time(g['ends_at'])}",
            reply_markup=button,
        )


@router.callback_query(F.data.startswith("draw:"))
async def draw_now(call: CallbackQuery, bot: Bot):
    giveaway = await db.get_giveaway(int(call.data.split(":")[1]))
    if not giveaway or giveaway["owner_id"] != call.from_user.id or giveaway["status"] != "active":
        await call.answer("Этот розыгрыш уже завершён.", show_alert=True)
        return
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Подвожу итоги…")
    await draw(bot, giveaway)


# ---------- Шаг 1: канал ----------

@router.message(Command("new"))
async def new(message: Message, state: FSMContext):
    await db.touch_user(message.from_user.id)
    limits = await limits_for(message.from_user.id)
    active = await db.active_giveaways(message.from_user.id)
    if len(active) >= limits["max_active"]:
        await message.answer(
            f"Сейчас можно вести не больше {limits['max_active']} розыгрыша одновременно.\n"
            "Дождитесь итогов текущего или оформите /premium, чтобы снять ограничение."
        )
        return
    await state.set_state(NewGiveaway.channel)
    await message.answer(
        "В каком канале проводим розыгрыш?\n\n"
        "Перешлите мне любой пост из этого канала или пришлите его @username.\n"
        "Не забудьте сначала добавить меня в канал администратором."
    )


async def resolve_channel(message: Message, bot: Bot):
    """Находит канал по пересланному посту или @username. Возвращает канал или None (и объясняет, что не так)."""
    if isinstance(message.forward_origin, MessageOriginChannel):
        chat_ref = message.forward_origin.chat.id
    elif message.text and message.text.strip().startswith("@"):
        chat_ref = message.text.strip()
    else:
        await message.answer("Перешлите пост из канала или пришлите @username канала.")
        return None
    try:
        chat = await bot.get_chat(chat_ref)
    except Exception:
        await message.answer("Не могу найти этот канал. Проверьте, что я добавлен туда администратором.")
        return None
    if chat.type != ChatType.CHANNEL:
        await message.answer("Это не канал. Пока я работаю только с каналами.")
        return None
    return chat


@router.message(NewGiveaway.channel)
async def got_channel(message: Message, state: FSMContext, bot: Bot):
    chat = await resolve_channel(message, bot)
    if not chat:
        return
    try:
        me = await bot.get_chat_member(chat.id, bot.id)
        user = await bot.get_chat_member(chat.id, message.from_user.id)
    except Exception:
        await message.answer("Не могу проверить права в этом канале. Проверьте, что я добавлен туда администратором.")
        return
    if me.status != ChatMemberStatus.ADMINISTRATOR or not getattr(me, "can_post_messages", False):
        await message.answer("Сделайте меня администратором канала с правом публиковать сообщения и пришлите канал ещё раз.")
        return
    if user.status not in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR):
        await message.answer("Создавать розыгрыши могут только администраторы этого канала.")
        return

    await state.update_data(channel_id=chat.id, channel_title=chat.title, partners=[])
    limits = await limits_for(message.from_user.id)
    if limits["max_channels"] > 1:
        await state.set_state(NewGiveaway.partners)
        await message.answer(
            f"Канал «{escape(chat.title)}» подходит ✅\n\n"
            "Это совместный розыгрыш? Перешлите пост из канала-партнёра или пришлите его @username — "
            f"участникам нужно будет подписаться и на него (до {limits['max_channels'] - 1} партнёров).\n"
            "Меня нужно добавить администратором и в каналы-партнёры.",
            reply_markup=partners_done_keyboard(),
        )
    else:
        await state.set_state(NewGiveaway.text)
        await message.answer(
            f"Канал «{escape(chat.title)}» подходит ✅\n"
            "<i>Совместные розыгрыши с каналами-партнёрами доступны в /premium.</i>\n\n"
            "Теперь пришлите текст розыгрыша (можно с одной картинкой)."
        )


# ---------- Шаг 1.5: каналы-партнёры (только премиум) ----------

def partners_done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Готово, дальше ➡️", callback_data="partners_done")
    ]])


@router.message(NewGiveaway.partners)
async def got_partner(message: Message, state: FSMContext, bot: Bot):
    chat = await resolve_channel(message, bot)
    if not chat:
        return
    data = await state.get_data()
    partners = data["partners"]
    if chat.id == data["channel_id"] or any(c["id"] == chat.id for c in partners):
        await message.answer("Этот канал уже в списке.", reply_markup=partners_done_keyboard())
        return
    try:
        me = await bot.get_chat_member(chat.id, bot.id)
    except Exception:
        me = None
    # Без прав администратора Telegram не даст боту проверить подписку.
    if not me or me.status != ChatMemberStatus.ADMINISTRATOR:
        await message.answer(
            f"Я не администратор в «{escape(chat.title)}», поэтому не смогу проверить подписку. "
            "Попросите админа партнёра добавить меня и пришлите канал ещё раз.",
            reply_markup=partners_done_keyboard(),
        )
        return

    limits = await limits_for(message.from_user.id)
    partners.append({"id": chat.id, "title": chat.title, "link": channel_link(chat)})
    await state.update_data(partners=partners)
    if len(partners) + 1 >= limits["max_channels"]:
        await state.set_state(NewGiveaway.text)
        await message.answer(f"Добавил «{escape(chat.title)}». Это максимум каналов.\n\nТеперь пришлите текст розыгрыша.")
        return
    await message.answer(
        f"Добавил «{escape(chat.title)}» ✅ Каналов-партнёров: {len(partners)}.\n"
        "Пришлите следующий или нажмите «Готово».",
        reply_markup=partners_done_keyboard(),
    )


@router.callback_query(NewGiveaway.partners, F.data == "partners_done")
async def partners_done(call: CallbackQuery, state: FSMContext):
    await state.set_state(NewGiveaway.text)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Теперь пришлите текст розыгрыша (можно с одной картинкой).")
    await call.answer()


# ---------- Шаг 2: текст ----------

@router.message(NewGiveaway.text)
async def got_text(message: Message, state: FSMContext):
    if message.photo:
        text = message.html_text if message.caption else ""
        photo_id = message.photo[-1].file_id
    elif message.text:
        text, photo_id = message.html_text, None
    else:
        await message.answer("Пришлите текст или картинку с подписью.")
        return
    if not text:
        await message.answer("Добавьте к картинке подпись с условиями розыгрыша.")
        return

    await state.update_data(text=text, photo_id=photo_id)
    await state.set_state(NewGiveaway.winners)
    limits = await limits_for(message.from_user.id)
    await message.answer(f"Сколько будет победителей? (от 1 до {limits['max_winners']})")


# ---------- Шаг 3: число победителей ----------

@router.message(NewGiveaway.winners)
async def got_winners(message: Message, state: FSMContext):
    limits = await limits_for(message.from_user.id)
    if not (message.text and message.text.isdigit() and 1 <= int(message.text) <= limits["max_winners"]):
        hint = "" if limits["max_winners"] > 3 else "\nВ /premium можно до 100 победителей."
        await message.answer(f"Пришлите число от 1 до {limits['max_winners']}.{hint}")
        return
    await state.update_data(winners=int(message.text))
    await state.set_state(NewGiveaway.ends_at)
    await message.answer(
        "Когда подвести итоги?\n\n"
        "Пришлите количество часов (например, 24)\n"
        "или дату и время по Москве: 25.10.2026 18:00"
    )


# ---------- Шаг 4: время итогов ----------

def parse_end(text: str) -> int | None:
    text = text.strip()
    if text.isdigit():
        return int(time.time()) + int(text) * 3600
    try:
        return int(datetime.strptime(text, "%d.%m.%Y %H:%M").replace(tzinfo=MSK).timestamp())
    except ValueError:
        return None


@router.message(NewGiveaway.ends_at)
async def got_end(message: Message, state: FSMContext, bot: Bot):
    ends_at = parse_end(message.text or "")
    now = time.time()
    if ends_at is None or ends_at < now + 600 or ends_at > now + 60 * 24 * 3600:
        await message.answer("Укажите время от 10 минут до 60 дней вперёд, например 24 или 25.10.2026 18:00")
        return
    await state.update_data(ends_at=ends_at)
    await state.set_state(NewGiveaway.confirm)

    data = await state.get_data()
    limits = await limits_for(message.from_user.id)
    me = await bot.me()
    preview = post_text(data["text"], data["winners"], ends_at, me.username, limits["watermark"], data["partners"])
    buttons = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать", callback_data="publish"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    ]])
    await message.answer("Так будет выглядеть пост:")
    if data["photo_id"]:
        await message.answer_photo(data["photo_id"], caption=preview, reply_markup=buttons)
    else:
        await message.answer(preview, reply_markup=buttons)


# ---------- Шаг 5: публикация ----------

@router.callback_query(NewGiveaway.confirm, F.data == "cancel")
async def cancel_button(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Отменено. Чтобы начать заново, отправьте /new")
    await call.answer()


@router.callback_query(NewGiveaway.confirm, F.data == "publish")
async def publish(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)

    limits = await limits_for(call.from_user.id)
    gid = await db.create_giveaway(
        call.from_user.id, data["channel_id"], data["channel_title"],
        data["text"], data["photo_id"], data["winners"], data["ends_at"], data["partners"],
    )
    me = await bot.me()
    text = post_text(data["text"], data["winners"], data["ends_at"], me.username, limits["watermark"], data["partners"])
    keyboard = await post_keyboard(bot, gid, call.from_user.id)
    try:
        if data["photo_id"]:
            post = await bot.send_photo(data["channel_id"], data["photo_id"], caption=text, reply_markup=keyboard)
        else:
            post = await bot.send_message(data["channel_id"], text, reply_markup=keyboard)
    except Exception as e:
        await db.delete_giveaway(gid)
        await call.message.answer(f"Не получилось опубликовать пост: {e}\nПроверьте мои права в канале.")
        await call.answer()
        return

    await db.set_message_id(gid, post.message_id)
    await call.message.answer(f"Готово! Розыгрыш опубликован, итоги {format_time(data['ends_at'])}.\nСледить за ним: /my")
    await call.answer()
    await reward_referral(bot, call.from_user.id)


async def reward_referral(bot: Bot, user_id: int):
    """Первый розыгрыш приглашённого админа: дарим премиум ему и тому, кто его пригласил."""
    referrer = await db.claim_referral(user_id)
    if not referrer:
        return
    await db.grant_premium(user_id, REFERRAL_BONUS_DAYS)
    await db.grant_premium(referrer, REFERRAL_BONUS_DAYS)
    await bot.send_message(user_id, f"🎁 Вам подарок за первый розыгрыш: {REFERRAL_BONUS_DAYS} дней премиума!")
    try:
        await bot.send_message(
            referrer, f"🎁 Приглашённый вами админ провёл первый розыгрыш. Вам {REFERRAL_BONUS_DAYS} дней премиума!"
        )
    except Exception:
        pass  # пригласивший мог заблокировать бота, премиум всё равно начислен
