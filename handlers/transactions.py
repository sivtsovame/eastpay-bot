import logging
from datetime import datetime
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from services.garantex import fetch_garus
from database import db

logger = logging.getLogger(__name__)
router = Router()


def _fmt(n: float) -> str:
    if n == int(n):
        return f"{int(n):,}".replace(",", "'")
    return f"{n:,.2f}".replace(",", "'")


@router.message(Command("tx"))
async def cmd_tx(message: Message):
    """
    /tx RUBVL 2470000 USDTVL 0.5%
    """
    parts = message.text.split()
    if len(parts) < 5:
        await message.reply(
            "Формат: <code>/tx RUBVL 2470000 USDTVL 0.5%</code>",
            parse_mode="HTML"
        )
        return

    currency_from = parts[1].upper()   # RUBVL
    try:
        amount_rub = float(parts[2].replace(",", ".").replace("'", ""))
    except ValueError:
        await message.reply("⚠️ Неверная сумма.")
        return
    currency_to = parts[3].upper()     # USDTVL
    city_pct_str = parts[4].replace("%", "")
    try:
        city_pct = float(city_pct_str)
    except ValueError:
        await message.reply("⚠️ Неверный процент.")
        return

    # Получаем курс
    try:
        ex_rate = await fetch_garus()
    except Exception as e:
        await message.reply(f"⚠️ Не удалось получить курс: {e}")
        return

    # Расчёт
    rate_with_pct = ex_rate * (1 - city_pct / 100)
    amount_usdt = amount_rub / rate_with_pct

    # Transaction ID
    now = datetime.now()
    tx_num = await db.get_next_tx_number(message.chat.id)
    tx_id = f"{now.strftime('%d.%m')}-{tx_num}"

    # Имя менеджера
    manager = message.from_user.username or message.from_user.full_name
    manager = manager.lower().replace(" ", "")

    # Название чата
    chat = message.chat
    if chat.type == "private":
        chat_name = "Private"
    else:
        chat_name = chat.title or "Group"

    # Обновляем балансы
    await db.update_balance(message.chat.id, currency_from, -amount_rub)
    await db.update_balance(message.chat.id, currency_to, amount_usdt)

    # Получаем все балансы
    balances = await db.get_all_balances(message.chat.id)
    balance_lines = "\n".join(
        f"{b['currency']}: {_fmt(b['amount'])}" for b in balances
    )

    await message.reply(
        f"Balance has been changed by <b>manager{manager}</b>\n"
        f"Transaction ID: {tx_id}\n"
        f"Client chat: {chat_name}\n\n"
        f"{ex_rate} - {city_pct}% = {rate_with_pct:.2f}\n"
        f"{currency_from}: -{_fmt(amount_rub)}\n"
        f"{currency_to}: {_fmt(amount_usdt)} (-{_fmt(amount_rub)}/{rate_with_pct:.2f})\n\n"
        f"Current balance:\n{balance_lines}",
        parse_mode="HTML"
    )