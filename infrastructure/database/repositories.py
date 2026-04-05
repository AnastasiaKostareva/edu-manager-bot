from typing import Optional, List
from datetime import datetime

from tortoise import Tortoise

from domain.entities import User, UserRole, Lesson, LessonStatus, RepeatType, Reminder, Chat

from application.interfaces.repositories import (
    IUserRepository,
    ILessonRepository,
    IReminderRepository,
    IChatRepository,
)


class UserRepository(IUserRepository):
    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        from infrastructure.database.models import User as UserModel
        model = await UserModel.get_or_none(telegram_id=telegram_id)
        if not model:
            return None
        return User(
            telegram_id=model.telegram_id,
            username=model.username,
            full_name=model.full_name,
            phone=model.phone,
            role=UserRole(model.role),
            is_active=model.is_active,
        )

    async def get_by_username(self, username: str) -> Optional[User]:
        from infrastructure.database.models import User as UserModel
        model = await UserModel.get_or_none(username=username)
        if not model:
            return None
        return User(
            telegram_id=model.telegram_id,
            username=model.username,
            full_name=model.full_name,
            phone=model.phone,
            role=UserRole(model.role),
            is_active=model.is_active,
        )

    async def create(self, user: User) -> User:
        from infrastructure.database.models import User as UserModel
        model = await UserModel.create(
            telegram_id=user.telegram_id,
            username=user.username,
            full_name=user.full_name,
            phone=user.phone,
            role=user.role.value,
            is_active=user.is_active,
        )
        return user

    async def update(self, user: User) -> User:
        from infrastructure.database.models import User as UserModel
        await UserModel.filter(telegram_id=user.telegram_id).update(
            username=user.username,
            full_name=user.full_name,
            phone=user.phone,
            role=user.role.value,
            is_active=user.is_active,
        )
        return user

    async def get_all_students(self) -> list[User]:
        from infrastructure.database.models import User as UserModel
        models = await UserModel.filter(role=UserRole.STUDENT.value, is_active=True)
        return [
            User(
                telegram_id=m.telegram_id,
                username=m.username,
                full_name=m.full_name,
                phone=m.phone,
                role=UserRole(m.role),
                is_active=m.is_active,
            )
            for m in models
        ]

    async def get_all_teachers(self) -> list[User]:
        from infrastructure.database.models import User as UserModel
        models = await UserModel.filter(role=UserRole.TEACHER.value, is_active=True)
        return [
            User(
                telegram_id=m.telegram_id,
                username=m.username,
                full_name=m.full_name,
                phone=m.phone,
                role=UserRole(m.role),
                is_active=m.is_active,
            )
            for m in models
        ]

    async def get_all_admins(self) -> list[User]:
        from infrastructure.database.models import User as UserModel
        models = await UserModel.filter(
            role__in=[UserRole.ADMIN.value, UserRole.OWNER.value], is_active=True
        )
        return [
            User(
                telegram_id=m.telegram_id,
                username=m.username,
                full_name=m.full_name,
                phone=m.phone,
                role=UserRole(m.role),
                is_active=m.is_active,
            )
            for m in models
        ]

    async def get_all_active(self) -> list[User]:
        from infrastructure.database.models import User as UserModel
        models = await UserModel.filter(is_active=True)
        return [
            User(
                telegram_id=m.telegram_id,
                username=m.username,
                full_name=m.full_name,
                phone=m.phone,
                role=UserRole(m.role),
                is_active=m.is_active,
            )
            for m in models
        ]


