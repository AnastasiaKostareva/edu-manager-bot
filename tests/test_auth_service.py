"""
Тесты для AuthService - проверка прав доступа.
"""
import pytest
from application.use_cases.auth import AuthService
from domain.entities import User, UserRole
from domain.exceptions import PermissionDeniedException


class TestAuthService:

    def test_owner_passes_owner_check(self, owner_user):
        """Владелец проходит проверку, если OWNER в списке допустимых ролей."""
        service = AuthService()
        service.ensure_role(owner_user, [UserRole.OWNER])
        service.ensure_role(owner_user, [UserRole.ADMIN, UserRole.OWNER])

    def test_owner_fails_if_not_in_allowed_list(self, owner_user):
        """ensure_role не имеет неявной иерархии: OWNER не проходит как ADMIN."""
        service = AuthService()
        with pytest.raises(PermissionDeniedException):
            service.ensure_role(owner_user, [UserRole.ADMIN])

    def test_teacher_cannot_access_owner_features(self, teacher_user):
        """Преподаватель не может использовать функции OWNER."""
        service = AuthService()
        with pytest.raises(PermissionDeniedException):
            service.ensure_role(teacher_user, [UserRole.OWNER])

    def test_student_cannot_create_lessons(self, student_user):
        """Студент не проходит проверку на роли ADMIN/OWNER."""
        service = AuthService()
        with pytest.raises(PermissionDeniedException):
            service.ensure_role(student_user, [UserRole.ADMIN, UserRole.OWNER])

    def test_teacher_passes_when_included(self, teacher_user):
        """Преподаватель проходит, если TEACHER явно указан в допустимых ролях."""
        service = AuthService()
        service.ensure_role(teacher_user, [UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER])

    def test_permission_denied_message_contains_required_roles(self, student_user):
        """Сообщение об ошибке содержит список требуемых ролей."""
        service = AuthService()
        with pytest.raises(PermissionDeniedException) as exc_info:
            service.ensure_role(student_user, [UserRole.ADMIN, UserRole.OWNER])
        error_message = str(exc_info.value)
        assert "admin" in error_message.lower()
        assert "owner" in error_message.lower()
