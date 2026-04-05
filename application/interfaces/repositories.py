from abc import ABC, abstractmethod
from typing import Optional, List
from datetime import datetime
from domain.entities import User, UserRole, Lesson, Reminder, Chat


class IUserRepository(ABC):
    @abstractmethod
    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        pass

    @abstractmethod
    async def get_by_username(self, username: str) -> Optional[User]:
        pass

    @abstractmethod
    async def create(self, user: User) -> User:
        pass

    @abstractmethod
    async def update(self, user: User) -> User:
        pass

    @abstractmethod
    async def get_all_students(self) -> list[User]:
        pass

    @abstractmethod
    async def get_all_teachers(self) -> list[User]:
        pass

    @abstractmethod
    async def get_all_admins(self) -> list[User]:
        pass

    @abstractmethod
    async def get_all_active(self) -> list[User]:
        pass


class ILessonRepository(ABC):
    @abstractmethod
    async def get_by_id(self, lesson_id: int) -> Optional[Lesson]:
        pass

    @abstractmethod
    async def get_by_chat_id(self, chat_id: int) -> List[Lesson]:
        pass

    @abstractmethod
    async def get_by_user_id(self, user_id: int) -> List[Lesson]:
        pass

    @abstractmethod
    async def get_upcoming(self, limit: int = 10) -> List[Lesson]:
        pass

    @abstractmethod
    async def get_upcoming_for_chat(self, chat_id: int) -> Optional[Lesson]:
        pass

    @abstractmethod
    async def get_last_for_chat(self, chat_id: int) -> Optional[Lesson]:
        pass

    @abstractmethod
    async def create(self, lesson: Lesson) -> Lesson:
        pass

    @abstractmethod
    async def update(self, lesson: Lesson) -> Lesson:
        pass

    @abstractmethod
    async def delete(self, lesson_id: int) -> None:
        pass


class IReminderRepository(ABC):
    @abstractmethod
    async def get_by_id(self, reminder_id: int) -> Optional[Reminder]:
        pass

    @abstractmethod
    async def get_by_user_id(self, user_id: int) -> List[Reminder]:
        pass

    @abstractmethod
    async def get_pending(self, before: datetime) -> List[Reminder]:
        pass

    @abstractmethod
    async def create(self, reminder: Reminder) -> Reminder:
        pass

    @abstractmethod
    async def update(self, reminder: Reminder) -> Reminder:
        pass

    @abstractmethod
    async def delete(self, reminder_id: int) -> None:
        pass

    @abstractmethod
    async def mark_sent(self, reminder_id: int) -> None:
        pass


class IChatRepository(ABC):
    @abstractmethod
    async def get_by_id(self, chat_id: int) -> Optional[Chat]:
        pass

    @abstractmethod
    async def create(self, chat: Chat) -> Chat:
        pass

    @abstractmethod
    async def update(self, chat: Chat) -> Chat:
        pass

    @abstractmethod
    async def get_all_active(self) -> List[Chat]:
        pass