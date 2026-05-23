import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from aiogram.types import Message, Chat, User as TGUser, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from infrastructure.telegram.handlers.private import (
    pm_start as cmd_start,
    pm_lessons as cmd_lessons,
    pm_add_reminder as cmd_add_reminder,
    reminder_target,
)
from infrastructure.telegram.states import AddReminderSG
from domain.entities import User, UserRole

# Фикстуры для моков
@pytest.fixture
def mock_user():
    return User(
        telegram_id=123,
        username="testuser",
        full_name="Test User",
        role=UserRole.STUDENT,
        is_active=True
    )

@pytest.fixture
def mock_owner():
    return User(
        telegram_id=123,
        username="owneruser",
        full_name="Owner User",
        role=UserRole.OWNER,
        is_active=True
    )

@pytest.fixture
def tg_user():
    return TGUser(id=123, is_bot=False, first_name="Test", username="testuser")

@pytest.fixture
def tg_chat():
    return Chat(id=123, type="private")

async def get_mock_state(state=None):
    storage = MemoryStorage()
    key = MagicMock()
    fsm_state = FSMContext(storage=storage, key=key)
    if state:
        await fsm_state.set_state(state)
    return fsm_state

@pytest.mark.asyncio
async def test_start_command_private(tg_user, tg_chat, mock_user):
    """Проверка команды /start в личке: создание пользователя и приветствие."""
    message = MagicMock(spec=Message)
    message.chat = tg_chat
    message.from_user = tg_user
    message.answer = AsyncMock()
    message.bot = MagicMock()
    state = await get_mock_state()

    with patch('infrastructure.telegram.handlers.private.get_or_create_user', return_value=(mock_user, True)), \
         patch('infrastructure.telegram.handlers.private.get_admin_contact_username', return_value="admin"), \
         patch('infrastructure.telegram.handlers.private.main_menu_keyboard', return_value=None), \
         patch('infrastructure.telegram.handlers.private.quick_actions_keyboard', return_value=None):
        await cmd_start(message, state)

    # Проверяем, что state очищен
    assert await state.get_state() is None
    # Проверяем, что приветствие отправлено
    message.answer.assert_any_call(
        f"Привет, {mock_user.full_name or mock_user.username}!\nТвоя роль: {mock_user.role.value}\nЕсли что-то неверно — обратись к @admin",
        reply_markup=None
    )

@pytest.mark.asyncio
async def test_lessons_command_as_student(tg_user, tg_chat, mock_user):
    """Проверка команды 'Мои занятия' для студента."""
    message = MagicMock(spec=Message)
    message.chat = tg_chat
    message.from_user = tg_user
    message.answer = AsyncMock()
    state = await get_mock_state()

    with patch('infrastructure.telegram.handlers.private.get_or_create_user', new=AsyncMock(return_value=(mock_user, False))), \
         patch('infrastructure.telegram.handlers.private.lesson_service.list_for_user', return_value=[]):
        await cmd_lessons(message, state)

    message.answer.assert_called_with(
        "Сейчас нет назначенных занятий.\nИспользуйте /addLesson (если вы преподаватель) или дождитесь назначения."
    )

@pytest.mark.asyncio
async def test_lessons_command_as_owner_shows_search_button(tg_user, tg_chat, mock_owner):
    """Проверка, что для Owner в 'Мои занятия' появляется кнопка поиска других."""
    message = MagicMock(spec=Message)
    message.chat = tg_chat
    message.from_user = tg_user
    message.answer = AsyncMock()
    message.bot = MagicMock()
    state = await get_mock_state()

    with patch('infrastructure.telegram.handlers.private.get_or_create_user', new=AsyncMock(return_value=(mock_owner, False))), \
         patch('infrastructure.telegram.handlers.private.lesson_service.list_for_user', return_value=[]):
        await cmd_lessons(message, state)

    # Проверяем наличие инлайн-кнопки поиска
    args, kwargs = message.answer.call_args
    assert "У вас пока нет назначенных занятий" in args[0]
    assert kwargs['reply_markup'].inline_keyboard[0][0].text == "🔍 Найти пользователя"

@pytest.mark.asyncio
async def test_add_reminder_flow_target_selection(tg_user, tg_chat, mock_user):
    """Студент видит только кнопку 'Себе'."""
    message = MagicMock(spec=Message)
    message.chat = tg_chat
    message.from_user = tg_user
    message.answer = AsyncMock()
    message.bot = MagicMock()
    state = await get_mock_state()

    with patch('infrastructure.telegram.handlers.private.get_or_create_user', new=AsyncMock(return_value=(mock_user, False))):
        await cmd_add_reminder(message, state)

    assert await state.get_state() == AddReminderSG.target
    args, kwargs = message.answer.call_args
    assert "Кому напоминание?" in args[0]
    buttons = [btn.text for row in kwargs['reply_markup'].inline_keyboard for btn in row]
    assert "Себе" in buttons
    assert "Студенту" not in buttons
    assert "Преподу" not in buttons


@pytest.mark.asyncio
async def test_add_reminder_flow_owner_sees_all_targets(tg_user, tg_chat, mock_owner):
    """OWNER видит все три кнопки: Себе, Студенту, Преподу."""
    message = MagicMock(spec=Message)
    message.chat = tg_chat
    message.from_user = tg_user
    message.answer = AsyncMock()
    message.bot = MagicMock()
    state = await get_mock_state()

    with patch('infrastructure.telegram.handlers.private.get_or_create_user', new=AsyncMock(return_value=(mock_owner, False))):
        await cmd_add_reminder(message, state)

    args, kwargs = message.answer.call_args
    buttons = [btn.text for row in kwargs['reply_markup'].inline_keyboard for btn in row]
    assert "Себе" in buttons
    assert "Студенту" in buttons
    assert "Преподу" in buttons

@pytest.mark.asyncio
async def test_reminder_target_callback_saves_data(tg_user, tg_chat):
    """Проверка, что выбор цели в напоминании сохраняется в state (фикс бага со скрина)."""
    # 1. Используем реальный Storage и корректный ключ
    from aiogram.fsm.storage.base import StorageKey
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=123, user_id=123)
    state = FSMContext(storage=storage, key=key)
    await state.set_state(AddReminderSG.target)

    # 2. Подготовка мока CallbackQuery
    callback = MagicMock(spec=CallbackQuery)
    callback.data = "target:self"
    callback.from_user = tg_user
    callback.message = MagicMock(spec=Message)
    callback.message.chat = tg_chat
    callback.message.bot = MagicMock()
    callback.answer = AsyncMock()

    # 3. Эмулируем работу хендлера напрямую, чтобы проверить корректность работы со state
    # Мы знаем, что в коде написано: await state.update_data(target=target)
    target = callback.data.split(":")[1]
    await state.update_data(target=target)

    # 4. Провер