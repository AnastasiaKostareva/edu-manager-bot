from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, Chat, User as TGUser
from domain.entities import User, UserRole

from infrastructure.telegram.handlers.private import pm_lessons as cmd_lessons
from infrastructure.telegram.states import AddReminderSG


@pytest.fixture
def mock_user():
    return User(
        telegram_id=123,
        username="testuser",
        full_name="Test User",
        role=UserRole.STUDENT,
        is_active=True
    )


@pytest.mark.asyncio
async def test_menu_interrupts_fsm(mock_user):
    """
    Тест проверяет, что нажатие кнопки меню (текст) прерывает активный FSM сценарий.
    """
    storage = MemoryStorage()
    key = MagicMock()
    state = FSMContext(storage=storage, key=key)

    await state.set_state(AddReminderSG.target)

    message = MagicMock(spec=Message)
    message.message_id = 1
    message.text = "Мои занятия"
    message.chat = Chat(id=123, type="private")
    message.from_user = TGUser(id=123, is_bot=False, first_name="Test", username="testuser")
    message.date = datetime.now()
    message.answer = AsyncMock()

    with patch('infrastructure.telegram.handlers.private.get_or_create_user', return_value=(mock_user, False)), \
         patch('infrastructure.telegram.handlers.private.lesson_service.list_for_user', return_value=[]):
        try:
            await cmd_lessons(message, state)
        except Exception:
            pass

    current_state = await state.get_state()
    assert current_state is None, "Состояние FSM должно быть сброшено кнопкой меню"


