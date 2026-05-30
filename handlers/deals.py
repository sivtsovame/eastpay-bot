import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import db
from services.garantex import fetch_garus
from services.sheets import append_deal_to_sheet
from config import CITY_RATES, COMPANY_PROFIT, ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()


# ════════════════════════════════════════════════════════════════════════════
#  FSM — состояния для создания сделки
# ════════════════════════════════════════════════════════════════════════════

class DealFSM(StatesGroup):
    choose_currency     = State()
    choose_type         = State()   # наличные / безнал
    choose_city         = State()   # город приёма рублей
    enter_amount        = State()   # сумма в иностранной валюте
    confirm             = State()


class RateFSM(StatesGroup):
    """Для администраторов: внесение курса валюты."""
    enter_currency = State()
    enter_type     = State()
    enter_rate     = State()


# ════════════════════════════════════════════════════════════════════════════
#  КОМАНДЫ АДМИНИСТРАТОРА
# ════════════════════════════════════════════════════════════════════════════

@router.message(Command("setrate"))
async def cmd_setrate(message: Message, state: FSMContext):
    """Администратор вносит курс: /setrate JPY transfer 155.21"""
    if message.from_user.id not in ADMIN_IDS and ADMIN_IDS:
        await message.reply("⛔ Только для администраторов.")
        return

    parts = message.text.split()
    # /setrate JPY transfer 155.21  — всё в одной строке
    if len(parts) == 4:
        currency, type_, rate_str = parts[1], parts[2], parts[3]
        if type_ not in ("cash", "transfer", "нал", "безнал"):
            await message.reply("Тип: <code>cash</code> или <code>transfer</code>", parse_mode="HTML")
            return
        type_ = "cash" if type_ in ("cash", "нал") else "transfer"
        try:
            rate = float(rate_str.replace(",", "."))
        except ValueError:
            await message.reply("Курс должен быть числом.")
            return
        await db.set_currency_rate(currency, type_, rate, message.from_user.id)
        await message.reply(
            f"✅ Курс сохранён:\n"
            f"<b>{currency.upper()}</b> ({'нал' if type_ == 'cash' else 'безнал'}) = {rate}",
            parse_mode="HTML"
        )
        return

    await message.reply(
        "Формат: <code>/setrate JPY transfer 155.21</code>\n"
        "Типы: <code>cash</code> (наличные) / <code>transfer</code> (безнал)",
        parse_mode="HTML"
    )


@router.message(Command("rates"))
async def cmd_rates(message: Message):
    """Показать все установленные курсы."""
    rates = await db.get_all_currency_rates()
    if not rates:
        await message.reply(
            "Курсы не заданы. Добавьте:\n<code>/setrate JPY transfer 155.21</code>",
            parse_mode="HTML"
        )
        return
    lines = ["<b>📋 Текущие курсы валют:</b>\n"]
    for r in rates:
        type_str = "нал" if r["type"] == "cash" else "безнал"
        lines.append(f"• <b>{r['currency']}</b> [{type_str}] = {r['rate']} — обновлён {r['updated_at'][:16]}")
    await message.reply("\n".join(lines), parse_mode="HTML")


# ════════════════════════════════════════════════════════════════════════════
#  СОЗДАНИЕ СДЕЛКИ — /deal
# ════════════════════════════════════════════════════════════════════════════

@router.message(Command("deal"))
async def cmd_deal(message: Message, state: FSMContext):
    rates = await db.get_all_currency_rates()
    if not rates:
        await message.reply(
            "⚠️ Курсы валют ещё не заданы. Обратитесь к администратору.",
        )
        return

    # Уникальные валюты
    currencies = sorted(set(r["currency"] for r in rates))
    builder = InlineKeyboardBuilder()
    for cur in currencies:
        builder.button(text=cur, callback_data=f"deal_cur:{cur}")
    builder.adjust(3)

    await state.set_state(DealFSM.choose_currency)
    await message.reply("💱 Выберите валюту получения:", reply_markup=builder.as_markup())


