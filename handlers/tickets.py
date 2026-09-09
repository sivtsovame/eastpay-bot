import random
import logging
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import db

logger = logging.getLogger(__name__)
router = Router()


def _generate_code() -> str:
    return f"{random.randint(100, 999)}-{random.randint(100, 999)}"


def _fmt_amount(amount_str: str) -> str:
    try:
        amount = float(amount_str.replace(",", ".").replace("'", "").replace(" ", ""))
        if amount == int(amount):
            return f"{int(amount):,}".replace(",", "'")
        return f"{amount:,.2f}".replace(",", "'")
    except Exception:
        return amount_str


@router.message(Command("ticket"))
async def cmd_ticket(message: Message):
    """
    /ticket @sender @receiver 1877500 RUB
    """
    parts = message.text.split(maxsplit=4)
    if len(parts) < 4:
        await message.reply(
            "Формат: <code>/ticket @отправитель @получатель 1877500 RUB</code>",
            parse_mode="HTML"
        )
        return

    sender   = parts[1]
    receiver = parts[2]
    amount   = parts[3]
    currency = parts[4].upper() if len(parts) > 4 else "RUB"

    code = _generate_code()
    now  = datetime.now()

    # Получаем следующий номер заявки
    ticket_num = await db.get_next_ticket_number(message.chat.id)
    ticket_label = f"№{ticket_num}-{now.strftime('%d.%m')}"

    sym = {"RUB": "₽", "USDT": "usdt", "USD": "$", "KRW": "KRW", "JPY": "JPY"}.get(currency, currency)
    amount_fmt = _fmt_amount(amount)

    creator_id = message.from_user.id

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Исполнено", callback_data=f"ticket_done:{ticket_num}:{creator_id}")
    builder.button(text="❌ Отменить",  callback_data=f"ticket_cancel:{ticket_num}:{creator_id}")
    builder.adjust(2)

    sent = await message.reply(
        f"🔴 <b>Заявка {ticket_label}</b>\n"
        f"Отдает: {sender}\n"
        f"Принимает: {receiver}\n"
        f"Сумма: {amount_fmt} {sym}\n"
        f"Код: {code}\n"
        f"Дедлайн: Отсутствует",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

    # Сохраняем заявку в БД
    await db.create_ticket(
        chat_id=message.chat.id,
        ticket_num=ticket_num,
        ticket_label=ticket_label,
        sender=sender,
        receiver=receiver,
        amount=amount_fmt,
        currency=sym,
        code=code,
        creator_id=creator_id,
        message_id=sent.message_id,
    )


async def _can_act(cb: CallbackQuery, creator_id: int) -> bool:
    """Проверяет что пользователь — создатель или админ группы."""
    user_id = cb.from_user.id
    if user_id == creator_id:
        return True
    try:
        member = await cb.bot.get_chat_member(cb.message.chat.id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


@router.callback_query(F.data.startswith("ticket_done:"))
async def ticket_done(cb: CallbackQuery):
    _, ticket_num, creator_id_str = cb.data.split(":")
    creator_id = int(creator_id_str)

    if not await _can_act(cb, creator_id):
        await cb.answer("⛔ Только создатель или админ может исполнить заявку.", show_alert=True)
        return

    user = cb.from_user.username or cb.from_user.full_name
    old_text = cb.message.text
    new_text = old_text.replace("🔴", "🟢")
    await cb.message.edit_text(
        new_text + f"\n\n✅ Исполнено: @{user}",
        parse_mode="HTML"
    )
    await db.update_ticket_status(cb.message.chat.id, int(ticket_num), "done")
    await cb.answer("Заявка исполнена!")


@router.callback_query(F.data.startswith("ticket_cancel:"))
async def ticket_cancel(cb: CallbackQuery):
    _, ticket_num, creator_id_str = cb.data.split(":")
    creator_id = int(creator_id_str)

    if not await _can_act(cb, creator_id):
        await cb.answer("⛔ Только создатель или админ может отменить заявку.", show_alert=True)
        return

    user = cb.from_user.username or cb.from_user.full_name
    old_text = cb.message.text
    new_text = old_text.replace("🔴", "⚫️")
    await cb.message.edit_text(
        new_text + f"\n\n❌ Отменено: @{user}",
        parse_mode="HTML"
    )
    await db.update_ticket_status(cb.message.chat.id, int(ticket_num), "cancelled")
    await cb.answer("Заявка отменена!")


@router.message(Command("ticketlist"))
async def cmd_ticketlist(message: Message):
    """Список неисполненных заявок."""
    tickets = await db.get_open_tickets(message.chat.id)
    if not tickets:
        await message.reply("✅ Нет открытых заявок.")
        return

    lines = ["<b>📋 Открытые заявки:</b>\n"]
    for t in tickets:
        lines.append(
            f"🔴 <b>Заявка {t['ticket_label']}</b>\n"
            f"Сумма: {t['amount']} {t['currency']}\n"
        )
    await message.reply("\n".join(lines), parse_mode="HTML")