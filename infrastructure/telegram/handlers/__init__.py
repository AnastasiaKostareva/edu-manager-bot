"""
Telegram handlers package.
Собирает все роутеры в один main_router.
"""
from aiogram import Router

from infrastructure.telegram.handlers.private import router as private_router
from infrastructure.telegram.handlers.group import router as group_router
from infrastructure.telegram.handlers.callbacks import router as callbacks_router

main_router = Router()

# Порядок важен: сначала группа/личка, потом общие колбеки
main_router.include_router(private_router)
main_router.include_router(group_router)
main_router.include_router(callbacks_router)

__all__ = ["main_router"]
