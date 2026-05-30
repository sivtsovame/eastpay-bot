import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, BotCommand

from config import BOT_TOKEN
from database.db import init_db
from handlers import calculator, balance, tracking, deals, formulas

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
BotCommand

async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start",    description="Начать работу / справка"),
        BotCommand(command="b",        description="Баланс: /b или /b usd 100"),
        BotCommand(command="balance_stat", description="Полная статистика балансов"),
        BotCommand(command="deal",     description="Создать сделку"),
        BotCommand(command="deals",    description="Последние сделки"),
        BotCommand(command="rates",    description="Текущие курсы валют"),
        BotCommand(command="setrate",  description="(Админ) Задать курс: /setrate JPY transfer 155.21"),
        BotCommand(command="formula",  description="Личные формулы для инлайн-калькулятора"),
        BotCommand(command="track",    description="Отслеживать BTC-адрес"),
        BotCommand(command="untrack",  description="Удалить адрес из мониторинга"),
        BotCommand(command="address",  description="Список отслеживаемых адресов"),
        BotCommand(command="roll", description="Случайное число: /roll 100"),
    ]
    await bot.set_my_commands(commands)


async def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Вставь токен бота в config.py или переменную окружения BOT_TOKEN!")
        return

    # Инициализация БД
    await init_db()
    logger.info("База данных инициализирована")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Регистрируем роутеры
    dp.include_router(calculator.router)   # инлайн — первым!
    dp.include_router(balance.router)
    dp.include_router(tracking.router)
    dp.include_router(deals.router)
    dp.include_router(formulas.router)

    # /start
    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        await message.reply(
            "<b>👋 Привет! Я EAST PAY бот.</b>\n\n"
            "<b>Инлайн-калькулятор:</b>\n"
            "В любом чате: <code>@botname (3511*95)+55</code>\n"
            "Курс Garantex: <code>@botname garus</code>\n"
            "С процентами: <code>@botname garus+1%+0.5%</code>\n\n"
            "<b>Основные команды:</b>\n"
            "/b — балансы\n"
            "/deal — создать сделку\n"
            "/deals — реестр сделок\n"
            "/rates — курсы валют\n"
            "/formula — личные формулы\n"
            "/track — мониторинг BTC\n"
            "/address — список кошельков\n\n"
            "<b>Для администраторов:</b>\n"
            "/setrate JPY transfer 155.21",
            parse_mode="HTML"
        )

    await set_commands(bot)

    # Запускаем фоновый мониторинг BTC-адресов
    asyncio.create_task(tracking.monitor_addresses(bot))
    logger.info("Фоновый мониторинг BTC запущен")

    logger.info("Бот запущен. Нажми Ctrl+C для остановки.")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
