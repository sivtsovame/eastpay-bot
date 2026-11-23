import asyncio
import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, LinkPreviewOptions
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database import zdb
from handlers.balance import _eval_amount

logger = logging.getLogger(__name__)
router = Router()

VLAT = ZoneInfo("Asia/Vladivostok")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
REMINDER_HOURS = (10, 19)   # время рассылки по Владивостоку


# ── Форматирование ───────────────────────────────────────────────────────────

def fmt_amount(n: float) -> str:
    if n == int(n):
        return f"{int(n):,}".replace(",", "'")
    return f"{n:,.2f}".replace(",", "'")


def msg_link(chat_id: int, message_id: int) -> str | None:
    s = str(chat_id)
    if s.startswith("-100") and message_id:
        return f"https://t.me/c/{s[4:]}/{message_id}"
    return None


def fmt_line(r: dict) -> str:
    emoji = {"open": "🔴", "done": "🟢", "cancelled": "⚫️"}.get(r["status"], "🔴")
    link = msg_link(r["chat_id"], r["message_id"])
    label = f'<a href="{link}">{r["label"]}</a>' if link else r["label"]
    return (f"{emoji} <b>Заявка {label}</b> — "
            f"{fmt_amount(r['amount'])} {r['currency']} · {html.escape(r['client'])}")


def build_chunks(title: str, lines: list[str], empty: str) -> list[str]:
    """Режет длинный список на сообщения (лимит Telegram — 4096 символов)."""
    if not lines:
        return [f"{title}\n\n{empty}"]
    chunks, cur = [], title + "\n"
    for ln in lines:
        if len(cur) + len(ln) + 1 > 3800:
            chunks.append(cur.strip())
            cur = ""
        cur += "\n" + ln
    chunks.append(cur.strip())
    return chunks


async def _can_act(cb: CallbackQuery, creator_id: int) -> bool:
    uid = cb.from_user.id
    if uid == creator_id or uid in ADMIN_IDS:
        return True
    try:
        member = await cb.bot.get_chat_member(cb.message.chat.id, uid)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def _who(user) -> str:
    return f"@{user.username}" if user.username else user.full_name


# ── /z — новая заявка ────────────────────────────────────────────────────────

