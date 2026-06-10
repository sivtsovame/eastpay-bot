import logging
import asyncio
import aiohttp
from datetime import datetime
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message
from database import db

logger = logging.getLogger(__name__)
router = Router()

TRON_API = "https://apilist.tronscanapi.com/api/transaction?sort=-timestamp&count=true&limit=10&address={address}&tokens=TRX"
TRON_TRC20_API = "https://apilist.tronscanapi.com/api/token_trc20/transfers?limit=10&start=0&toAddress={address}&contract_address=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
BLOCKSTREAM_API = "https://blockstream.info/api/address/{address}/txs"


def _is_tron_address(address: str) -> bool:
    return address.startswith("T") and len(address) == 34


def _is_btc_address(address: str) -> bool:
    return len(address) >= 25 and len(address) <= 62 and address[0] in "13bc"


# ════════════════════════════════════════════════════════════════════════════
#  КОМАНДЫ
# ════════════════════════════════════════════════════════════════════════════

@router.message(Command("wallet"))
async def cmd_wallet(message: Message):
    """
    /wallet add АДРЕС ИМЯ — добавить кошелёк с именем контрагента
    /wallet list — список кошельков
    /wallet del АДРЕС — удалить
    """
    parts = message.text.split(maxsplit=3)
    chat_id = message.chat.id

    if len(parts) < 2:
        await message.reply(
            "<b>Команды кошелька:</b>\n"
            "<code>/wallet add АДРЕС ИМЯ</code> — добавить\n"
            "<code>/wallet list</code> — список\n"
            "<code>/wallet del АДРЕС</code> — удалить",
            parse_mode="HTML"
        )
        return

    sub = parts[1].lower()

    if sub == "add":
        if len(parts) < 4:
            await message.reply(
                "Формат: <code>/wallet add АДРЕС ИМЯ_КОНТРАГЕНТА</code>",
                parse_mode="HTML"
            )
            return
        address = parts[2].strip()
        name = parts[3].strip()

        if not (_is_tron_address(address) or _is_btc_address(address)):
            await message.reply("⚠️ Не похоже на BTC или USDT TRC20 адрес.")
            return

        await db.add_tracked_address(chat_id, address, name)
        network = "TRC20 (USDT)" if _is_tron_address(address) else "BTC"
        await message.reply(
            f"✅ Кошелёк добавлен:\n"
            f"Сеть: <b>{network}</b>\n"
            f"Адрес: <code>{address}</code>\n"
            f"Контрагент: <b>{name}</b>",
            parse_mode="HTML"
        )

    elif sub == "list":
        wallets = await db.get_tracked_wallets(chat_id)
        if not wallets:
            await message.reply(
                "Список пуст.\n<code>/wallet add АДРЕС ИМЯ</code>",
                parse_mode="HTML"
            )
            return
        lines = ["<b>📋 Кошельки:</b>\n"]
        for w in wallets:
            network = "TRC20" if _is_tron_address(w["address"]) else "BTC"
            lines.append(f"• <b>{w['name']}</b> [{network}]\n  <code>{w['address']}</code>")
        await message.reply("\n".join(lines), parse_mode="HTML")

    elif sub == "del":
        if len(parts) < 3:
            await message.reply("Укажите адрес: <code>/wallet del АДРЕС</code>", parse_mode="HTML")
            return
        address = parts[2].strip()
        await db.remove_tracked_address(chat_id, address)
        await message.reply(f"🗑 Кошелёк удалён: <code>{address}</code>", parse_mode="HTML")

    else:
        await message.reply("Неизвестная команда. Используй <code>/wallet</code>", parse_mode="HTML")


