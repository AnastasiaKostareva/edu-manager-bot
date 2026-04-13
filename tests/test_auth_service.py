"""
Тесты для AuthService - проверка прав доступа.
"""
import pytest
from application.use_cases.auth import AuthService
from domain.entities import User, UserRole
from domain.exceptions import PermissionDeniedException


class TestAuthService:
    """Тесты для сервиса авторизации."""

    def test_owner_has_all_permissions(self, owner_user):
        """Владелец имеет доступ ко всем ролям."""
        service = AuthService()

        # Не должно быть исключения
        service.ensure_role(owner_user, [UserRole.OWNER])
        service.ensure_role(owner_user, [UserRole.ADMIN])
        service.ensure_role(owner_user, [UserRole.TEACHER])

    def test_teacher_cannot_access_owner_features(self, teacher_user):
        """Преподаватель не может использовать функции owner."""
        service = AuthService()

        with pytest.raises(PermissionDeniedException):
            service.ensure_role(teacher_user, [UserRole.OWNER])

    def test_student_cannot_create_lessons(self, student_user):
        """Студент не может создавать занятия."""
        service = AuthService()

        with pytest.raises(PermissionDeniedException):
            service.ensure_role(
                student_user,
                [UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER]
            )

    def test_teacher_can_manage_lessons(self, teacher_user):
        """Преподаватель может управлять занятиями."""
        service = AuthService()

        # Не должно быть исключения
        service.ensure_role(
            teacher_user,
            [UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER]
        )

    def test_permission_denied_message_contains_required_roles(self, student_user):
        """Сообщение об ошибке содержит список требуемых ролей."""
        service = AuthService()

        with pytest.raises(PermissionDeniedException) as exc_info:
            service.ensure_role(student_user, [UserRole.ADMIN, UserRole.OWNER])

        error_message = str(exc_info.value)
        assert "admin" in error_message.lower()
        assert "owner" in error_message.lower()