@router.message(Command("z"))
async def cmd_z(message: Message):
    await zdb.touch_chat(message.chat.id, message.chat.title or "Личный чат")

    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 4:
        await message.reply(
            "Формат: <code>/z usd 100000 алексей</code>\n"
            "валюта · сумма (без пробелов, можно формулу) · клиент",
            parse_mode="HTML",
        )
        return

    currency = parts[1].upper()
    try:
        amount = _eval_amount(parts[2])
    except Exception:
        await message.reply("⚠️ Не удалось распознать сумму. Пример: <code>/z usd 100000 алексей</code>",
                            parse_mode="HTML")
        return
    if amount <= 0:
        await message.reply("⚠️ Сумма должна быть больше нуля.")
        return
    client = parts[3].strip().splitlines()[0][:100]

    num = await zdb.next_num(message.chat.id)
    now = datetime.now(VLAT)
    label = f"№{num}-{now.strftime('%d.%m')}"
    who = _who(message.from_user)

    req_id = await zdb.create_request(
        message.chat.id, num, label, currency, amount, client,
        message.from_user.id, who,
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Исполнено", callback_data=f"zdone:{req_id}")
    builder.button(text="❌ Отменить", callback_data=f"zcancel:{req_id}")
    builder.adjust(2)

    sent = await message.reply(
        f"🔴 <b>Заявка {label}</b>\n"
        f"Сумма: {fmt_amount(amount)} {currency}\n"
        f"Клиент: {html.escape(client)}\n"
        f"Создал: {html.escape(who)}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await zdb.set_message_id(req_id, sent.message_id)


# ── Кнопки «Исполнено» / «Отменить» ──────────────────────────────────────────

async def _close(cb: CallbackQuery, status: str):
    req_id = int(cb.data.split(":")[1])
    req = await zdb.get_request(req_id)
    if not req:
        await cb.answer("Заявка не найдена.", show_alert=True)
        return
    if req["status"] != "open":
        await cb.answer("Заявка уже закрыта.", show_alert=True)
        return
    if not await _can_act(cb, req["creator_id"]):
        await cb.answer("⛔ Закрыть может создатель заявки или админ группы.", show_alert=True)
        return

    who = _who(cb.from_user)
    if not await zdb.set_status(req_id, status, who):
        await cb.answer("Заявка уже закрыта.", show_alert=True)
        return

    if status == "done":
        emoji, tail = "🟢", f"✅ Исполнено: {html.escape(who)}"
    else:
        emoji, tail = "⚫️", f"❌ Отменено: {html.escape(who)}"

    text = (cb.message.html_text or "").replace("🔴", emoji, 1)
    await cb.message.edit_text(f"{text}\n\n{tail}", parse_mode="HTML")
    await cb.answer("Готово!")


@router.callback_query(F.data.startswith("zdone:"))
async def z_done(cb: CallbackQuery):
    await _close(cb, "done")


@router.callback_query(F.data.startswith("zcancel:"))
async def z_cancel(cb: CallbackQuery):
    await _close(cb, "cancelled")


# ── /zlist и /zlistcomp ──────────────────────────────────────────────────────
# ── Хаб ALL PAYMENTS: сводка по всем группам ─────────────────────────────────

def totals_lines(rows: list[dict]) -> list[str]:
    sums: dict[str, float] = {}
    for r in rows:
        sums[r["currency"]] = sums.get(r["currency"], 0) + r["amount"]
    lines = ["", "<b>Итого:</b>"]
    for cur in sorted(sums):
        lines.append(f"Общее количество {cur}: {fmt_amount(sums[cur])}")
    return lines


async def hub_chunks(status: str, limit: int | None = None) -> list[str]:
    rows = await zdb.list_all(status, limit)
    if status == "open":
        head = f"📋 <b>ALL PAYMENTS — неисполненные заявки: {len(rows)}</b>"
        empty = "Нет активных заявок ✅"
    else:
        head = f"✅ <b>ALL PAYMENTS — исполненные (последние {len(rows)})</b>"
        empty = "Исполненных заявок пока нет."

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["chat_title"], []).append(r)

    lines = []
    for title, items in groups.items():
        lines.append(f"\n📁 <b>{html.escape(title)}</b> — {len(items)}")
        lines.extend(fmt_line(r) for r in items)
    if rows and status == "open":
        lines.extend(totals_lines(rows))
    return build_chunks(head, lines, empty)


async def _is_hub(chat_id: int) -> bool:
    return (await zdb.get_hub()) == chat_id


@router.message(Command("zhub"))
async def cmd_zhub(message: Message):
    """/zhub — назначить этот чат сводным (ALL PAYMENTS). /zhub off — снять."""
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔ Только для администраторов бота.")
        return
    if "off" in (message.text or "").lower():
        await zdb.set_hub(None)
        await message.reply("Сводный чат отключён.")
        return
    await zdb.touch_chat(message.chat.id, message.chat.title or "Личный чат")
    await zdb.set_hub(message.chat.id)
    await message.reply(
        "✅ Этот чат теперь сводный (ALL PAYMENTS).\n"
        "Здесь <code>/zlist</code> показывает заявки всех групп с итогами, "
        "и сюда приходит общая рассылка в 10:00 и 19:00.",
        parse_mode="HTML",
    )


# ── /zlist и /zlistcomp ──────────────────────────────────────────────────────

@router.message(Command("zlist"))
async def cmd_zlist(message: Message):
    await zdb.touch_chat(message.chat.id, message.chat.title or "Личный чат")
    if await _is_hub(message.chat.id):
        chunks = await hub_chunks("open")
    else:
        rows = await zdb.list_requests(message.chat.id, "open")
        title = f"📋 <b>Неисполненные заявки: {len(rows)}</b>"
        chunks = build_chunks(title, [fmt_line(r) for r in rows], "Нет активных заявок ✅")
    for chunk in chunks:
        await message.reply(chunk, parse_mode="HTML", link_preview_options=NO_PREVIEW)


@router.message(Command("zlistcomp"))
async def cmd_zlistcomp(message: Message):
    await zdb.touch_chat(message.chat.id, message.chat.title or "Личный чат")
    if await _is_hub(message.chat.id):
        chunks = await hub_chunks("done", limit=100)
    else:
        rows = await zdb.list_requests(message.chat.id, "done", limit=50)
        title = f"✅ <b>Исполненные заявки (последние {len(rows)})</b>"
        chunks = build_chunks(title, [fmt_line(r) for r in rows], "Исполненных заявок пока нет.")
    for chunk in chunks:
        await message.reply(chunk, parse_mode="HTML", link_preview_options=NO_PREVIEW)

# ── /zall — общий реестр по всем группам (только админы бота) ────────────────

@router.message(Command("zall"))
async def cmd_zall(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔ Только для администраторов бота.")
        return

    done = "done" in (message.text or "").lower()
    status = "done" if done else "open"
    rows = await zdb.list_all(status, limit=100 if done else None)

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["chat_title"], []).append(r)

    lines = []
    for title, items in groups.items():
        lines.append(f"\n📁 <b>{html.escape(title)}</b> — {len(items)}")
        lines.extend(fmt_line(r) for r in items)

    head = ("✅ <b>Общий реестр: исполненные (последние 100)</b>" if done
            else f"📋 <b>Общий реестр: неисполненные ({len(rows)})</b>")
    for chunk in build_chunks(head, lines, "Заявок нет."):
        await message.reply(chunk, parse_mode="HTML", link_preview_options=NO_PREVIEW)


# ── Напоминания в 10:00 и 19:00 по Владивостоку ──────────────────────────────

async def _reminder_texts(chat_id: int) -> list[str]:
    rows = await zdb.list_requests(chat_id, "open")
    if not rows:
        return ["⏰ Нет активных заявок"]
    title = f"⏰ <b>Незакрытые заявки: {len(rows)}</b>"
    return build_chunks(title, [fmt_line(r) for r in rows], "")


@router.message(Command("zremind"))
async def cmd_zremind(message: Message):
    """Тест: показать напоминание в этом чате прямо сейчас (только админы бота)."""
    if message.from_user.id not in ADMIN_IDS:
        return
    if await _is_hub(message.chat.id):
        texts = await hub_chunks("open")
    else:
        texts = await _reminder_texts(message.chat.id)
    for text in texts:
        await message.answer(text, parse_mode="HTML", link_preview_options=NO_PREVIEW)


async def _broadcast(bot: Bot):
    hub = await zdb.get_hub()

    # 1) Группы: каждая получает только свои незакрытые заявки
    for chat_id, title in await zdb.get_chats():
        if chat_id == hub:
            continue
        try:
            rows = await zdb.list_requests(chat_id, "open")
            if not rows:
                continue
            for text in await _reminder_texts(chat_id):
                await bot.send_message(chat_id, text, parse_mode="HTML",
                                       link_preview_options=NO_PREVIEW)
        except Exception as e:
            logger.warning(f"Не удалось отправить напоминание в {chat_id} ({title}): {e}")
        await asyncio.sleep(0.2)

    # 2) ALL PAYMENTS: все заявки всех групп и итоги
    if hub:
        try:
            if await zdb.list_all("open"):
                for text in await hub_chunks("open"):
                    await bot.send_message(hub, text, parse_mode="HTML",
                                           link_preview_options=NO_PREVIEW)
        except Exception as e:
            logger.warning(f"Не удалось отправить сводку в хаб {hub}: {e}")

async def _broadcast(bot: Bot):
    for chat_id, title in await zdb.get_chats():
        try:
            rows = await zdb.list_requests(chat_id, "open")
            if not rows:
                continue  # нет незакрытых заявок: ничего не отправляем
            for text in await _reminder_texts(chat_id):
                await bot.send_message(chat_id, text, parse_mode="HTML",
                                       link_preview_options=NO_PREVIEW)
        except Exception as e:
            logger.warning(f"Не удалось отправить напоминание в {chat_id} ({title}): {e}")
        await asyncio.sleep(0.2)


async def reminders_loop(bot: Bot):
    logger.info("Запущены напоминания о заявках (10:00 и 19:00 VLAT)")
    sent: set = set()
    while True:
        try:
            now = datetime.now(VLAT)
            slot = (now.date(), now.hour)
            if now.hour in REMINDER_HOURS and now.minute < 3 and slot not in sent:
                sent.add(slot)
                await _broadcast(bot)
                sent = {s for s in sent if s[0] == now.date()}
        except Exception as e:
            logger.error(f"Ошибка в reminders_loop: {e}")
        await asyncio.sleep(20)

        