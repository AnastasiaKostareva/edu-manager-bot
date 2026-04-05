from dataclasses import dataclass

from domain.entities import User, UserRole
from domain.exceptions import PermissionDeniedException


@dataclass(frozen=True)
class AccessPolicy:
    allowed_roles: tuple[UserRole, ...]

    def ensure(self, user: User) -> None:
        if user.role not in self.allowed_roles:
            raise PermissionDeniedException(
                f"Required roles: {[r.value for r in self.allowed_roles]}"
            )


class AuthService:
    def ensure_role(self, user: User, allowed_roles: list[UserRole]) -> None:
        policy = AccessPolicy(tuple(allowed_roles))
        policy.ensure(user)