@router.callback_query(DealFSM.choose_currency, F.data.startswith("deal_cur:"))
async def deal_choose_currency(cb: CallbackQuery, state: FSMContext):
    currency = cb.data.split(":")[1]
    await state.update_data(currency=currency)

    # Проверяем доступные типы для этой валюты
    cash_rate   = await db.get_currency_rate(currency, "cash")
    trans_rate  = await db.get_currency_rate(currency, "transfer")

    builder = InlineKeyboardBuilder()
    if trans_rate is not None:
        builder.button(text=f"💳 Безналичный (курс {trans_rate})", callback_data="deal_type:transfer")
    if cash_rate is not None:
        builder.button(text=f"💵 Наличный (курс {cash_rate})", callback_data="deal_type:cash")
    builder.adjust(1)

    await state.set_state(DealFSM.choose_type)
    await cb.message.edit_text(f"<b>{currency}</b> — выберите тип:", reply_markup=builder.as_markup(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(DealFSM.choose_type, F.data.startswith("deal_type:"))
async def deal_choose_type(cb: CallbackQuery, state: FSMContext):
    type_ = cb.data.split(":")[1]
    await state.update_data(currency_type=type_)

    # Выбор города
    builder = InlineKeyboardBuilder()
    for city, rate in CITY_RATES.items():
        builder.button(text=f"{city.capitalize()} (+{rate}%)", callback_data=f"deal_city:{city}")
    builder.adjust(2)

    await state.set_state(DealFSM.choose_city)
    await cb.message.edit_text("🏙 Город приёма рублей:", reply_markup=builder.as_markup())
    await cb.answer()


@router.callback_query(DealFSM.choose_city, F.data.startswith("deal_city:"))
async def deal_choose_city(cb: CallbackQuery, state: FSMContext):
    city = cb.data.split(":")[1]
    await state.update_data(city=city)

    data = await state.get_data()
    currency = data["currency"]
    currency_type = data["currency_type"]
    city_rate_pct = CITY_RATES.get(city, 0.5)

    # Показываем предварительный курс
    garus = await fetch_garus()
    fx_rate = await db.get_currency_rate(currency, currency_type)
    # Формула: ((garus * (1 + city_rate/100)) / fx_rate) * (1 + profit/100)
    calc_rate = ((garus * (1 + city_rate_pct / 100)) / fx_rate) * (1 + COMPANY_PROFIT / 100)

    await state.update_data(calc_rate=round(calc_rate, 6), garus=garus, fx_rate=fx_rate)
    await state.set_state(DealFSM.enter_amount)

    type_str = "безнал" if currency_type == "transfer" else "нал"
    await cb.message.edit_text(
        f"<b>Параметры сделки:</b>\n"
        f"Валюта: <b>{currency}</b> [{type_str}]\n"
        f"Город: <b>{city.capitalize()}</b>\n"
        f"GARUS: <b>{garus}</b>\n"
        f"Курс {currency}: <b>{fx_rate}</b>\n"
        f"Расчётный курс: <b>{calc_rate:.6f}</b> руб/{currency}\n\n"
        f"Введите сумму <b>{currency}</b> к получению клиентом:",
        parse_mode="HTML"
    )
    await cb.answer()


@router.message(DealFSM.enter_amount)
async def deal_enter_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").replace(" ", "").replace("_", ""))
    except ValueError:
        await message.reply("Введите число, например: <code>10000000</code>", parse_mode="HTML")
        return

    data = await state.get_data()
    calc_rate = data["calc_rate"]
    currency   = data["currency"]
    currency_type = data["currency_type"]
    city       = data["city"]

    amount_rub = round(amount * calc_rate)
    type_str = "Безналичный перевод" if currency_type == "transfer" else "Наличные"

    await state.update_data(amount_foreign=amount, amount_rub=amount_rub)

    # Предпросмотр заявки
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="deal_confirm:yes")
    builder.button(text="❌ Отменить",    callback_data="deal_confirm:no")
    builder.adjust(2)

    await state.set_state(DealFSM.confirm)
    await message.reply(
        f"📋 <b>Предварительная заявка:</b>\n\n"
        f"Город приёма рублей: <b>{city.capitalize()}</b>\n"
        f"Валюта получения: <b>{currency}</b>\n"
        f"Тип валюты: <b>{type_str}</b>\n"
        f"Сумма валюты к получению: <b>{_fmt(amount)} {currency}</b>\n"
        f"Сумма рублей к оплате: <b>{_fmt(amount_rub)} ₽</b>\n"
        f"Курс: <b>{calc_rate:.6f}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(DealFSM.confirm, F.data.startswith("deal_confirm:"))
async def deal_confirm(cb: CallbackQuery, state: FSMContext):
    answer = cb.data.split(":")[1]

    if answer == "no":
        await state.clear()
        await cb.message.edit_text("❌ Сделка отменена.")
        await cb.answer()
        return

    data = await state.get_data()
    user = cb.from_user
    manager_name = user.full_name or user.username or str(user.id)

    deal_id = await db.create_deal(
        manager_id=user.id,
        manager_name=manager_name,
        chat_id=cb.message.chat.id,
        currency=data["currency"],
        currency_type=data["currency_type"],
        city=data["city"],
        amount_foreign=data["amount_foreign"],
        amount_rub=data["amount_rub"],
        rate_used=data["calc_rate"],
    )

    deal = await db.get_deal(deal_id)
    # Записываем в Google Sheets
    await append_deal_to_sheet(deal)

    type_str = "Безналичный перевод" if data["currency_type"] == "transfer" else "Наличные"

    # Кнопки для клиента (принять/отклонить)
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять",   callback_data=f"client_deal:accept:{deal_id}")
    builder.button(text="❌ Отклонить", callback_data=f"client_deal:reject:{deal_id}")
    builder.adjust(2)

    await state.clear()
    await cb.message.edit_text(
        f"✅ <b>Заявка #{deal_id}</b>\n\n"
        f"Город приёма рублей: <b>{data['city'].capitalize()}</b>\n"
        f"Валюта получения: <b>{data['currency']}</b>\n"
        f"Тип валюты: <b>{type_str}</b>\n"
        f"Сумма валюты к получению: <b>{_fmt(data['amount_foreign'])} {data['currency']}</b>\n"
        f"Сумма рублей к оплате: <b>{_fmt(data['amount_rub'])} ₽</b>\n\n"
        f"Менеджер: {manager_name}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await cb.answer("Заявка создана!")


@router.callback_query(F.data.startswith("client_deal:"))
async def client_deal_response(cb: CallbackQuery):
    _, action, deal_id_str = cb.data.split(":")
    deal_id = int(deal_id_str)
    deal = await db.get_deal(deal_id)

    if not deal:
        await cb.answer("Заявка не найдена.")
        return
    if deal["status"] != "pending":
        await cb.answer(f"Заявка уже обработана: {deal['status']}")
        return

    status = "accepted" if action == "accept" else "rejected"
    await db.update_deal_status(deal_id, status)

    emoji = "✅" if status == "accepted" else "❌"
    status_str = "принята" if status == "accepted" else "отклонена"

    user = cb.from_user
    await cb.message.edit_text(
        cb.message.text + f"\n\n{emoji} Заявка <b>{status_str}</b> — {user.full_name}",
        parse_mode="HTML"
    )
    await cb.answer(f"Заявка {status_str}!")


@router.message(Command("deals"))
async def cmd_deals(message: Message):
    """Последние 10 сделок в чате."""
    # Простой запрос — добавим прямо здесь
    import aiosqlite, os
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "eastpay.db")
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("""
            SELECT id, manager_name, currency, currency_type, city,
                   amount_foreign, amount_rub, status, created_at
            FROM deals WHERE chat_id=?
            ORDER BY id DESC LIMIT 10
        """, (message.chat.id,)) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    if not rows:
        await message.reply("Сделок пока нет. Создайте: /deal")
        return

    lines = ["<b>📋 Последние сделки:</b>\n"]
    status_emoji = {"pending": "⏳", "accepted": "✅", "rejected": "❌"}
    for r in rows:
        em = status_emoji.get(r["status"], "?")
        type_str = "безнал" if r["currency_type"] == "transfer" else "нал"
        lines.append(
            f"{em} <b>#{r['id']}</b> {r['currency']} [{type_str}] | "
            f"{_fmt(r['amount_foreign'])} → {_fmt(r['amount_rub'])} ₽ | "
            f"{r['city']} | {r['manager_name']} | {r['created_at'][:10]}"
        )

    await message.reply("\n".join(lines), parse_mode="HTML")


# ── Утилита ──────────────────────────────────────────────────────────────────

def _fmt(n: float) -> str:
    if n is None:
        return "0"
    if n == int(n):
        return f"{int(n):,}".replace(",", " ")
    return f"{n:,.2f}".replace(",", " ")
