from datetime import datetime, timedelta, timezone

from domain.entities import Reminder, ReminderTime, ReminderType, User, UserRole
from domain.exceptions import PermissionDeniedException, ValidationException
from application.interfaces.repositories import IReminderRepository, ILessonRepository

MSK = timezone(timedelta(hours=3))


class ReminderService:
    def __init__(self, reminder_repo: IReminderRepository, lesson_repo: ILessonRepository):
        self._reminder_repo = reminder_repo
        self._lesson_repo = lesson_repo

    async def list_for_user(self, user_id: int) -> list[Reminder]:
        return await self._reminder_repo.get_by_user_id(user_id)

    async def delete(self, reminder_id: int, actor: User) -> None:
        reminder = await self._reminder_repo.get_by_id(reminder_id)
        if not reminder:
            return

        # Удалить может только тот, кто создал напоминание, или admin/owner.
        # Получатель напоминания (user_id) НЕ может удалить чужое напоминание.
        if actor.role not in (UserRole.ADMIN, UserRole.OWNER):
            if reminder.creator_id != actor.telegram_id:
                raise PermissionDeniedException("Вы не можете удалить это напоминание")

        await self._reminder_repo.delete(reminder_id)

    async def create_for_lesson(
        self,
        *,
        actor: User,
        target_user_id: int,
        lesson_id: int,
        reminder_type: ReminderType,
        time_value: str,
        custom_text: str | None = None,
    ) -> Reminder:
        """
        Создаёт напоминание для занятия.
        Время занятия считается московским (UTC+3) — конвертируется в UTC при сохранении.
        """
        normalized_time = (time_value or "").strip().lower()
        if not normalized_time:
            raise ValidationException("Invalid reminder time")

        try:
            reminder_time = (
                ReminderTime.from_custom_format(normalized_time)
                if ":" in normalized_time
                else ReminderTime.from_string(normalized_time)
            )
        except ValueError as exc:
            raise ValidationException("Invalid reminder time") from exc

        if reminder_time.minutes <= 0:
            raise ValidationException("Invalid reminder time")

        lesson = await self._lesson_repo.get_by_id(lesson_id)
        if not lesson or not lesson.scheduled_at:
            raise ValidationException("Lesson not found")

        # scheduled_at хранится как UTC-aware (конвертация из MSK происходит при создании занятия)
        lesson_dt = lesson.scheduled_at
        if lesson_dt.tzinfo is None:
            # Обратная совместимость: наивное время считаем московским
            lesson_dt = lesson_dt.replace(tzinfo=MSK)

        remind_at = lesson_dt - timedelta(minutes=reminder_time.minutes)
        # Конвертируем в UTC для корректного сравнения в БД
        remind_at_utc = remind_at.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)

        if remind_at <= now:
            msk_remind = remind_at.astimezone(MSK)
            msk_now = now.astimezone(MSK)
            raise ValidationException(
                f"Напоминание попадает в прошлое.\n"
                f"Время напоминания: {msk_remind.strftime('%H:%M')} МСК. "
                f"Сейчас: {msk_now.strftime('%H:%M')} МСК"
            )

        reminder = Reminder(
            id=0,
            user_id=target_user_id,
            creator_id=actor.telegram_id,
            lesson_id=lesson_id,
            reminder_type=reminder_type,
            custom_text=custom_text,
            remind_at=remind_at_utc,
            is_sent=False,
        )
        return await self._reminder_repo.create(reminder)
