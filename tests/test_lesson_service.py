"""
Тесты для LessonService - управление занятиями.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from application.use_cases.lesson import LessonService
from domain.entities import User, UserRole, Lesson, LessonStatus, RepeatType
from domain.exceptions import PermissionDeniedException, ValidationException


class TestLessonService:

    @pytest.fixture
    def lesson_repo_mock(self):
        return AsyncMock()

    @pytest.fixture
    def lesson_service(self, lesson_repo_mock):
        return LessonService(lesson_repo_mock)

    # ── Права на создание занятия ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_admin_can_schedule_lesson(self, lesson_service, lesson_repo_mock, owner_user):
        """ADMIN/OWNER может назначить занятие."""
        future_time = datetime.now(timezone.utc) + timedelta(days=1)
        lesson_repo_mock.create.return_value = Lesson(
            id=1, chat_id=12345, created_by=owner_user.telegram_id,
            scheduled_at=future_time, status=LessonStatus.SCHEDULED, topic="Математика",
        )
        result = await lesson_service.schedule(
            actor=owner_user, chat_id=12345, scheduled_at=future_time, topic="Математика"
        )
        assert result.topic == "Математика"
        assert result.status == LessonStatus.SCHEDULED
        lesson_repo_mock.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_teacher_can_schedule_lesson(self, lesson_service, lesson_repo_mock, teacher_user):
        """Преподаватель может назначать занятия."""
        future_time = datetime.now(timezone.utc) + timedelta(days=1)
        lesson_repo_mock.create.return_value = Lesson(
            id=1, chat_id=12345, created_by=teacher_user.telegram_id,
            scheduled_at=future_time, status=LessonStatus.SCHEDULED, topic="Математика",
        )
        result = await lesson_service.schedule(
            actor=teacher_user, chat_id=12345, scheduled_at=future_time, topic="Математика"
        )
        assert result.topic == "Математика"
        assert result.status == LessonStatus.SCHEDULED
        lesson_repo_mock.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_student_cannot_schedule_lesson(self, lesson_service, student_user):
        """Студент не может назначить занятие."""
        future_time = datetime.now(timezone.utc) + timedelta(days=1)
        with pytest.raises(PermissionDeniedException):
            await lesson_service.schedule(
                actor=student_user, chat_id=12345, scheduled_at=future_time, topic="Математика"
            )

    @pytest.mark.asyncio
    async def test_cannot_schedule_lesson_in_past(self, lesson_service, owner_user):
        """Нельзя назначить занятие в прошлом."""
        past_time = datetime.now(timezone.utc) - timedelta(days=1)
        with pytest.raises(ValidationException) as exc_info:
            await lesson_service.schedule(
                actor=owner_user, chat_id=12345, scheduled_at=past_time, topic="Математика"
            )
        assert "future" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_cannot_schedule_lesson_without_topic(self, lesson_service, owner_user):
        """Нельзя создать занятие без темы."""
        future_time = datetime.now(timezone.utc) + timedelta(days=1)
        with pytest.raises(ValidationException) as exc_info:
            await lesson_service.schedule(
                actor=owner_user, chat_id=12345, scheduled_at=future_time, topic=""
            )
        assert "topic" in str(exc_info.value).lower()

    # ── Завершение занятия ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_complete_lesson_success(self, lesson_service, lesson_repo_mock, teacher_user, sample_lesson):
        """Преподаватель может завершить своё занятие."""
        lesson_repo_mock.get_by_id.return_value = sample_lesson
        lesson_repo_mock.update.return_value = sample_lesson
        result = await lesson_service.complete_lesson(
            lesson_id=1, actor=teacher_user, duration_minutes=60
        )
        assert result.status == LessonStatus.COMPLETED
        assert result.duration_minutes == 60
        lesson_repo_mock.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_cannot_complete_already_completed_lesson(
        self, lesson_service, lesson_repo_mock, teacher_user, sample_lesson
    ):
        """Нельзя завершить уже завершённое занятие."""
        sample_lesson.status = LessonStatus.COMPLETED
        lesson_repo_mock.get_by_id.return_value = sample_lesson
        with pytest.raises(ValidationException) as exc_info:
            await lesson_service.complete_lesson(lesson_id=1, actor=teacher_user, duration_minutes=60)
        assert "already" in str(exc_info.value).lower() or "уже" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_teacher_cannot_complete_other_teacher_lesson(
        self, lesson_service, lesson_repo_mock, teacher_user, sample_lesson
    ):
        """Преподаватель не может завершить чужое занятие."""
        sample_lesson.created_by = 999999999
        lesson_repo_mock.get_by_id.return_value = sample_lesson
        with pytest.raises(PermissionDeniedException):
            await lesson_service.complete_lesson(lesson_id=1, actor=teacher_user, duration_minutes=60)

    @pytest.mark.asyncio
    async def test_admin_can_complete_any_lesson(
        self, lesson_service, lesson_repo_mock, owner_user, sample_lesson
    ):
        """Администратор может завершить любое занятие."""
        sample_lesson.created_by = 999999999
        lesson_repo_mock.get_by_id.return_value = sample_lesson
        lesson_repo_mock.update.return_value = sample_lesson
        result = await lesson_service.complete_lesson(lesson_id=1, actor=owner_user, duration_minutes=60)
        assert result.status == LessonStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_invalid_duration_rejected(self, lesson_service, lesson_repo_mock, teacher_user, sample_lesson):
        """Нулевая или отрицательная длительность отклоняется."""
        lesson_repo_mock.get_by_id.return_value = sample_lesson
        with pytest.raises(ValidationException):
            await lesson_service.complete_lesson(lesson_id=1, actor=teacher_user, duration_minutes=0)
        with pytest.raises(ValidationException):
            await lesson_service.complete_lesson(lesson_id=1, actor=teacher_user, duration_minutes=-10)
