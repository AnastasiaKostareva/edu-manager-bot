from datetime import datetime
from typing import Optional

from domain.entities import User, UserRole, Chat, ChatMember
from domain.exceptions import PermissionDeniedException, ValidationException
from application.interfaces.repositories import IChatRepository, IChatMemberRepository, IUserRepository


class ChatService:
    def __init__(
        self,
        chat_repo: IChatRepository,
        chat_member_repo: IChatMemberRepository,
        user_repo: IUserRepository,
    ):
        self.chat_repo = chat_repo
        self.chat_member_repo = chat_member_repo
        self.user_repo = user_repo

    async def initialize_chat(
        self,
        actor: User,
        chat_id: int,
        chat_title: str,
        chat_type: str,
        student_username: Optional[str] = None,
        student_telegram_id: Optional[int] = None,
        default_profile_id: int = 1,
    ) -> tuple[Chat, ChatMember, ChatMember]:
        """
        Инициализация чата преподавателем.

        Args:
            actor: Пользователь, инициирующий чат (должен быть TEACHER/ADMIN/OWNER)
            chat_id: ID Telegram-чата
            chat_title: Название чата
            chat_type: Тип чата (private/group)
            student_username: Username студента (с @ или без)
            student_telegram_id: Telegram ID студента (используется как fallback)
            default_profile_id: ID профиля уведомлений по умолчанию

        Returns:
            Tuple из (Chat, teacher_member, student_member)

        Raises:
            PermissionDeniedException: Если actor не имеет права создавать чаты
            ValidationException: Если студент не найден или чат уже инициализирован
        """
        # Проверка прав доступа
        if actor.role not in (UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER):
            raise PermissionDeniedException(
                "Только преподаватели и администраторы могут инициализировать чаты"
            )

        # Проверка, не инициализирован ли уже чат
        existing_chat = await self.chat_repo.get_by_id(chat_id)
        if existing_chat:
            existing_members = await self.chat_member_repo.get_members_by_chat(chat_id)
            if existing_members:
                raise ValidationException(
                    f"Чат уже инициализирован с {len(existing_members)} участниками"
                )

        # Поиск студента
        student: Optional[User] = None

        if student_username:
            # Очистка username от @
            clean_username = student_username.lstrip("@")
            student = await self.user_repo.get_by_username(clean_username)

        if not student and student_telegram_id:
            student = await self.user_repo.get_by_telegram_id(student_telegram_id)

        if not student:
            raise ValidationException(
                "Студент не найден. "
                "Попросите студента написать любое сообщение в чат для регистрации, "
                "затем повторите команду /init."
            )

        # Создание или обновление записи чата
        if not existing_chat:
            chat = Chat(
                chat_id=chat_id,
                chat_title=chat_title,
                chat_type=chat_type,
                created_at=datetime.utcnow(),
                is_active=True,
            )
            await self.chat_repo.create(chat)
        else:
            chat = existing_chat

        # Добавление преподавателя в чат
        teacher_member = ChatMember(
            id=0,  # Будет присвоен при создании
            chat_id=chat_id,
            user_id=actor.telegram_id,
            profile_id=default_profile_id,
            joined_at=datetime.utcnow(),
            is_active=True,
        )
        teacher_member = await self.chat_member_repo.create(teacher_member)

        # Добавление студента в чат
        student_member = ChatMember(
            id=0,  # Будет присвоен при создании
            chat_id=chat_id,
            user_id=student.telegram_id,
            profile_id=default_profile_id,
            joined_at=datetime.utcnow(),
            is_active=True,
        )
        student_member = await self.chat_member_repo.create(student_member)

        return chat, teacher_member, student_member

    async def get_chat_member(self, chat_id: int, user_id: int) -> Optional[ChatMember]:
        """Получить информацию об участнике чата."""
        return await self.chat_member_repo.get_by_chat_and_user(chat_id, user_id)

    async def is_chat_initialized(self, chat_id: int) -> bool:
        """Проверить, инициализирован ли чат (есть ли в нем занятия)."""
        chat = await self.chat_repo.get_by_id(chat_id)
        if not chat:
            return False
        
        # Чат считается инициализированным, если в нем есть хотя бы одно занятие
        # или если это групповой чат, в котором прошла регистрация (есть участники)
        from infrastructure.database.models import Lesson as LessonModel
        from infrastructure.database.models import ChatMember as ChatMemberModel
        
        has_lessons = await LessonModel.filter(chat_id=chat_id).exists()
        if has_lessons:
            return True
            
        has_members = await ChatMemberModel.filter(chat_id=chat_id, is_active=True).exists()
        return has_members