# Оставляем старые команды для совместимости
@router.message(Command("track"))
async def cmd_track(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply(
            "Формат: <code>/track АДРЕС</code>\n"
            "Или используй <code>/wallet add АДРЕС ИМЯ</code>",
            parse_mode="HTML"
        )
        return
    address = parts[1].strip()
    name = parts[2] if len(parts) > 2 else address[:8] + "..."
    await db.add_tracked_address(message.chat.id, address, name)
    await message.reply(
        f"✅ Адрес добавлен:\n<code>{address}</code>",
        parse_mode="HTML"
    )


@router.message(Command("untrack"))
async def cmd_untrack(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("Укажите адрес: <code>/untrack АДРЕС</code>", parse_mode="HTML")
        return
    await db.remove_tracked_address(message.chat.id, parts[1].strip())
    await message.reply(f"🗑 Удалено: <code>{parts[1].strip()}</code>", parse_mode="HTML")


@router.message(Command("address"))
async def cmd_address(message: Message):
    wallets = await db.get_tracked_wallets(message.chat.id)
    if not wallets:
        await message.reply(
            "Список пуст.\n<code>/wallet add АДРЕС ИМЯ</code>",
            parse_mode="HTML"
        )
        return
    lines = ["<b>📋 Отслеживаемые кошельки:</b>\n"]
    for w in wallets:
        network = "TRC20" if _is_tron_address(w["address"]) else "BTC"
        lines.append(f"• <b>{w['name']}</b> [{network}] <code>{w['address']}</code>")
    await message.reply("\n".join(lines), parse_mode="HTML")


# ════════════════════════════════════════════════════════════════════════════
#  ПОЛУЧЕНИЕ ТРАНЗАКЦИЙ
# ════════════════════════════════════════════════════════════════════════════

async def _fetch_trc20_txs(address: str) -> list[dict]:
    """Получает USDT TRC20 транзакции с Tronscan."""
    url = TRON_TRC20_API.format(address=address)
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("token_transfers", [])
    except Exception as e:
        logger.debug(f"Ошибка TRC20 API: {e}")
        return []


async def _fetch_btc_txs(address: str) -> list[dict]:
    url = BLOCKSTREAM_API.format(address=address)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                return await resp.json()
    except Exception as e:
        logger.debug(f"Ошибка BTC API: {e}")
        return []


# ════════════════════════════════════════════════════════════════════════════
#  ФОНОВЫЙ МОНИТОРИНГ
# ════════════════════════════════════════════════════════════════════════════

async def monitor_addresses(bot: Bot):
    logger.info("Запущен мониторинг кошельков")
    while True:
        try:
            tracked = await db.get_all_tracked()
            for chat_id, address, name in tracked:
                try:
                    if _is_tron_address(address):
                        await _check_trc20(bot, chat_id, address, name)
                    else:
                        await _check_btc(bot, chat_id, address, name)
                except Exception as e:
                    logger.debug(f"Ошибка проверки {address}: {e}")
        except Exception as e:
            logger.error(f"Ошибка мониторинга: {e}")

        await asyncio.sleep(60)


async def _check_trc20(bot: Bot, chat_id: int, address: str, name: str):
    txs = await _fetch_trc20_txs(address)
    if not txs:
        return

    latest_tx_id = txs[0].get("transaction_id", "")
    last_known = await db.get_last_tx(address)

    if last_known is None:
        await db.set_last_tx(address, latest_tx_id)
        return

    if latest_tx_id == last_known:
        return

    await db.set_last_tx(address, latest_tx_id)

    # Только входящие транзакции
    tx = txs[0]
    to_address = tx.get("to_address", "")
    if to_address.lower() != address.lower():
        return

    amount = float(tx.get("quant", 0)) / 1_000_000
    tx_id = tx.get("transaction_id", "")
    ts = tx.get("block_ts", 0) / 1000
    date_str = datetime.utcfromtimestamp(ts).strftime("%d-%m-%Y %H:%M:%S") if ts else ""
    from_addr = tx.get("from_address", "")

    # Автоматически обновляем баланс USDT в чате
    await db.update_balance(chat_id, "USDT", amount)
    new_balance = await db.get_balance(chat_id, "USDT")

    short_tx = tx_id[:5] + "..." + tx_id[-5:] if len(tx_id) > 10 else tx_id
    short_from = from_addr[:5] + "..." + from_addr[-5:] if len(from_addr) > 10 else from_addr
    short_to = address[:5] + "..." + address[-5:] if len(address) > 10 else address

    await bot.send_message(
        chat_id,
        f"🚀💸 <b>Account: {name}</b> 💸🚀\n"
        f"Income: {amount:,.2f}\n"
        f"/b usdt {amount:.2f}\n"
        f"/b usdt -{amount:.2f}\n"
        f"<b>#{name}</b>\n"
        f"⎯⎯⎯⎯⎯⎯ Transactions ⎯⎯⎯⎯⎯⎯\n"
        f"{short_tx} +{amount:,.2f} {date_str}\n"
        f"From: {short_from}\n"
        f"To: {short_to}\n"
        f"{amount:,.2f} USDT\n\n"
        f"Баланс: {new_balance:,.2f} USDT",
        parse_mode="HTML"
    )


async def _check_btc(bot: Bot, chat_id: int, address: str, name: str):
    txs = await _fetch_btc_txs(address)
    if not txs:
        return

    latest_tx_id = txs[0]["txid"]
    last_known = await db.get_last_tx(address)

    if last_known is None:
        await db.set_last_tx(address, latest_tx_id)
        return

    if latest_tx_id == last_known:
        return

    await db.set_last_tx(address, latest_tx_id)

    tx = txs[0]
    received = sum(
        o["value"] for o in tx.get("vout", [])
        if o.get("scriptpubkey_address") == address
    )
    spent = sum(
        i.get("prevout", {}).get("value", 0)
        for i in tx.get("vin", [])
        if i.get("prevout", {}).get("scriptpubkey_address") == address
    )
    delta_btc = (received - spent) / 1e8
    sign = "+" if delta_btc >= 0 else ""
    confirmed = tx.get("status", {}).get("confirmed", False)
    confirmations = "✅ подтверждено" if confirmed else "⏳ 0 подтверждений"

    await bot.send_message(
        chat_id,
        f"🔔 <b>{name}</b>\n"
        f"Адрес: <code>{address}</code>\n"
        f"{sign}{delta_btc:.8f} ฿\n"
        f"{confirmations}",
        parse_mode="HTML"
    )