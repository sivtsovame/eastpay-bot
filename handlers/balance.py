import re
import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from simpleeval import SimpleEval
from database import db

logger = logging.getLogger(__name__)
router = Router()

CURRENCY_SYMBOLS = {
    "USD": "$", "RUB": "₽", "USDT": "usdt",
    "BTC": "฿", "EUR": "€", "CNY": "¥",
    "USDTKHV": "usdt", "USDTVL": "usdt", "USDTSKH": "usdt",
    "USDTMSK": "usdt", "KHV": "₽", "VL": "₽", "MSK": "₽",
}


def _sym(currency: str) -> str:
    return CURRENCY_SYMBOLS.get(currency.upper(), currency.upper())


def _eval_amount(expr: str) -> float:
    """Безопасно вычисляет числовое выражение, например -100*7."""
    ev = SimpleEval()
    return float(ev.eval(expr.replace(",", ".")))


@router.message(Command("b"))
async def balance_command(message: Message):
    args = message.text.split(maxsplit=1)
    chat_id = message.chat.id

    # /b — показать все балансы
    if len(args) == 1:
        balances = await db.get_all_balances(chat_id)
        if not balances:
            await message.reply("📭 Балансов нет. Создайте: <code>/b usd 100</code>", parse_mode="HTML")
            return
        lines = []
        for b in balances:
            lines.append(f"{b['currency']}: {_fmt(b['amount'])}")
        await message.reply("\n".join(lines), parse_mode="HTML")
        return

    rest = args[1].strip()
    parts = rest.split(maxsplit=1)
    sub = parts[0].lower()

    # /b del USD
    if sub == "del" and len(parts) > 1:
        currency = parts[1].upper()
        await db.delete_balance(chat_id, currency)
        await message.reply(f"🗑 Валюта <b>{currency}</b> удалена.", parse_mode="HTML")
        return

    # /b clear USD
    if sub == "clear" and len(parts) > 1:
        currency = parts[1].upper()
        await db.set_balance(chat_id, currency, 0.0)
        await message.reply(f"🔄 Баланс <b>{currency}</b> обнулён.", parse_mode="HTML")
        return

    # /b stat USD
    if sub == "stat" and len(parts) > 1:
        currency = parts[1].upper()
        balance = await db.get_balance(chat_id, currency)
        history = await db.get_balance_history(chat_id, currency)
        turnover = await db.get_total_turnover(chat_id, currency)
        sym = _sym(currency)

        bal_str = _fmt(balance if balance is not None else 0)
        lines = [
            f"<b>Баланс {currency}:</b> {bal_str} {sym}\n",
            f"Оборот: {_fmt(turnover)} {sym}",
            "Последние операции:",
        ]
        for h in history:
            sign = "+" if h["delta"] >= 0 else ""
            lines.append(f"{sign}{_fmt(h['delta'])} {sym}")
        await message.reply("\n".join(lines), parse_mode="HTML")
        return

    # /b USD — показать баланс по валюте
    # /b USD 100 — добавить
    # /b USD -100*7 — вычесть
    currency = parts[0].upper()

    if len(parts) == 1:
        # просто показать баланс
        balance = await db.get_balance(chat_id, currency)
        if balance is None:
            await message.reply(
                f"Валюта <b>{currency}</b> не найдена.\n"
                f"Создать: <code>/b {currency} 0</code>",
                parse_mode="HTML"
            )
            return
        sym = _sym(currency)
        await message.reply(
            f"<b>{currency}:</b> {_fmt(balance)} {sym}", parse_mode="HTML"
        )
        return

    # Есть значение — изменяем баланс
    amount_expr = parts[1]
    try:
        delta = _eval_amount(amount_expr)
    except Exception:
        await message.reply("⚠️ Не удалось распознать сумму. Пример: <code>/b usd 100</code> или <code>/b usd -100*7</code>", parse_mode="HTML")
        return

    await db.update_balance(chat_id, currency, delta)
    new_balance = await db.get_balance(chat_id, currency)
    sym = _sym(currency)
    sign = "+" if delta >= 0 else ""
    await message.reply(
        f"<b>{currency}</b> {sign}{_fmt(delta)} {sym}\n"
        f"Итого: {_fmt(new_balance)} {sym}",
        parse_mode="HTML"
    )


@router.message(Command("balance_stat"))
async def balance_stat_export(message: Message):
    """Отдаёт полную статистику в текстовом виде (Excel-экспорт можно добавить позже)."""
    chat_id = message.chat.id
    balances = await db.get_all_balances(chat_id)
    if not balances:
        await message.reply("Нет данных для экспорта.")
        return

    lines = ["<b>📊 Полная статистика:</b>\n"]
    for b in balances:
        currency = b["currency"]
        sym = _sym(currency)
        turnover = await db.get_total_turnover(chat_id, currency)
        history = await db.get_balance_history(chat_id, currency, limit=10)
        lines.append(f"<b>{currency}:</b> {_fmt(b['amount'])} {sym} | оборот: {_fmt(turnover)} {sym}")
        for h in history:
            sign = "+" if h["delta"] >= 0 else ""
            lines.append(f"  {sign}{_fmt(h['delta'])} {sym}  [{h['created_at'][:16]}]")
        lines.append("")

    await message.reply("\n".join(lines), parse_mode="HTML")

@router.message(Command("roll"))
async def cmd_roll(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("Укажите число: <code>/roll 100</code>", parse_mode="HTML")
        return
    try:
        max_num = int(parts[1])
    except ValueError:
        await message.reply("Укажите целое число: <code>/roll 100</code>", parse_mode="HTML")
        return
    import random
    result = random.randint(0, max_num)
    await message.reply(f"🎲 <b>{result}</b> (0 — {max_num})", parse_mode="HTML")
    
def _fmt(n: float | None) -> str:
    if n is None:
        return "0.00"
    if n == int(n):
        return f"{int(n):,}".replace(",", "'")
    return f"{n:,.8f}".rstrip("0").rstrip(".").replace(",", "'")
