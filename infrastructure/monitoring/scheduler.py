import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot

from application.config import get_config
from infrastructure.database.repositories import ReminderRepository, LessonRepository, ChatRepository, UserRepository
from application.use_cases.lesson import LessonService
from domain.entities import LessonStatus, ReminderType

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.reminder_repo = ReminderRepository()
        self.lesson_repo = LessonRepository()
        self.chat_repo = ChatRepository()
        self.user_repo = UserRepository()
        self.lesson_service = LessonService(self.lesson_repo)
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
                await self._check_lesson_completions()
                await self._check_overdue_lessons()
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

    async def _check_lesson_completions(self):
        """
        Проверяет занятия, которые закончились и требуют подтверждения длительности.
        Отправляет преподавателю инлайн-кнопки для выбора времени.
        """
        lessons = await self.lesson_service.get_lessons_needing_completion()

        for lesson in lessons:
            try:
                # Проверяем, не отправляли ли мы уже запрос (можно добавить флаг в БД)
                # Пока упрощенная версия - отправляем каждый раз при проверке

                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏱ 45 мин", callback_data=f"complete_lesson:{lesson.id}:45")],
                    [InlineKeyboardButton(text="⏱ 60 мин", callback_data=f"complete_lesson:{lesson.id}:60")],
                    [InlineKeyboardButton(text="⏱ 90 мин", callback_data=f"complete_lesson:{lesson.id}:90")],
                    [InlineKeyboardButton(text="✏️ Свой вариант", callback_data=f"complete_lesson:{lesson.id}:custom")],
                ])

                # Определяем время окончания
                end_time = lesson.scheduled_end or (lesson.scheduled_at + timedelta(hours=1))

                message_text = (
                    f"⏰ Занятие завершено!\n\n"
                    f"📚 Тема: {lesson.topic}\n"
                    f"🕐 Запланировано: {lesson.scheduled_at.strftime('%d.%m %H:%M')}\n"
                    f"🕑 Окончание: {end_time.strftime('%H:%M')}\n\n"
                    f"Пожалуйста, укажите фактическую длительность занятия:"
                )

                # Отправляем создателю занятия (преподавателю)
                await self.bot.send_message(
                    lesson.created_by,
                    message_text,
                    reply_markup=keyboard
                )

                logger.info(f"Sent completion request for lesson {lesson.id} to user {lesson.created_by}")

            except Exception as e:
                logger.error(f"Failed to send completion request for lesson {lesson.id}: {e}")

    async def _check_overdue_lessons(self):
        """
        Проверяет занятия, не закрытые в течение 24 часов.
        Помечает их как OVERDUE и отправляет алерт администраторам.
        """
        overdue_lessons = await self.lesson_service.get_overdue_lessons(hours=24)

        for lesson in overdue_lessons:
            try:
                # Помечаем как просроченное
                if lesson.status != LessonStatus.OVERDUE:
                    await self.lesson_service.mark_overdue(lesson.id)

                    # Получаем информацию о преподавателе
                    teacher = await self.user_repo.get_by_telegram_id(lesson.created_by)
                    teacher_name = teacher.full_name or teacher.username if teacher else f"ID {lesson.created_by}"

                    # Отправляем алерт всем администраторам
                    admins = await self.user_repo.get_all_admins()

                    alert_text = (
                        f"⚠️ ПРОСРОЧЕННОЕ ЗАНЯТИЕ\n\n"
                        f"📚 Тема: {lesson.topic}\n"
                        f"👨‍🏫 Преподаватель: {teacher_name}\n"
                        f"🕐 Дата: {lesson.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
                        f"⏰ Не закрыто более 24 часов\n\n"
                        f"ID занятия: {lesson.id}"
                    )

                    for admin in admins:
                        try:
                            await self.bot.send_message(admin.telegram_id, alert_text)
                        except Exception as e:
                            logger.error(f"Failed to send alert to admin {admin.telegram_id}: {e}")

                    logger.info(f"Marked lesson {lesson.id} as overdue and notified admins")

            except Exception as e:
                logger.error(f"Failed to process overdue lesson {lesson.id}: {e}")

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
