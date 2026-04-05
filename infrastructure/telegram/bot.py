
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from application.config import load_config
from infrastructure.telegram.handlers import router


def build_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    load_dotenv()
    config = load_config()

    token_bot = config.bot.token or os.getenv("TOKEN_BOT")
    if not token_bot:
        raise ValueError("TOKEN_BOT не найден в appsettings.yaml или .env файле")

    storage = MemoryStorage()
    bot = Bot(token=token_bot)
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    return bot, dp
