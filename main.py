import asyncio
import logging

from infrastructure.database.db_config import init_db, close_db
from infrastructure.telegram.bot import build_bot_and_dispatcher
from infrastructure.monitoring.scheduler import Scheduler
from infrastructure.monitoring.notification_worker import NotificationWorker


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot, dp = build_bot_and_dispatcher()


async def main():
    await init_db()
    logger.info("База данных подключена")

    scheduler = Scheduler(bot)
    await scheduler.start()

    # отдельный воркер для напоминаний (проверяет pending reminders каждую минуту)
    notification_worker = NotificationWorker(bot)
    await notification_worker.start()

    try:
        logger.info("Бот запущен")
        await dp.start_polling(bot)
    finally:
        await notification_worker.stop()
        await scheduler.stop()
        await close_db()
        logger.info("База данных отключена")

if __name__ == "__main__":
    asyncio.run(main())