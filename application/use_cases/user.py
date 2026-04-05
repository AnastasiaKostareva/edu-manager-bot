from typing import Optional
from domain.entities import User, UserRole
from domain.exceptions import UserNotFoundException, PermissionDeniedException
from application.interfaces.repositories import IUserRepository


class UserService:
    def __init__(self, user_repo: IUserRepository):
        self._user_repo = user_repo

    async def get_user(self, telegram_id: int) -> Optional[User]:
        return await self._user_repo.get_by_telegram_id(telegram_id)

    async def get_user_by_username(self, username: str) -> Optional[User]:
        return await self._user_repo.get_by_username(username)

    async def create_user(
        self,
        telegram_id: int,
        username: str,
        full_name: Optional[str] = None,
        role: UserRole = UserRole.STUDENT
    ) -> User:
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            role=role,
            is_active=True
        )
        return await self._user_repo.create(user)

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: str,
        full_name: Optional[str] = None,
        default_role: UserRole = UserRole.STUDENT
    ) -> tuple[User, bool]:
        existing = await self._user_repo.get_by_telegram_id(telegram_id)
        if existing:
            return existing, True
        
        user = await self.create_user(telegram_id, username, full_name, default_role)
        return user, False

    async def update_user_role(self, telegram_id: int, new_role: UserRole) -> User:
        user = await self._user_repo.get_by_telegram_id(telegram_id)
        if not user:
            raise UserNotFoundException(f"User {telegram_id} not found")
        
        user.role = new_role
        return await self._user_repo.update(user)

    def has_permission(self, user: User, required_roles: list[UserRole]) -> bool:
        return user.role in required_roles

    def require_role(self, user: User, required_roles: list[UserRole]) -> None:
        if not self.has_permission(user, required_roles):
            raise PermissionDeniedException(f"Required roles: {[r.value for r in required_roles]}")