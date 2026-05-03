import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.memory import MemoryJobStore

from application.config import get_config
from infrastructure.database.repositories import ReminderRepository, LessonRepository, ChatRepository, UserRepository
from application.use_cases.lesson import LessonService
from domain.entities import LessonStatus, ReminderType

logger = logging.getLogger(__name__)

async def run_send_automatic_reminder_job(chat_id: int, topic: str, minutes: int):
    scheduler = Scheduler.get_instance()
    if scheduler:
        await scheduler.send_automatic_reminder_job(chat_id, topic, minutes)

async def run_ask_completion_job(lesson_id: int):
    scheduler = Scheduler.get_instance()
    if scheduler:
        await scheduler.ask_completion_job(lesson_id)

class Scheduler:
    _instance: Optional['Scheduler'] = None

    def __init__(self, bot: Bot):
        self.bot = bot
        self.reminder_repo = ReminderRepository()
        self.lesson_repo = LessonRepository()
        self.chat_repo = ChatRepository()
        self.user_repo = UserRepository()
        self.lesson_service = LessonService(self.lesson_repo)

        config = get_config()
        db_url = f"postgresql://{config.database.user}:{config.database.password}@{config.database.host}:{config.database.port}/{config.database.database}"

        jobstores = {
            'default': SQLAlchemyJobStore(url=db_url, tablename='apscheduler_jobs'),
            'memory': MemoryJobStore()
        }

        self.scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="UTC")
        Scheduler._instance = self

    @classmethod
    def get_instance(cls) -> 'Scheduler':
        return cls._instance

    async def start(self):
        # Adding periodical jobs
        self.scheduler.add_job(
            self._check_reminders,
            'interval',
            seconds=60,
            id='check_reminders_job',
            replace_existing=True,
            jobstore='memory'
        )
        self.scheduler.add_job(
            self._check_lesson_completions,
            'interval',
            seconds=60,
            id='check_lesson_completions_job',
            replace_existing=True,
            jobstore='memory'
        )
        self.scheduler.add_job(
            self._check_overdue_lessons,
            'interval',
            minutes=15,
            id='check_overdue_lessons_job',
            replace_existing=True,
            jobstore='memory'
        )
        # AC: Weekly cron job for checking chats (Monday morning)
        self.scheduler.add_job(
            self._check_chats,
            'cron',
            day_of_week='mon',
            hour=9,
            minute=0,
            id='check_chats_job',
            replace_existing=True,
            jobstore='memory'
        )

        self.scheduler.start()
        logger.info("APScheduler started")

    async def stop(self):
        self.scheduler.shutdown()
        logger.info("APScheduler stopped")

    def schedule_reminder(self, job_id: str, run_date: datetime, func, *args, **kwargs):
        self.scheduler.add_job(
            func,
            'date',
            run_date=run_date,
            id=job_id,
            replace_existing=True,
            args=args,
            kwargs=kwargs
        )

    def cancel_reminder(self, job_id: str):
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    async def send_automatic_reminder_job(self, chat_id: int, topic: str, minutes: int):
        text = f"Напоминание: Урок \"{topic}\" начнется через {minutes} минут."
        try:
            await self.bot.send_message(chat_id, text)
        except Exception as e:
            logger.error(f"Failed to send automatic reminder to {chat_id}: {e}")

    async def ask_completion_job(self, lesson_id: int):
        lesson = await self.lesson_repo.get_by_id(lesson_id)
        if not lesson or lesson.status not in (LessonStatus.SCHEDULED, LessonStatus.IN_PROGRESS):
            return

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="45", callback_data=f"complete_lesson:{lesson.id}:45"),
             InlineKeyboardButton(text="60", callback_data=f"complete_lesson:{lesson.id}:60"),
             InlineKeyboardButton(text="90", callback_data=f"complete_lesson:{lesson.id}:90")],
            [InlineKeyboardButton(text="Отменен", callback_data=f"complete_lesson:{lesson.id}:cancelled")]
        ])

        message_text = f"Урок завершен? Укажите длительность:\nТема: {lesson.topic}"

        try:
            await self.bot.send_message(
                lesson.created_by,
                message_text,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Failed to send completion request for lesson {lesson.id}: {e}")

    async def _check_reminders(self):
        # Use UTC-aware now to match DB-stored timestamps (Tortoise usually returns tz-aware datetimes).
        now = datetime.now(timezone.utc)
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

            # Ensure we compute difference with datetimes having the same tzinfo.
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

    async def _check_lesson_completions(self):
        # Оставлен пустым, так как теперь используются явно запланированные задачи (ask_completion_job)
        pass

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

        inactive_chats = []
        now = datetime.now()

        for chat in chats:
            try:
                last_lesson = await self.lesson_repo.get_last_for_chat(chat.chat_id)
                upcoming = await self.lesson_repo.get_upcoming_for_chat(chat.chat_id)

                if last_lesson and not upcoming:
                    days_passed = (now - last_lesson.scheduled_at.replace(tzinfo=None)).days
                    if days_passed > 7:
                        inactive_chats.append((chat, days_passed))
                elif not last_lesson and not upcoming:
                    # Если вообще нет занятий
                    days_passed = (now - chat.created_at.replace(tzinfo=None)).days
                    if days_passed > 7:
                        inactive_chats.append((chat, days_passed))
            except Exception as e:
                logger.error(f"Failed to check chat {chat.chat_id}: {e}")

        if inactive_chats:
            admins = await self.user_repo.get_all_admins()

            report_lines = ["⚠️ Отчет по 'зависшим' чатам (>7 дней без уроков):\n"]
            for chat, days in inactive_chats:
                report_lines.append(f"• Чат '{chat.chat_title}' (ID: {chat.chat_id}) — нет активности {days} дней")

            alert_text = "\n".join(report_lines)

            for admin in admins:
                try:
                    await self.bot.send_message(admin.telegram_id, alert_text)
                except Exception as e:
                    logger.error(f"Failed to send inactive chats report to admin {admin.telegram_id}: {e}")
