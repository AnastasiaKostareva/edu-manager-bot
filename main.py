import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from infrastructure.database.db_config import init_db, close_db


load_dotenv()
TOKEN_BOT = os.getenv("TOKEN_BOT")

if not TOKEN_BOT:
    raise ValueError("TOKEN_BOT не найден в .env файле")

bot = Bot(token=TOKEN_BOT)
dp = Dispatcher()

async def main():
    await init_db()
    print("База данных подключена")
    
    try:
        print("Бот запущен")
        await dp.start_polling(bot)
    finally:
        await close_db()
        print("База данных отключена")

if __name__ == "__main__":
    asyncio.run(main())