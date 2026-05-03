from datetime import datetime, timedelta, timezone

from domain.entities import Reminder, ReminderTime, ReminderType, User
from domain.exceptions import ValidationException
from application.interfaces.repositories import IReminderRepository, ILessonRepository


class ReminderService:
    def __init__(self, reminder_repo: IReminderRepository, lesson_repo: ILessonRepository):
        self._reminder_repo = reminder_repo
        self._lesson_repo = lesson_repo

    async def list_for_user(self, user_id: int) -> list[Reminder]:
        return await self._reminder_repo.get_by_user_id(user_id)

    async def delete(self, reminder_id: int) -> None:
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

        remind_at = lesson.scheduled_at - timedelta(minutes=reminder_time.minutes)
        if remind_at.tzinfo is not None:
            now = datetime.now(timezone.utc)
        else:
            now = datetime.now()

        if remind_at <= now:
            raise ValidationException("Reminder time is in the past")

        reminder = Reminder(
            id=0,
            user_id=target_user_id,
            lesson_id=lesson_id,
            reminder_type=reminder_type,
            custom_text=custom_text,
            remind_at=remind_at,
            is_sent=False,
        )
        return await self._reminder_repo.create(reminder)
