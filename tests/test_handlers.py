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



from infrastructure.telegram.keyboards import main_menu_keyboard


def test_group_menu_hides_lesson_buttons_from_non_admin():
    """В групповом чате кнопки управления занятиями не видны студентам и учителям."""
    for role in (UserRole.STUDENT, UserRole.TEACHER):
        kb = main_menu_keyboard(role, is_group=True)
        texts = [btn.text for row in kb.keyboard for btn in row]
        assert "Добавить занятие" not in texts, f"{role}: не должна видеть 'Добавить занятие'"
        assert "Удалить занятие" not in texts, f"{role}: не должна видеть 'Удалить занятие'"


def test_group_menu_shows_lesson_buttons_to_admin():
    """В групповом чате OWNER и ADMIN видят кнопки управления занятиями."""
    for role in (UserRole.ADMIN, UserRole.OWNER):
        kb = main_menu_keyboard(role, is_group=True)
        texts = [btn.text for row in kb.keyboard for btn in row]
        assert "Добавить занятие" in texts, f"{role}: должна видеть 'Добавить занятие'"
        assert "Удалить занятие" in texts, f"{role}: должна видеть 'Удалить занятие'"


def test_private_menu_always_shows_reminder_buttons():
    """В личных сообщениях кнопки напоминаний видны всем ролям."""
    for role in (UserRole.STUDENT, UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER):
        kb = main_menu_keyboard(role, is_group=False)
        texts = [btn.text for row in kb.keyboard for btn in row]
        assert "Добавить напоминание" in texts
        assert "Удалить напоминание" in texts


def test_group_menu_hides_reminder_buttons():
    """В групповом чате кнопки напоминаний не показываются (работают только в ЛС)."""
    for role in (UserRole.STUDENT, UserRole.ADMIN, UserRole.OWNER):
        kb = main_menu_keyboard(role, is_group=True)
        texts = [btn.text for row in kb.keyboard for btn in row]
        assert "Добавить напоминание" not in texts
        assert "Удалить напоминание" not in texts
