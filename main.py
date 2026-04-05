import asyncio
import logging

from infrastructure.database.db_config import init_db, close_db
from infrastructure.telegram.bot import build_bot_and_dispatcher
from infrastructure.monitoring.scheduler import Scheduler


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot, dp = build_bot_and_dispatcher()


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