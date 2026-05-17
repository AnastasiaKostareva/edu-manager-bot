import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta, timezone

from infrastructure.monitoring.scheduler import Scheduler
from domain.entities import Lesson, StartNotificationLevel, LessonStatus

class TestSchedulerCompletions:
    @pytest.fixture
    def mock_bot(self):
        return AsyncMock()

    @pytest.fixture
    def scheduler(self, mock_bot):
        with patch('infrastructure.monitoring.scheduler.ReminderRepository'), \
                patch('infrastructure.monitoring.scheduler.LessonRepository') as MockLessonRepo, \
                patch('infrastructure.monitoring.scheduler.ChatRepository'), \
                patch('infrastructure.monitoring.scheduler.UserRepository') as MockUserRepo, \
                patch('infrastructure.monitoring.scheduler.ChatMemberRepository'), \
                patch('infrastructure.monitoring.scheduler.LessonService') as MockLessonService:
            sched = Scheduler(bot=mock_bot)
            sched.lesson_repo = MockLessonRepo()
            sched.user_repo = MockUserRepo()
            sched.lesson_service = MockLessonService()
            return sched

    def create_mock_lesson(self, start_notification_level, time_passed_minutes):
        now = datetime.now(timezone.utc)
        scheduled_at = now - timedelta(minutes=time_passed_minutes)

        lesson = Lesson(
            id=1,
            chat_id=123,
            created_by=456,
            topic="Test Lesson",
            scheduled_at=scheduled_at,
            status=LessonStatus.SCHEDULED,
            start_notification_level=start_notification_level
        )
        return lesson

    @pytest.mark.asyncio
    async def test_transitions_from_none_to_started_when_time_passed(self, scheduler, mock_bot):
        lesson = self.create_mock_lesson(StartNotificationLevel.NONE, 0)
        scheduler.lesson_service.get_lessons_needing_completion = AsyncMock(return_value=[lesson])
        scheduler.lesson_repo.update = AsyncMock()

        await scheduler._check_lesson_completions()

        assert lesson.start_notification_level == StartNotificationLevel.STARTED
        scheduler.lesson_repo.update.assert_called_once_with(lesson)
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_transitions_from_started_to_late_10_min_when_10_minutes_passed(self, scheduler, mock_bot):
        lesson = self.create_mock_lesson(StartNotificationLevel.STARTED, 10)
        scheduler.lesson_service.get_lessons_needing_completion = AsyncMock(return_value=[lesson])
        scheduler.lesson_repo.update = AsyncMock()

        await scheduler._check_lesson_completions()

        assert lesson.start_notification_level == StartNotificationLevel.LATE_10_MIN
        scheduler.lesson_repo.update.assert_called_once_with(lesson)
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_transitions_from_late_10_min_to_late_30_min_when_30_minutes_passed(self, scheduler, mock_bot):
        lesson = self.create_mock_lesson(StartNotificationLevel.LATE_10_MIN, 30)
        scheduler.lesson_service.get_lessons_needing_completion = AsyncMock(return_value=[lesson])
        scheduler.user_repo.get_all_admins = AsyncMock(return_value=[])
        scheduler.lesson_repo.update = AsyncMock()

        await scheduler._check_lesson_completions()

        assert lesson.start_notification_level == StartNotificationLevel.LATE_30_MIN
        scheduler.lesson_repo.update.assert_called_once_with(lesson)
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_transition_when_time_is_less_than_threshold(self, scheduler, mock_bot):
        lesson = self.create_mock_lesson(StartNotificationLevel.STARTED, 5)
        scheduler.lesson_service.get_lessons_needing_completion = AsyncMock(return_value=[lesson])
        scheduler.lesson_repo.update = AsyncMock()

        await scheduler._check_lesson_completions()

        assert lesson.start_notification_level == StartNotificationLevel.STARTED
        scheduler.lesson_repo.update.assert_not_called()
        mock_bot.send_message.assert_not_called()
