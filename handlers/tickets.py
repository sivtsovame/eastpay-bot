import random
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

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
    ticket_num = f"{random.randint(1, 99)}-{now.strftime('%d.%m')}"

    sym = {"RUB": "₽", "USDT": "usdt", "USD": "$"}.get(currency, currency)
    amount_fmt = _fmt_amount(amount)

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Исполнено", callback_data=f"ticket_done:{message.message_id}")
    builder.button(text="❌ Отменить",  callback_data=f"ticket_cancel:{message.message_id}")
    builder.adjust(2)

    await message.reply(
        f"🔴 <b>Заявка №{ticket_num}</b>\n"
        f"Отдает: {sender}\n"
        f"Принимает: {receiver}\n"
        f"Сумма: {amount_fmt} {sym}\n"
        f"Код: {code}\n"
        f"Дедлайн: Отсутствует",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("ticket_done:"))
async def ticket_done(cb: CallbackQuery):
    user = cb.from_user.username or cb.from_user.full_name
    old_text = cb.message.text
    new_text = old_text.replace("🔴", "🟢")
    await cb.message.edit_text(
        new_text + f"\n\n✅ Исполнено: @{user}",
        parse_mode="HTML"
    )
    await cb.answer("Заявка исполнена!")


@router.callback_query(F.data.startswith("ticket_cancel:"))
async def ticket_cancel(cb: CallbackQuery):
    user = cb.from_user.username or cb.from_user.full_name
    old_text = cb.message.text
    new_text = old_text.replace("🔴", "⚫️")
    await cb.message.edit_text(
        new_text + f"\n\n❌ Отменено: @{user}",
        parse_mode="HTML"
    )
    await cb.answer("Заявка отменена!")