import re
import logging
import aiohttp
from datetime import datetime
from aiogram import Router
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from simpleeval import SimpleEval
from services.garantex import fetch_garus
from database.db import get_formula, get_all_formulas

logger = logging.getLogger(__name__)
router = Router()


def _is_btc_address(text: str) -> bool:
    """Проверяет что строка похожа на BTC-адрес а не формулу."""
    if len(text) < 25 or len(text) > 62:
        return False
    if any(op in text for op in ['+', '-', '*', '/', '(', ')', '%', ' ']):
        return False
    if not re.match(r'^[13a-zA-Z0-9]+$', text):
        return False
    return True


def _apply_percent(value: float, expr: str) -> float:
    parts = re.findall(r'([+-]?\d+(?:\.\d+)?)%', expr)
    for p in parts:
        value = value * (1 + float(p) / 100)
    return value


async def evaluate_expression(expr: str, user_id: int) -> float:
    raw = expr.strip()

    formulas = await get_all_formulas(user_id)
    for f in formulas:
        raw = re.sub(re.escape(f["shortcut"]), f"({f['formula']})", raw, flags=re.IGNORECASE)

    if re.search(r'\b(ex|usd)\b', raw, re.IGNORECASE):
        garus = await fetch_garus()
        raw = re.sub(r'\b(ex|usd)\b', str(garus), raw, flags=re.IGNORECASE)

    raw = _preprocess_percents(raw)

    evaluator = SimpleEval()
    result = evaluator.eval(raw)
    return float(result)


def _preprocess_percents(expr: str) -> str:
    def replace_percent(m):
        sign = m.group(1)
        num = m.group(2)
        if sign == '+':
            return f'*(1+{num}/100)'
        else:
            return f'*(1-{num}/100)'
    result = re.sub(r'([+-])(\d+(?:\.\d+)?)%', replace_percent, expr)
    return result


def _format_number(n: float) -> str:
    if n == int(n) and abs(n) < 1e15:
        return f"{int(n):,}".replace(",", "'")
    formatted = f"{n:.8f}".rstrip("0").rstrip(".")
    parts = formatted.split(".")
    parts[0] = f"{int(parts[0]):,}".replace(",", "'")
    return ".".join(parts)


async def _get_btc_address_info(address: str) -> str | None:
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        ) as session:
            async with session.get(
                f"https://blockstream.info/api/address/{address}/txs"
            ) as resp:
                if resp.status != 200:
                    return None
                txs = await resp.json()

        if not txs:
            return None

        lines = [f"Адрес {address}"]
        for tx in txs[:5]:
            received = sum(
                o["value"] for o in tx.get("vout", [])
                if o.get("scriptpubkey_address") == address
            )
            spent = sum(
                i.get("prevout", {}).get("value", 0)
                for i in tx.get("vin", [])
                if i.get("prevout", {}).get("scriptpubkey_address") == address
            )
            delta = (received - spent) / 1e8
            sign = "+" if delta >= 0 else ""
            status = tx.get("status", {})
            date = ""
            if status.get("block_time"):
                dt = datetime.utcfromtimestamp(status["block_time"])
                date = dt.strftime("%d.%m %H:%M:%S")
            txid = tx["txid"]
            lines.append(
                f"{sign}{delta:.8f} {date} -> https://blockstream.info/tx/{txid}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"Ошибка получения BTC адреса: {e}")
        return None


@router.inline_query()
async def inline_calculator(query: InlineQuery):
    text = query.query.strip()
    if not text:
        return

    user_id = query.from_user.id
    results = []

    # Проверяем BTC-адрес (только если нет операторов)
    if _is_btc_address(text):
        info = await _get_btc_address_info(text)
        if info:
            results.append(
                InlineQueryResultArticle(
                    id="btc_address",
                    title=f"BTC: {text[:20]}...",
                    description="Последние транзакции",
                    input_message_content=InputTextMessageContent(
                        message_text=f"<code>{info}</code>",
                        parse_mode="HTML",
                    ),
                )
            )
        await query.answer(results=results, cache_time=1, is_personal=True)
        return

    # Калькулятор
    try:
        result = await evaluate_expression(text, user_id)
        result_str = _format_number(result)
        results.append(
            InlineQueryResultArticle(
                id="calc_result",
                title=result_str,
                description=text,
                input_message_content=InputTextMessageContent(
                    message_text=f"<b>{result_str}</b>\n<code>{text}</code>",
                    parse_mode="HTML",
                ),
            )
        )
    except Exception:
        results.append(
            InlineQueryResultArticle(
                id="calc_error",
                title="Ошибка в выражении",
                description=text[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"⚠️ Не удалось вычислить: <code>{text}</code>",
                    parse_mode="HTML",
                ),
            )
        )

    await query.answer(results=results, cache_time=1, is_personal=True)