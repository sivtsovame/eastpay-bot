from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from database import db

router = Router()


@router.message(Command("formula"))
async def cmd_formula(message: Message):
    """
    /formula — список формул
    /formula buy ur-1.5%   — создать/обновить
    /formula del buy       — удалить
    """
    parts = message.text.split(maxsplit=2)
    user_id = message.from_user.id

    # /formula — показать все
    if len(parts) == 1:
        formulas = await db.get_all_formulas(user_id)
        if not formulas:
            await message.reply(
                "У вас нет личных формул.\n"
                "Создайте: <code>/formula buy garus-1.5%</code>",
                parse_mode="HTML"
            )
            return
        lines = ["<b>📌 Ваши формулы:</b>\n"]
        for f in formulas:
            lines.append(f"• <code>{f['shortcut']}</code> → <code>{f['formula']}</code>")
        lines.append("\nИспользование в инлайн: <code>@botname buy</code>")
        await message.reply("\n".join(lines), parse_mode="HTML")
        return

    sub = parts[1].lower()

    # /formula del shortcut
    if sub == "del" and len(parts) == 3:
        shortcut = parts[2].strip().lower()
        await db.delete_formula(user_id, shortcut)
        await message.reply(f"🗑 Формула <code>{shortcut}</code> удалена.", parse_mode="HTML")
        return

    # /formula shortcut formula
    if len(parts) == 3:
        shortcut = parts[1].strip().lower()
        formula  = parts[2].strip()
        await db.save_formula(user_id, shortcut, formula)
        await message.reply(
            f"✅ Формула сохранена:\n"
            f"<code>{shortcut}</code> → <code>{formula}</code>",
            parse_mode="HTML"
        )
        return

    await message.reply(
        "Формат:\n"
        "<code>/formula buy garus-1.5%</code> — создать\n"
        "<code>/formula del buy</code> — удалить\n"
        "<code>/formula</code> — список",
        parse_mode="HTML"
    )
