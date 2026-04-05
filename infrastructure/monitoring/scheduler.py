import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot

from application.config import get_config
from infrastructure.database.repositories import ReminderRepository, LessonRepository, ChatRepository
from domain.entities import LessonStatus, ReminderType

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.reminder_repo = ReminderRepository()
        self.lesson_repo = LessonRepository()
        self.chat_repo = ChatRepository()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("Scheduler started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler stopped")

    async def _run(self):
        config = get_config()
        interval = config.scheduler.check_interval_seconds

        while self._running:
            try:
                await self._check_reminders()
                await self._check_chats()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            await asyncio.sleep(interval)

    async def _check_reminders(self):
        now = datetime.now()
        pending = await self.reminder_repo.get_pending(now)

        for reminder in pending:
            try:
                await self._send_reminder(reminder)
                await self.reminder_repo.mark_sent(reminder.id)
            except Exception as e:
                logger.error(f"Failed to send reminder {reminder.id}: {e}")

    async def _send_reminder(self, reminder):
        if reminder.lesson_id:
            lesson = await self.lesson_repo.get_by_id(reminder.lesson_id)
            if not lesson:
                return

            time_diff = lesson.scheduled_at - datetime.now()
            minutes = int(time_diff.total_seconds() / 60)

            if reminder.reminder_type == ReminderType.LESSON:
                text = f"Внимание!\nЗанятие \"{lesson.topic}\" начнется через {minutes} мин."
            elif reminder.reminder_type == ReminderType.HOMEWORK:
                text = f"Напоминание о домашнем задании к занятию \"{lesson.topic}\""
            else:
                text = reminder.custom_text or "Напоминание"

            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Начать занятие", callback_data=f"start_lesson:{lesson.id}")]
            ])

            await self.bot.send_message(reminder.user_id, text, reply_markup=keyboard)
        else:
            await self.bot.send_message(reminder.user_id, reminder.custom_text or "Напоминание")

    async def _check_chats(self):
        chats = await self.chat_repo.get_all_active()

        for chat in chats:
            try:
                last_lesson = await self.lesson_repo.get_last_for_chat(chat.chat_id)
                upcoming = await self.lesson_repo.get_upcoming_for_chat(chat.chat_id)

                if not last_lesson and not upcoming:
                    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Назначить занятие", callback_data="schedule_lesson")]
                    ])

                    await self.bot.send_message(
                        chat.chat_id,
                        "Последнее занятие было давно\nНовое еще не назначено",
                        reply_markup=keyboard
                    )
            except Exception as e:
                logger.error(f"Failed to check chat {chat.chat_id}: {e}")
