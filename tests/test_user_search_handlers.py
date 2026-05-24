"""
Handler-level tests for the user search flow (task 8).

Tests the full UX path:
  Admin/Owner presses "Мои занятия"
    → presses "🔍 Найти пользователя"
    → pm_user_search_start  →  state set to UserSearchSG.waiting_for_user_search_query
    → types query
    → pm_user_search_query  →  0 / 1 / N results
    → (if N > 1) presses a result button
    → pm_user_search_select →  shows that user's lessons
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import (
    CallbackQuery, Chat, Message, User as TGUser,
)

from domain.entities import Lesson, LessonStatus, User, UserRole
from infrastructure.telegram.handlers.private import (
    pm_user_search_start,
    pm_user_search_query,
    pm_user_search_select,
    _show_user_lessons,
)
from infrastructure.telegram.states import UserSearchSG


# ─── helpers ─────────────────────────────────────────────────────────────────

def _tg_user(uid=123, username="admin") -> TGUser:
    return TGUser(id=uid, is_bot=False, first_name="Test", username=username)


def _private_chat(cid=123) -> Chat:
    return Chat(id=cid, type="private")


async def _make_state(initial=None) -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=123, user_id=123)
    ctx = FSMContext(storage=storage, key=key)
    if initial:
        await ctx.set_state(initial)
    return ctx


def _domain_user(tid=123, role=UserRole.ADMIN) -> User:
    return User(telegram_id=tid, username="admin", role=role, full_name="Admin")


def _lesson(lid=1) -> Lesson:
    from datetime import datetime, timezone
    return Lesson(
        id=lid, chat_id=999, created_by=42,
        scheduled_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        status=LessonStatus.SCHEDULED, topic="Алгебра",
    )


def _make_callback(data: str, uid=123) -> CallbackQuery:
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.from_user = _tg_user(uid)
    msg = MagicMock(spec=Message)
    msg.chat = _private_chat()
    msg.answer = AsyncMock()
    msg.edit_text = AsyncMock()
    msg.edit_reply_markup = AsyncMock()
    cb.message = msg
    cb.answer = AsyncMock()
    return cb


def _make_message(text: str, uid=123) -> Message:
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.from_user = _tg_user(uid)
    msg.chat = _private_chat()
    msg.answer = AsyncMock()
    return msg


# ─── pm_user_search_start ────────────────────────────────────────────────────

class TestSearchStart:
    @pytest.mark.asyncio
    async def test_admin_gets_state_set(self):
        cb = _make_callback("search_user_start")
        state = await _make_state()

        with patch("infrastructure.telegram.handlers.private.get_or_create_user",
                   new=AsyncMock(return_value=(_domain_user(role=UserRole.ADMIN), False))):
            await pm_user_search_start(cb, state)

        assert await state.get_state() == UserSearchSG.waiting_for_user_search_query

    @pytest.mark.asyncio
    async def test_owner_gets_state_set(self):
        cb = _make_callback("search_user_start")
        state = await _make_state()

        with patch("infrastructure.telegram.handlers.private.get_or_create_user",
                   new=AsyncMock(return_value=(_domain_user(role=UserRole.OWNER), False))):
            await pm_user_search_start(cb, state)

        assert await state.get_state() == UserSearchSG.waiting_for_user_search_query

    @pytest.mark.asyncio
    async def test_student_is_rejected(self):
        cb = _make_callback("search_user_start")
        state = await _make_state()

        with patch("infrastructure.telegram.handlers.private.get_or_create_user",
                   new=AsyncMock(return_value=(_domain_user(role=UserRole.STUDENT), False))):
            await pm_user_search_start(cb, state)

        # State must NOT be set
        assert await state.get_state() is None
        cb.answer.assert_called_once()
        _, kwargs = cb.answer.call_args
        assert kwargs.get("show_alert") is True

    @pytest.mark.asyncio
    async def test_teacher_is_rejected(self):
        cb = _make_callback("search_user_start")
        state = await _make_state()

        with patch("infrastructure.telegram.handlers.private.get_or_create_user",
                   new=AsyncMock(return_value=(_domain_user(role=UserRole.TEACHER), False))):
            await pm_user_search_start(cb, state)

        assert await state.get_state() is None

    @pytest.mark.asyncio
    async def test_bot_asks_for_query_text(self):
        cb = _make_callback("search_user_start")
        state = await _make_state()

        with patch("infrastructure.telegram.handlers.private.get_or_create_user",
                   new=AsyncMock(return_value=(_domain_user(role=UserRole.ADMIN), False))):
            await pm_user_search_start(cb, state)

        cb.message.answer.assert_called_once()
        text = cb.message.answer.call_args[0][0]
        assert "username" in text.lower() or "имя" in text.lower() or "введите" in text.lower()


# ─── pm_user_search_query ────────────────────────────────────────────────────

class TestSearchQuery:
    @pytest.mark.asyncio
    async def test_empty_query_shows_error(self):
        msg = _make_message("   ")
        state = await _make_state(UserSearchSG.waiting_for_user_search_query)

        with patch("infrastructure.telegram.handlers.private.user_service") as svc:
            await pm_user_search_query(msg, state)

        svc.search_users.assert_not_called()
        msg.answer.assert_called_once()
        assert "пустой" in msg.answer.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_no_results_shows_not_found_message(self):
        msg = _make_message("@nonexistent")
        state = await _make_state(UserSearchSG.waiting_for_user_search_query)

        with patch("infrastructure.telegram.handlers.private.user_service") as svc:
            svc.search_users = AsyncMock(return_value=[])
            await pm_user_search_query(msg, state)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        assert "не найден" in text.lower()

    @pytest.mark.asyncio
    async def test_no_results_message_does_not_say_no_lessons(self):
        """Если юзер не найден, бот не должен говорить 'нет занятий'."""
        msg = _make_message("@ghost")
        state = await _make_state(UserSearchSG.waiting_for_user_search_query)

        with patch("infrastructure.telegram.handlers.private.user_service") as svc:
            svc.search_users = AsyncMock(return_value=[])
            await pm_user_search_query(msg, state)

        text = msg.answer.call_args[0][0]
        assert "нет занятий" not in text.lower()

    @pytest.mark.asyncio
    async def test_single_result_shows_lessons(self):
        target = _domain_user(tid=999, role=UserRole.STUDENT)
        msg = _make_message("@student")
        state = await _make_state(UserSearchSG.waiting_for_user_search_query)

        with patch("infrastructure.telegram.handlers.private.user_service") as svc, \
             patch("infrastructure.telegram.handlers.private.lesson_service") as lsvc:
            svc.search_users = AsyncMock(return_value=[target])
            lsvc.list_for_user = AsyncMock(return_value=[_lesson()])
            await pm_user_search_query(msg, state)

        lsvc.list_for_user.assert_called_once_with(999)
        msg.answer.assert_called_once()
        assert "алгебра" in msg.answer.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_single_result_no_lessons_says_no_lessons(self):
        target = _domain_user(tid=999, role=UserRole.STUDENT)
        msg = _make_message("@student")
        state = await _make_state(UserSearchSG.waiting_for_user_search_query)

        with patch("infrastructure.telegram.handlers.private.user_service") as svc, \
             patch("infrastructure.telegram.handlers.private.lesson_service") as lsvc:
            svc.search_users = AsyncMock(return_value=[target])
            lsvc.list_for_user = AsyncMock(return_value=[])
            await pm_user_search_query(msg, state)

        text = msg.answer.call_args[0][0]
        assert "нет занятий" in text.lower()

    @pytest.mark.asyncio
    async def test_multiple_results_shows_selection_keyboard(self):
        users = [
            _domain_user(tid=1, role=UserRole.STUDENT),
            _domain_user(tid=2, role=UserRole.STUDENT),
        ]
        users[0].username = "alice"
        users[1].username = "bob"

        msg = _make_message("ivan")
        state = await _make_state(UserSearchSG.waiting_for_user_search_query)

        with patch("infrastructure.telegram.handlers.private.user_service") as svc:
            svc.search_users = AsyncMock(return_value=users)
            await pm_user_search_query(msg, state)

        args, kwargs = msg.answer.call_args
        kb = kwargs.get("reply_markup")
        assert kb is not None
        # Two buttons — one per user
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(all_buttons) == 2

    @pytest.mark.asyncio
    async def test_state_cleared_after_query(self):
        msg = _make_message("@alice")
        state = await _make_state(UserSearchSG.waiting_for_user_search_query)

        with patch("infrastructure.telegram.handlers.private.user_service") as svc:
            svc.search_users = AsyncMock(return_value=[])
            await pm_user_search_query(msg, state)

        assert await state.get_state() is None


# ─── pm_user_search_select ───────────────────────────────────────────────────

class TestSearchSelect:
    @pytest.mark.asyncio
    async def test_shows_target_lessons(self):
        target = _domain_user(tid=777, role=UserRole.STUDENT)
        cb = _make_callback("search_sel:777")

        with patch("infrastructure.telegram.handlers.private.get_or_create_user",
                   new=AsyncMock(return_value=(_domain_user(role=UserRole.ADMIN), False))), \
             patch("infrastructure.telegram.handlers.private.user_repo") as repo, \
             patch("infrastructure.telegram.handlers.private.lesson_service") as lsvc:
            repo.get_by_telegram_id = AsyncMock(return_value=target)
            lsvc.list_for_user = AsyncMock(return_value=[_lesson()])
            await pm_user_search_select(cb)

        lsvc.list_for_user.assert_called_once_with(777)
        cb.message.answer.assert_called_once()
        assert "алгебра" in cb.message.answer.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_student_cannot_select(self):
        cb = _make_callback("search_sel:999")

        with patch("infrastructure.telegram.handlers.private.get_or_create_user",
                   new=AsyncMock(return_value=(_domain_user(role=UserRole.STUDENT), False))):
            await pm_user_search_select(cb)

        cb.answer.assert_called_once()
        _, kwargs = cb.answer.call_args
        assert kwargs.get("show_alert") is True
        cb.message.answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_target_shows_error(self):
        cb = _make_callback("search_sel:9999")

        with patch("infrastructure.telegram.handlers.private.get_or_create_user",
                   new=AsyncMock(return_value=(_domain_user(role=UserRole.ADMIN), False))), \
             patch("infrastructure.telegram.handlers.private.user_repo") as repo:
            repo.get_by_telegram_id = AsyncMock(return_value=None)
            await pm_user_search_select(cb)

        cb.message.edit_text.assert_called_once()
        text = cb.message.edit_text.call_args[0][0]
        assert "не доступен" in text.lower() or "не найден" in text.lower()

    @pytest.mark.asyncio
    async def test_keyboard_removed_after_selection(self):
        target = _domain_user(tid=777, role=UserRole.STUDENT)
        cb = _make_callback("search_sel:777")

        with patch("infrastructure.telegram.handlers.private.get_or_create_user",
                   new=AsyncMock(return_value=(_domain_user(role=UserRole.ADMIN), False))), \
             patch("infrastructure.telegram.handlers.private.user_repo") as repo, \
             patch("infrastructure.telegram.handlers.private.lesson_service") as lsvc:
            repo.get_by_telegram_id = AsyncMock(return_value=target)
            lsvc.list_for_user = AsyncMock(return_value=[])
            await pm_user_search_select(cb)

        cb.message.edit_reply_markup.assert_called_once_with(reply_markup=None)


# ─── _show_user_lessons ───────────────────────────────────────────────────────

class TestShowUserLessons:
    @pytest.mark.asyncio
    async def test_formats_lesson_list(self):
        target = _domain_user(tid=1, role=UserRole.STUDENT)
        target.full_name = "Иван Иванов"
        msg = MagicMock(spec=Message)
        msg.answer = AsyncMock()

        with patch("infrastructure.telegram.handlers.private.lesson_service") as lsvc:
            lsvc.list_for_user = AsyncMock(return_value=[_lesson(1), _lesson(2)])
            await _show_user_lessons(msg, target)

        text = msg.answer.call_args[0][0]
        assert "Иван Иванов" in text
        assert "Алгебра" in text

    @pytest.mark.asyncio
    async def test_no_lessons_message_contains_username_not_none(self):
        target = User(telegram_id=5, username=None, role=UserRole.STUDENT, full_name=None)
        msg = MagicMock(spec=Message)
        msg.answer = AsyncMock()

        with patch("infrastructure.telegram.handlers.private.lesson_service") as lsvc:
            lsvc.list_for_user = AsyncMock(return_value=[])
            await _show_user_lessons(msg, target)

        text = msg.answer.call_args[0][0]
        assert "None" not in text
