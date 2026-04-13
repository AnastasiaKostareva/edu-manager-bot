"""
Pytest configuration and fixtures.
"""
import pytest
from datetime import datetime
from domain.entities import User, UserRole, Lesson, LessonStatus


@pytest.fixture
def owner_user():
    """Fixture для пользователя с ролью OWNER."""
    return User(
        telegram_id=123456789,
        username="owner_user",
        role=UserRole.OWNER,
        full_name="Owner User",
        is_active=True
    )


@pytest.fixture
def teacher_user():
    """Fixture для пользователя с ролью TEACHER."""
    return User(
        telegram_id=987654321,
        username="teacher_user",
        role=UserRole.TEACHER,
        full_name="Teacher User",
        is_active=True
    )


@pytest.fixture
def student_user():
    """Fixture для пользователя с ролью STUDENT."""
    return User(
        telegram_id=111222333,
        username="student_user",
        role=UserRole.STUDENT,
        full_name="Student User",
        is_active=True
    )


@pytest.fixture
def sample_lesson():
    """Fixture для тестового занятия."""
    return Lesson(
        id=1,
        chat_id=12345,
        created_by=987654321,
        scheduled_at=datetime(2024, 12, 15, 10, 0),
        scheduled_end=datetime(2024, 12, 15, 11, 0),
        status=LessonStatus.SCHEDULED,
        topic="Математика",
        lesson_link="https://zoom.us/j/123",
    )
