from datetime import datetime

from domain.entities import Lesson, LessonStatus, RepeatType, User, UserRole
from domain.exceptions import PermissionDeniedException, ValidationException
from application.interfaces.repositories import ILessonRepository


class LessonService:
    def __init__(self, lesson_repo: ILessonRepository):
        self._lesson_repo = lesson_repo

    async def list_for_user(self, user_id: int) -> list[Lesson]:
        return await self._lesson_repo.get_by_user_id(user_id)

    async def list_for_chat(self, chat_id: int) -> list[Lesson]:
        return await self._lesson_repo.get_by_chat_id(chat_id)

    async def delete(self, lesson_id: int) -> None:
        await self._lesson_repo.delete(lesson_id)

    async def schedule(
        self,
        *,
        actor: User,
        chat_id: int,
        scheduled_at: datetime,
        topic: str,
        lesson_link: str | None = None,
        repeat_type: RepeatType | None = None,
    ) -> Lesson:
        if actor.role not in (UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER):
            raise PermissionDeniedException("No permission to schedule lesson")
        if not topic:
            raise ValidationException("Topic is required")
        if scheduled_at <= datetime.now():
            raise ValidationException("scheduled_at must be in the future")

        lesson = Lesson(
            chat_id=chat_id,
            created_by=actor.telegram_id,
            lesson_link=lesson_link,
            repeat_type=repeat_type,
            scheduled_at=scheduled_at,
            status=LessonStatus.SCHEDULED,
            topic=topic,
        )
        return await self._lesson_repo.create(lesson)

    async def upcoming(self, limit: int = 10) -> list[Lesson]:
        return await self._lesson_repo.get_upcoming(limit)

    async def get(self, lesson_id: int) -> Lesson | None:
        return await self._lesson_repo.get_by_id(lesson_id)
