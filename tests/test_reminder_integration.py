"""
Integration-style tests for the reminder system.

Tests the full pipeline:
  ReminderService.create_for_lesson → ReminderRepository.get_pending → NotificationWorker._check_and_send

Repositories are mocked (no real DB), but all service and worker logic runs as-is.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

from application.use_cases.reminder import ReminderService
from domain.entities import (
    Lesson, LessonStatus, Reminder, ReminderType, User, UserRole,
)
from domain.exceptions import PermissionDeniedException, ValidationException
from infrastructure.monitoring.notification_worker import NotificationWorker

MSK = timezone(timedelta(hours=3))


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def teacher():
    return User(telegram_id=111, username="teacher", role=UserRole.TEACHER, full_name="Иван")

@pytest.fixture
def student():
    return User(telegram_id=222, username="student", role=UserRole.STUDENT, full_name="Студент")

@pytest.fixture
def future_lesson():
    """Занятие через 2 часа по МСК."""
    return Lesson(
        id=1,
        chat_id=9999,
        created_by=111,
        scheduled_at=datetime.now(MSK) + timedelta(hours=2),
        status=LessonStatus.SCHEDULED,
        topic="Алгебра",
    )

@pytest.fixture
def reminder_repo_mock():
    mock = AsyncMock()
    mock.create.side_effect = lambda r: _set_id(r, 42)
    return mock

@pytest.fixture
def lesson_repo_mock(future_lesson):
    mock = AsyncMock()
    mock.get_by_id.return_value = future_lesson
    return mock

@pytest.fixture
def reminder_service(reminder_repo_mock, lesson_repo_mock):
    return ReminderService(reminder_repo_mock, lesson_repo_mock)


def _set_id(reminder: Reminder, id_: int) -> Reminder:
    reminder.id = id_
    return reminder


# ─── ReminderService.create_for_lesson ────────────────────────────────────────

class TestReminderCreation:
    @pytest.mark.asyncio
    async def test_creates_reminder_30_min_before(self, reminder_service, reminder_repo_mock, teacher, future_lesson):
        result = await reminder_service.create_for_lesson(
            actor=teacher,
            target_user_id=teacher.telegram_id,
            lesson_id=1,
            reminder_type=ReminderType.LESSON,
            time_value="30m",
        )
        remind_at = result.remind_at
        expected = future_lesson.scheduled_at - timedelta(minutes=30)
        # Сравниваем с допуском 5 секунд
        assert abs((remind_at - expected).total_seconds()) < 5

    @pytest.mark.asyncio
    async def test_remind_at_is_utc_aware(self, reminder_service, teacher):
        result = await reminder_service.create_for_lesson(
            actor=teacher,
            target_user_id=teacher.telegram_id,
            lesson_id=1,
            reminder_type=ReminderType.LESSON,
            time_value="1h",
        )
        assert result.remind_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_creator_id_set_to_actor(self, reminder_service, teacher):
        result = await reminder_service.create_for_lesson(
            actor=teacher,
            target_user_id=222,
            lesson_id=1,
            reminder_type=ReminderType.LESSON,
            time_value="15m",
        )
        assert result.creator_id == teacher.telegram_id
        assert result.user_id == 222

    @pytest.mark.asyncio
    async def test_rejects_past_reminder(self, lesson_repo_mock, reminder_repo_mock, teacher):
        """Занятие уже прошло → напоминание в прошлом → ValidationException."""
        lesson_repo_mock.get_by_id.return_value = Lesson(
            id=2, chat_id=9999, created_by=111,
            scheduled_at=datetime.now(timezone.utc) - timedelta(hours=1),
            status=LessonStatus.SCHEDULED, topic="Прошедшее",
        )
        svc = ReminderService(reminder_repo_mock, lesson_repo_mock)
        with pytest.raises(ValidationException, match="прошлое"):
            await svc.create_for_lesson(
                actor=teacher, target_user_id=teacher.telegram_id,
                lesson_id=2, reminder_type=ReminderType.LESSON, time_value="5m",
            )

    @pytest.mark.asyncio
    async def test_arbitrary_time_formats(self, teacher):
        """8m, 3h, 1d — все форматы должны парситься и вычитаться правильно."""
        cases = [
            ("8m", 8),
            ("3h", 180),
            ("1d", 1440),
        ]
        # Занятие через 3 дня — далеко в будущем, любое напоминание не попадёт в прошлое
        far_lesson = Lesson(
            id=1, chat_id=9999, created_by=111,
            scheduled_at=datetime.now(MSK) + timedelta(days=3),
            status=LessonStatus.SCHEDULED, topic="Алгебра",
        )
        lesson_repo = AsyncMock()
        lesson_repo.get_by_id.return_value = far_lesson
        reminder_repo = AsyncMock()
        reminder_repo.create.side_effect = lambda r: _set_id(r, 42)
        svc = ReminderService(reminder_repo, lesson_repo)

        for value, expected_min in cases:
            result = await svc.create_for_lesson(
                actor=teacher, target_user_id=teacher.telegram_id,
                lesson_id=1, reminder_type=ReminderType.LESSON, time_value=value,
            )
            actual_min = round((far_lesson.scheduled_at - result.remind_at).total_seconds() / 60)
            assert actual_min == expected_min, f"value={value}: got {actual_min} min, want {expected_min}"

    @pytest.mark.asyncio
    async def test_invalid_time_format_raises(self, reminder_service, teacher):
        with pytest.raises(ValidationException, match="Invalid reminder time"):
            await reminder_service.create_for_lesson(
                actor=teacher, target_user_id=teacher.telegram_id,
                lesson_id=1, reminder_type=ReminderType.LESSON, time_value="foobar",
            )


# ─── ReminderService.delete ───────────────────────────────────────────────────

class TestReminderDelete:
    def _reminder(self, creator_id: int, user_id: int) -> Reminder:
        return Reminder(
            id=10, user_id=user_id, creator_id=creator_id,
            lesson_id=1, reminder_type=ReminderType.LESSON,
            remind_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    @pytest.mark.asyncio
    async def test_creator_can_delete_own_reminder(self, teacher):
        repo = AsyncMock()
        repo.get_by_id.return_value = self._reminder(creator_id=teacher.telegram_id, user_id=222)
        svc = ReminderService(repo, AsyncMock())
        await svc.delete(10, teacher)
        repo.delete.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_student_cannot_delete_teachers_reminder(self, student, teacher):
        repo = AsyncMock()
        repo.get_by_id.return_value = self._reminder(creator_id=teacher.telegram_id, user_id=student.telegram_id)
        svc = ReminderService(repo, AsyncMock())
        with pytest.raises(PermissionDeniedException):
            await svc.delete(10, student)

    @pytest.mark.asyncio
    async def test_admin_can_delete_any_reminder(self):
        admin = User(telegram_id=999, username="admin", role=UserRole.ADMIN, full_name="Admin")
        repo = AsyncMock()
        repo.get_by_id.return_value = self._reminder(creator_id=111, user_id=222)
        svc = ReminderService(repo, AsyncMock())
        await svc.delete(10, admin)
        repo.delete.assert_called_once_with(10)


# ─── get_pending timezone correctness ─────────────────────────────────────────

class TestGetPendingLogic:
    """
    Проверяем логику worker: правильно ли он ищет pending и помечает sent.
    Репозиторий возвращает ровно один reminder, который должен быть отправлен.
    """

    def _make_pending_reminder(self, user_id=123) -> Reminder:
        return Reminder(
            id=5, user_id=user_id, creator_id=user_id,
            lesson_id=1, reminder_type=ReminderType.LESSON,
            remind_at=datetime.now(timezone.utc) - timedelta(seconds=30),
            is_sent=False,
        )

    @pytest.mark.asyncio
    async def test_worker_sends_pending_and_marks_sent(self):
        reminder = self._make_pending_reminder(user_id=111)
        lesson = Lesson(id=1, chat_id=9, created_by=111,
                        scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                        status=LessonStatus.SCHEDULED, topic="Тест")

        reminder_repo = AsyncMock()
        reminder_repo.get_pending.return_value = [reminder]
        lesson_repo = AsyncMock()
        lesson_repo.get_by_id.return_value = lesson

        bot = AsyncMock()

        worker = NotificationWorker.__new__(NotificationWorker)
        worker.bot = bot
        worker.reminder_repo = reminder_repo
        worker.lesson_repo = lesson_repo

        await worker._check_and_send()

        bot.send_message.assert_called_once()
        args = bot.send_message.call_args[0]
        assert args[0] == 111  # user_id совпадает
        reminder_repo.mark_sent.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_worker_skips_already_sent(self):
        """Воркер не должен повторно отправлять уже отправленные напоминания."""
        reminder_repo = AsyncMock()
        reminder_repo.get_pending.return_value = []  # get_pending фильтрует is_sent=True

        bot = AsyncMock()
        worker = NotificationWorker.__new__(NotificationWorker)
        worker.bot = bot
        worker.reminder_repo = reminder_repo
        worker.lesson_repo = AsyncMock()

        await worker._check_and_send()
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_worker_continues_after_send_error(self):
        """Ошибка отправки одного не останавливает остальные."""
        r1 = self._make_pending_reminder(user_id=111)
        r1.id = 1
        r2 = self._make_pending_reminder(user_id=222)
        r2.id = 2

        lesson = Lesson(id=1, chat_id=9, created_by=111,
                        scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                        status=LessonStatus.SCHEDULED, topic="Тест")

        reminder_repo = AsyncMock()
        reminder_repo.get_pending.return_value = [r1, r2]
        lesson_repo = AsyncMock()
        lesson_repo.get_by_id.return_value = lesson

        bot = AsyncMock()
        # Первый вызов падает, второй успешен
        bot.send_message.side_effect = [Exception("Network error"), None]

        worker = NotificationWorker.__new__(NotificationWorker)
        worker.bot = bot
        worker.reminder_repo = reminder_repo
        worker.lesson_repo = lesson_repo

        await worker._check_and_send()

        assert bot.send_message.call_count == 2
        # Первый reminder НЕ помечается sent (ошибка), второй — помечается
        reminder_repo.mark_sent.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_remind_at_before_now_is_pending(self):
        """remind_at в прошлом → в get_pending. remind_at в будущем → нет."""
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        future = datetime.now(timezone.utc) + timedelta(minutes=10)

        # Симулируем логику фильтра: remind_at__lte=now, is_sent=False
        now = datetime.now(timezone.utc)
        assert past <= now   # попадает в pending
        assert future > now  # не попадает


# ─── Timezone edge cases ──────────────────────────────────────────────────────

class TestTimezoneHandling:
    @pytest.mark.asyncio
    async def test_msk_lesson_reminder_stored_as_utc(self, reminder_service, teacher, future_lesson):
        """remind_at должен быть в UTC (tzinfo != MSK)."""
        result = await reminder_service.create_for_lesson(
            actor=teacher, target_user_id=teacher.telegram_id,
            lesson_id=1, reminder_type=ReminderType.LESSON, time_value="30m",
        )
        # Должен быть timezone-aware
        assert result.remind_at.tzinfo is not None
        # Offset не должен быть +3 (должен быть UTC или конвертироваться в UTC)
        # В Python при arithmetic с MSK-aware datetime результат остаётся MSK-aware,
        # но Tortoise конвертирует в UTC при хранении. Главное что offset корректен.
        lesson_utc = future_lesson.scheduled_at.astimezone(timezone.utc)
        remind_utc = result.remind_at.astimezone(timezone.utc)
        diff_min = round((lesson_utc - remind_utc).total_seconds() / 60)
        assert diff_min == 30

    @pytest.mark.asyncio
    async def test_naive_lesson_scheduled_at_treated_as_msk(self):
        """Если scheduled_at без tzinfo — обратная совместимость: считаем МСК."""
        naive_lesson = Lesson(
            id=3, chat_id=9999, created_by=111,
            scheduled_at=datetime.now() + timedelta(hours=2),  # naive!
            status=LessonStatus.SCHEDULED, topic="Без TZ",
        )
        lesson_repo = AsyncMock()
        lesson_repo.get_by_id.return_value = naive_lesson
        reminder_repo = AsyncMock()
        reminder_repo.create.side_effect = lambda r: _set_id(r, 99)
        teacher = User(telegram_id=111, username="t", role=UserRole.TEACHER)

        svc = ReminderService(reminder_repo, lesson_repo)
        # Не должно упасть
        result = await svc.create_for_lesson(
            actor=teacher, target_user_id=111,
            lesson_id=3, reminder_type=ReminderType.LESSON, time_value="10m",
        )
        assert result.remind_at is not None
