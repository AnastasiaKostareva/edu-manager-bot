import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession

try:
    from aiogram.fsm.storage.redis import RedisStorage
except Exception:  # pragma: no cover
    RedisStorage = None

from dotenv import load_dotenv
from application.config import load_config
from infrastructure.telegram.handlers import main_router

def build_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    load_dotenv()
    config = load_config()

    token_bot = config.bot.token or os.getenv("TOKEN_BOT")
    if not token_bot:
        raise ValueError("TOKEN_BOT не найден в appsettings.yaml или .env файле")

    proxy_url = "http://vless-proxy:8080"
    session = AiohttpSession(proxy=proxy_url)

    redis_url = os.getenv("REDIS_URL")
    storage = (
        RedisStorage.from_url(redis_url)
        if redis_url and RedisStorage is not None
        else MemoryStorage()
    )

    bot = Bot(token=token_bot, session=session)
    dp = Dispatcher(storage=storage)
    dp.include_router(main_router)
    
    return bot, dp