class LessonRepository(ILessonRepository):
    async def get_by_id(self, lesson_id: int) -> Optional[Lesson]:
        from infrastructure.database.models import Lesson as LessonModel
        model = await LessonModel.get_or_none(id=lesson_id)
        if not model:
            return None
        return self._to_entity(model)

    async def get_by_chat_id(self, chat_id: int) -> List[Lesson]:
        from infrastructure.database.models import Lesson as LessonModel
        models = await LessonModel.filter(chat_id=chat_id).order_by("-scheduled_at")
        return [self._to_entity(m) for m in models]

    async def get_by_user_id(self, user_id: int) -> List[Lesson]:
        from infrastructure.database.models import Lesson as LessonModel
        models = await LessonModel.filter(created_by=user_id).order_by("-scheduled_at")
        return [self._to_entity(m) for m in models]

    async def get_upcoming(self, limit: int = 10) -> List[Lesson]:
        from infrastructure.database.models import Lesson as LessonModel
        now = datetime.now()
        models = await LessonModel.filter(
            scheduled_at__gt=now,
            status__in=[LessonStatus.SCHEDULED.value, LessonStatus.CONFIRMED.value],
        ).order_by("scheduled_at").limit(limit)
        return [self._to_entity(m) for m in models]

    async def get_upcoming_for_chat(self, chat_id: int) -> Optional[Lesson]:
        from infrastructure.database.models import Lesson as LessonModel
        now = datetime.now()
        model = await LessonModel.filter(
            chat_id=chat_id,
            scheduled_at__gt=now,
            status__in=[LessonStatus.SCHEDULED.value, LessonStatus.CONFIRMED.value],
        ).order_by("scheduled_at").first()
        return self._to_entity(model) if model else None

    async def get_last_for_chat(self, chat_id: int) -> Optional[Lesson]:
        from infrastructure.database.models import Lesson as LessonModel
        model = await LessonModel.filter(chat_id=chat_id).order_by("-scheduled_at").first()
        return self._to_entity(model) if model else None

    async def create(self, lesson: Lesson) -> Lesson:
        from infrastructure.database.models import Lesson as LessonModel
        model = await LessonModel.create(
            chat_id=lesson.chat_id,
            created_by=lesson.created_by,
            lesson_link=lesson.lesson_link,
            repeat_type=lesson.repeat_type.value if lesson.repeat_type else None,
            scheduled_at=lesson.scheduled_at,
            actual_start=lesson.actual_start,
            scheduled_end=lesson.scheduled_end,
            actual_end=lesson.actual_end,
            duration_minutes=lesson.duration_minutes,
            status=lesson.status.value,
            topic=lesson.topic,
        )
        lesson.id = model.id
        return lesson

    async def update(self, lesson: Lesson) -> Lesson:
        from infrastructure.database.models import Lesson as LessonModel
        await LessonModel.filter(id=lesson.id).update(
            lesson_link=lesson.lesson_link,
            repeat_type=lesson.repeat_type.value if lesson.repeat_type else None,
            scheduled_at=lesson.scheduled_at,
            actual_start=lesson.actual_start,
            scheduled_end=lesson.scheduled_end,
            actual_end=lesson.actual_end,
            duration_minutes=lesson.duration_minutes,
            status=lesson.status.value,
            topic=lesson.topic,
        )
        return lesson

    async def delete(self, lesson_id: int) -> None:
        from infrastructure.database.models import Lesson as LessonModel
        await LessonModel.filter(id=lesson_id).delete()

    def _to_entity(self, model) -> Lesson:
        return Lesson(
            id=model.id,
            chat_id=model.chat_id,
            created_by=model.created_by,
            lesson_link=model.lesson_link,
            repeat_type=RepeatType(model.repeat_type) if model.repeat_type else None,
            scheduled_at=model.scheduled_at,
            actual_start=model.actual_start,
            scheduled_end=model.scheduled_end,
            actual_end=model.actual_end,
            duration_minutes=model.duration_minutes,
            status=LessonStatus(model.status),
            topic=model.topic,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class ReminderRepository(IReminderRepository):
    async def get_by_id(self, reminder_id: int) -> Optional[Reminder]:
        from infrastructure.database.models import Reminder as ReminderModel
        model = await ReminderModel.get_or_none(id=reminder_id)
        return self._to_entity(model) if model else None

    async def get_by_user_id(self, user_id: int) -> List[Reminder]:
        from infrastructure.database.models import Reminder as ReminderModel
        models = await ReminderModel.filter(user_id=user_id).order_by("-remind_at")
        return [self._to_entity(m) for m in models]

    async def get_pending(self, before: datetime) -> List[Reminder]:
        from infrastructure.database.models import Reminder as ReminderModel
        models = await ReminderModel.filter(
            remind_at__lte=before,
            is_sent=False,
        ).order_by("remind_at")
        return [self._to_entity(m) for m in models]

    async def create(self, reminder: Reminder) -> Reminder:
        from infrastructure.database.models import Reminder as ReminderModel
        model = await ReminderModel.create(
            user_id=reminder.user_id,
            lesson_id=reminder.lesson_id,
            reminder_type=reminder.reminder_type.value,
            custom_text=reminder.custom_text,
            remind_at=reminder.remind_at,
            is_sent=reminder.is_sent,
        )
        reminder.id = model.id
        return reminder

    async def update(self, reminder: Reminder) -> Reminder:
        from infrastructure.database.models import Reminder as ReminderModel
        await ReminderModel.filter(id=reminder.id).update(
            user_id=reminder.user_id,
            lesson_id=reminder.lesson_id,
            reminder_type=reminder.reminder_type.value,
            custom_text=reminder.custom_text,
            remind_at=reminder.remind_at,
            is_sent=reminder.is_sent,
        )
        return reminder

    async def delete(self, reminder_id: int) -> None:
        from infrastructure.database.models import Reminder as ReminderModel
        await ReminderModel.filter(id=reminder_id).delete()

    async def mark_sent(self, reminder_id: int) -> None:
        from infrastructure.database.models import Reminder as ReminderModel
        await ReminderModel.filter(id=reminder_id).update(is_sent=True)

    def _to_entity(self, model) -> Reminder:
        from domain.entities import ReminderType
        return Reminder(
            id=model.id,
            user_id=model.user_id,
            lesson_id=model.lesson_id,
            reminder_type=ReminderType(model.reminder_type),
            custom_text=model.custom_text,
            remind_at=model.remind_at,
            is_sent=model.is_sent,
            created_at=model.created_at,
        )


class ChatRepository(IChatRepository):
    async def get_by_id(self, chat_id: int) -> Optional[Chat]:
        from infrastructure.database.models import Chat as ChatModel
        model = await ChatModel.get_or_none(chat_id=chat_id)
        return self._to_entity(model) if model else None

    async def create(self, chat: Chat) -> Chat:
        from infrastructure.database.models import Chat as ChatModel
        model = await ChatModel.create(
            chat_id=chat.chat_id,
            chat_title=chat.chat_title,
            chat_type=chat.chat_type,
            is_active=chat.is_active,
        )
        return chat

    async def update(self, chat: Chat) -> Chat:
        from infrastructure.database.models import Chat as ChatModel
        await ChatModel.filter(chat_id=chat.chat_id).update(
            chat_title=chat.chat_title,
            chat_type=chat.chat_type,
            is_active=chat.is_active,
        )
        return chat

    async def get_all_active(self) -> List[Chat]:
        from infrastructure.database.models import Chat as ChatModel
        models = await ChatModel.filter(is_active=True)
        return [self._to_entity(m) for m in models]

    def _to_entity(self, model) -> Chat:
        return Chat(
            chat_id=model.chat_id,
            chat_title=model.chat_title,
            chat_type=model.chat_type,
            created_at=model.created_at,
            is_active=model.is_active,
        )