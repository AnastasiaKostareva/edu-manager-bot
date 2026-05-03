import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from aiogram import Bot

from application.config import get_config
from infrastructure.database.repositories import ReminderRepository, LessonRepository
from domain.entities import ReminderType

logger = logging.getLogger(__name__)


class NotificationWorker:
    """Worker, который отвечает только за отправку напоминаний.

    Каждую итерацию (интервал задаётся в конфиге) получает pending reminders
    из БД и отправляет их пользователям, помечая как отправленные.
    """

    def __init__(self, bot: Bot):
        self.bot = bot
        self.reminder_repo = ReminderRepository()
        self.lesson_repo = LessonRepository()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("NotificationWorker started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NotificationWorker stopped")

    async def _run(self):
        config = get_config()
        interval = config.scheduler.check_interval_seconds or 60

        while self._running:
            try:
                await self._check_and_send()
            except Exception as e:
                logger.error(f"NotificationWorker error: {e}")
            await asyncio.sleep(interval)

    async def _check_and_send(self):
        now = datetime.now(timezone.utc)
        pending = await self.reminder_repo.get_pending(now)

        if pending:
            logger.info(f"NotificationWorker: found {len(pending)} pending reminder(s) at {now.isoformat()}")

        for reminder in pending:
            try:
                await self._send_reminder(reminder)
                await self.reminder_repo.mark_sent(reminder.id)
                logger.info(f"Reminder {reminder.id} sent to user {reminder.user_id}")
            except Exception as e:
                logger.error(f"Failed to send reminder {reminder.id} to user {reminder.user_id}: {e}", exc_info=True)

    async def _send_reminder(self, reminder):
        # If reminder linked to lesson - include lesson info
        if reminder.lesson_id:
            lesson = await self.lesson_repo.get_by_id(reminder.lesson_id)
            if not lesson:
                return

            # compute minutes until lesson, careful with tz-aware vs naive
            if lesson.scheduled_at.tzinfo is not None:
                now = datetime.now(timezone.utc)
            else:
                now = datetime.now()

            time_diff = lesson.scheduled_at - now
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

