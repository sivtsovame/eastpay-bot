import logging
import asyncio
import aiohttp
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message
from database import db

logger = logging.getLogger(__name__)
router = Router()

BLOCKSTREAM_API = "https://blockstream.info/api/address/{address}/txs"


@router.message(Command("track"))
async def cmd_track(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply(
            "Укажите адрес:\n<code>/track 1MxcwUAQKRgheTxgNphKVRmBzXxVXM6Ea2</code>",
            parse_mode="HTML"
        )
        return

    address = parts[1].strip()
    chat_id = message.chat.id

    # Простая валидация BTC-адреса
    if not (25 <= len(address) <= 62 and address[0] in "13bc"):
        await message.reply("⚠️ Похоже это не BTC-адрес. Проверьте и попробуйте снова.")
        return

    await db.add_tracked_address(chat_id, address)
    await message.reply(
        f"✅ Адрес добавлен в мониторинг:\n<code>{address}</code>",
        parse_mode="HTML"
    )


@router.message(Command("untrack"))
async def cmd_untrack(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("Укажите адрес: <code>/untrack АДРЕС</code>", parse_mode="HTML")
        return
    address = parts[1].strip()
    await db.remove_tracked_address(message.chat.id, address)
    await message.reply(f"🗑 Адрес удалён из мониторинга:\n<code>{address}</code>", parse_mode="HTML")


@router.message(Command("address"))
async def cmd_address(message: Message):
    addresses = await db.get_tracked_addresses(message.chat.id)
    if not addresses:
        await message.reply(
            "Список пуст. Добавьте адрес:\n<code>/track АДРЕС</code>",
            parse_mode="HTML"
        )
        return
    lines = ["<b>📋 Отслеживаемые адреса:</b>\n"]
    for addr in addresses:
        lines.append(f"• <code>{addr}</code>")
    await message.reply("\n".join(lines), parse_mode="HTML")


# ── Фоновый мониторинг ───────────────────────────────────────────────────────

async def _fetch_txs(address: str) -> list[dict]:
    url = BLOCKSTREAM_API.format(address=address)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return []
            return await resp.json()


async def monitor_addresses(bot: Bot):
    """
    Фоновая задача: каждые 60 секунд проверяет все отслеживаемые адреса.
    Если появилась новая транзакция — отправляет уведомление.
    """
    logger.info("Запущен мониторинг BTC-адресов")
    while True:
        try:
            tracked = await db.get_all_tracked()
            for chat_id, address in tracked:
                try:
                    txs = await _fetch_txs(address)
                    if not txs:
                        continue

                    latest_tx_id = txs[0]["txid"]
                    last_known = await db.get_last_tx(address)

                    if last_known is None:
                        # Первая проверка — запоминаем, не уведомляем
                        await db.set_last_tx(address, latest_tx_id)
                        continue

                    if latest_tx_id == last_known:
                        continue  # новых транзакций нет

                    # Есть новые транзакции
                    await db.set_last_tx(address, latest_tx_id)

                    tx = txs[0]
                    # Считаем нетто-изменение баланса для адреса
                    received = sum(
                        o["value"] for o in tx.get("vout", [])
                        if any(addr == address for addr in o.get("scriptpubkey_address", [address]) if addr)
                    )
                    spent = sum(
                        inp.get("prevout", {}).get("value", 0)
                        for inp in tx.get("vin", [])
                        if inp.get("prevout", {}).get("scriptpubkey_address") == address
                    )
                    delta_sat = received - spent
                    delta_btc = delta_sat / 1e8
                    sign = "+" if delta_btc >= 0 else ""
                    confirmed = tx.get("status", {}).get("confirmed", False)
                    confirmations = "✅ подтверждено" if confirmed else "⏳ 0 подтверждений"

                    await bot.send_message(
                        chat_id,
                        f"🔔 <b>Транзакция</b>\n"
                        f"Адрес: <code>{address}</code>\n"
                        f"{'→' if delta_btc < 0 else '<-'} {sign}{delta_btc:.8f} ฿\n"
                        f"{confirmations}",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.debug(f"Ошибка проверки {address}: {e}")

        except Exception as e:
            logger.error(f"Ошибка в monitor_addresses: {e}")

        await asyncio.sleep(60)
