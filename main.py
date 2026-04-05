import asyncio
import os
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from application.config import load_config
from infrastructure.database.db_config import init_db, close_db
from infrastructure.telegram.handlers import router
from infrastructure.monitoring.scheduler import Scheduler


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
config = load_config()

TOKEN_BOT = config.bot.token or os.getenv("TOKEN_BOT")
if not TOKEN_BOT:
    raise ValueError("TOKEN_BOT не найден в appsettings.yaml или .env файле")

storage = MemoryStorage()
bot = Bot(token=TOKEN_BOT)
dp = Dispatcher(storage=storage)

dp.include_router(router)


async def main():
    await init_db()
    logger.info("База данных подключена")

    scheduler = Scheduler(bot)
    await scheduler.start()

    try:
        logger.info("Бот запущен")
        await dp.start_polling(bot)
    finally:
        await scheduler.stop()
        await close_db()
        logger.info("База данных отключена")

if __name__ == "__main__":
    asyncio.run(main())