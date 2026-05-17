import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot

from application.config import get_config
from infrastructure.database.repositories import ReminderRepository, LessonRepository, ChatRepository, UserRepository, ChatMemberRepository
from application.use_cases.lesson import LessonService
from domain.entities import LessonStatus, ReminderType, UserRole, StartNotificationLevel

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
CHAT_NOTIFY_COOLDOWN_DAYS = 1


class Scheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.reminder_repo = ReminderRepository()
        self.lesson_repo = LessonRepository()
        self.chat_repo = ChatRepository()
        self.user_repo = UserRepository()
        self.chat_member_repo = ChatMemberRepository()
        self.lesson_service = LessonService(self.lesson_repo)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Дедупликация уведомлений о чатах без занятий: {chat_id: last_notified_at}
        self._chat_notified_at: dict[int, datetime] = {}

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
                await self._check_lesson_completions()
                await self._check_overdue_lessons()
                await self._check_chats()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            await asyncio.sleep(interval)

    async def _check_reminders(self):
        now = datetime.now(timezone.utc)
        pending = await self.reminder_repo.get_pending(now)

        for reminder in pending:
            try:
                await self._send_reminder(reminder)
                await self.reminder_repo.mark_sent(reminder.id)
            except Exception as e:
                logger.error(f"Failed to send reminder {reminder.id}: {e}")

    async def _send_reminder(self, reminder):
        # Определяем получателя: приоритет у chat_id (группы), затем user_id (личка)
        target_id = reminder.chat_id or reminder.user_id
        if not target_id:
            logger.warning(
                f"Reminder {reminder.id} has no valid target (chat_id or user_id). Skipping.")
            return

        # Если есть привязка к занятию — формируем красивое уведомление
        if reminder.lesson_id:
            lesson = await self.lesson_repo.get_by_id(reminder.lesson_id)
            if not lesson:
                logger.warning(
                    f"Lesson {reminder.lesson_id} not found for reminder {reminder.id}. Skipping.")
                return

            now = datetime.now(timezone.utc)
            lesson_dt = lesson.scheduled_at
            if lesson_dt.tzinfo is None:
                lesson_dt = lesson_dt.replace(tzinfo=MSK)
            time_diff = lesson_dt - now
            minutes = max(0, int(time_diff.total_seconds() / 60))

            if reminder.reminder_type == ReminderType.LESSON:
                text = f"⏰ Напоминание!\nЗанятие «{lesson.topic}» начнётся через {minutes} мин."
            elif reminder.reminder_type == ReminderType.HOMEWORK:
                text = f"📝 Напоминание о домашнем задании к занятию «{lesson.topic}»"
            else:
                text = reminder.custom_text or "Напоминание"

            from aiogram.types import InlineKeyboardMarkup, \
                InlineKeyboardButton

            await self.bot.send_message(target_id, text)

        # Если напоминание без занятия (кастомное)
        else:
            text = reminder.custom_text or "Напоминание"
            await self.bot.send_message(target_id, text)

    async def _check_lesson_completions(self):
        """Проверяет занятия, которые должны начаться, и отправляет уведомление в чат"""
        lessons = await self.lesson_service.get_lessons_needing_completion()
        now = datetime.now(timezone.utc)
        for lesson in lessons:
            try:
                # 🔹 Отправляем в ОБЩИЙ ЧАТ, а не в ЛС
                chat_id = lesson.chat_id

                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

                lesson_dt = lesson.scheduled_at
                if lesson_dt.tzinfo is None:
                    lesson_dt = lesson_dt.replace(tzinfo=MSK)

                time_passed = (now - lesson_dt).total_seconds() / 60.0

                if lesson.start_notification_level == StartNotificationLevel.NONE and time_passed >= 0:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="▶️ Начать занятие",
                            callback_data=f"start_lesson:{lesson.id}"
                        )]
                    ])
                    message_text = (
                        f"⏰ Пора начинать!\n\n"
                        f"📚 Тема: {lesson.topic}\n"
                        f"🕐 Запланировано: {lesson_dt.astimezone(MSK).strftime('%d.%m %H:%M')} МСК"
                    )
                    await self.bot.send_message(chat_id, message_text, reply_markup=keyboard)
                    lesson.start_notification_level = StartNotificationLevel.STARTED
                    await self.lesson_repo.update(lesson)
                    logger.info(f"Sent start notification for lesson {lesson.id} (level: NONE -> STARTED)")

                elif lesson.start_notification_level == StartNotificationLevel.STARTED and time_passed >= 10:
                    message_text = (
                        f"⚠️ Занятие «{lesson.topic}» задерживается уже на 10 минут!\n"
                    )
                    await self.bot.send_message(chat_id, message_text)
                    lesson.start_notification_level = StartNotificationLevel.LATE_10_MIN
                    await self.lesson_repo.update(lesson)
                    logger.info(f"Sent late_10 warning for lesson {lesson.id} (level: STARTED -> LATE_10_MIN)")

                elif lesson.start_notification_level == StartNotificationLevel.LATE_10_MIN and time_passed >= 30:
                    message_text = (
                        f"🚨 Прошло 30 минут с ожидаемого начала занятия «{lesson.topic}».\n"
                        f"Оно до сих пор не начато!"
                    )
                    admins = await self.user_repo.get_all_admins()
                    for admin in admins:
                        try:
                            await self.bot.send_message(admin.telegram_id, f"Чат {chat_id}:\n" + message_text)
                        except Exception:
                            pass
                    await self.bot.send_message(chat_id, message_text)
                    lesson.start_notification_level = StartNotificationLevel.LATE_30_MIN
                    await self.lesson_repo.update(lesson)
                    logger.info(f"Sent late_30 warning for lesson {lesson.id} (level: LATE_10_MIN -> LATE_30_MIN)")

            except Exception as e:
                logger.error(f"Failed to process start notification for lesson {lesson.id}: {e}")

    async def _check_overdue_lessons(self):
        overdue_lessons = await self.lesson_service.get_overdue_lessons(hours=24)

        for lesson in overdue_lessons:
            try:
                if lesson.status != LessonStatus.OVERDUE:
                    await self.lesson_service.mark_overdue(lesson.id)

                    teacher = await self.user_repo.get_by_telegram_id(lesson.created_by)
                    teacher_name = teacher.full_name or teacher.username if teacher else f"ID {lesson.created_by}"

                    admins = await self.user_repo.get_all_admins()

                    lesson_dt = lesson.scheduled_at
                    if lesson_dt.tzinfo is None:
                        lesson_dt = lesson_dt.replace(tzinfo=MSK)

                    alert_text = (
                        f"⚠️ ПРОСРОЧЕННОЕ ЗАНЯТИЕ\n\n"
                        f"📚 Тема: {lesson.topic}\n"
                        f"👨‍🏫 Преподаватель: {teacher_name}\n"
                        f"🕐 Дата: {lesson_dt.astimezone(MSK).strftime('%d.%m.%Y %H:%M')} МСК\n"
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

    @staticmethod
    def _format_user_mention(user) -> str:
        name = user.full_name or user.username or f"ID {user.telegram_id}"
        if user.username:
            return f"@{user.username}"
        return f'<a href="tg://user?id={user.telegram_id}">{name}</a>'

    async def _get_chat_responsible_users(self, chat_id: int):
        members = await self.chat_member_repo.get_members_by_chat(chat_id)
        if not members:
            return await self.user_repo.get_all_admins()

        users = []
        for member in members:
            user = await self.user_repo.get_by_telegram_id(member.user_id)
            if user and user.is_active:
                users.append(user)

        owners_teachers = [u for u in users if u.role in (UserRole.OWNER, UserRole.TEACHER)]
        if owners_teachers:
            return owners_teachers

        owners_admins = [u for u in users if u.role in (UserRole.OWNER, UserRole.ADMIN)]
        if owners_admins:
            return owners_admins

        return await self.user_repo.get_all_admins()

    def _build_mentions_text(self, users) -> str:
        unique = {u.telegram_id: u for u in users}
        return " ".join(self._format_user_mention(u) for u in unique.values())

    async def _check_chats(self):
        chats = await self.chat_repo.get_all_active()
        now = datetime.now(timezone.utc)
        cooldown = timedelta(days=CHAT_NOTIFY_COOLDOWN_DAYS)

        for chat in chats:
            # Личные чаты не тревожим уведомлениями о расписании
            if chat.chat_type == "private":
                continue

            try:
                # Дедупликация: не слать уведомление чаще раза в неделю
                last_notified = self._chat_notified_at.get(chat.chat_id)
                if last_notified and (now - last_notified) < cooldown:
                    continue

                upcoming = await self.lesson_repo.get_upcoming_for_chat(chat.chat_id)
                if upcoming:
                    continue

                last_lesson = await self.lesson_repo.get_last_for_chat(chat.chat_id)
                stale = (
                    last_lesson is None
                    or (now - (last_lesson.scheduled_at if last_lesson.scheduled_at.tzinfo else last_lesson.scheduled_at.replace(tzinfo=MSK))) > timedelta(days=2)
                )
                if not stale:
                    continue

                mention_users = await self._get_chat_responsible_users(chat.chat_id)
                mentions = self._build_mentions_text(mention_users)
                message_text = (
                    "📭 Нет запланированных занятий.\n"
                    "Последнее занятие было более 2 дней назад. Хотите назначить следующее?\n\n"
                    f"{mentions}"
                )

                await self.bot.send_message(
                    chat.chat_id,
                    message_text,
                    parse_mode="HTML",
                )
                self._chat_notified_at[chat.chat_id] = now

            except Exception as e:
                logger.error(f"Failed to check chat {chat.chat_id}: {e}")
