from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import calendar
from datetime import datetime, timedelta

import re
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, \
    InlineKeyboardButton

from application.config import get_config
from application.use_cases.auth import AuthService
from application.use_cases.lesson import LessonService
from application.use_cases.reminder import ReminderService
from application.use_cases.chat import ChatService
from application.use_cases.analytics import AnalyticsService
from application.use_cases.statistics import StatisticsService
from domain.entities import LessonStatus, ReminderTime, ReminderType, \
    RepeatType, User, UserRole, Chat
from domain.exceptions import PermissionDeniedException, ValidationException
from infrastructure.database.repositories import (
    LessonRepository,
    ReminderRepository,
    UserRepository,
    ChatRepository,
    ChatMemberRepository,
)
from infrastructure.telegram.states import AddLessonSG, AddReminderSG, \
    RemoveLessonSG, RemoveReminderSG, SqlConsoleSG, CompleteLessonSG
from infrastructure.telegram.keyboards import main_menu_keyboard, \
    quick_actions_keyboard

router = Router()

user_repo = UserRepository()
lesson_repo = LessonRepository()
reminder_repo = ReminderRepository()
chat_repo = ChatRepository()
chat_member_repo = ChatMemberRepository()

auth_service = AuthService()
lesson_service = LessonService(lesson_repo)
reminder_service = ReminderService(reminder_repo, lesson_repo)
chat_service = ChatService(chat_repo, chat_member_repo, user_repo)
analytics_service = AnalyticsService()
statistics_service = StatisticsService()


# ==========================================
# СОСТОЯНИЯ ДЛЯ ГРУППОВОЙ РЕГИСТРАЦИИ
# ==========================================
class GroupRegSG(StatesGroup):
    input_username = State()
    role_selection = State()
    name_input = State()
    confirmation = State()


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def get_user_role(telegram_id: int) -> UserRole:
    config = get_config()
    admin_ids = {str(admin_id).strip() for admin_id in config.admins}
    return UserRole.OWNER if str(
        telegram_id) in admin_ids else UserRole.STUDENT


async def get_or_create_user(message: Message) -> tuple[User, bool]:
    existing = await user_repo.get_by_telegram_id(message.from_user.id)
    expected_role = get_user_role(message.from_user.id)

    if existing:
        updated = False
        if expected_role == UserRole.OWNER and existing.role != UserRole.OWNER:
            existing.role = UserRole.OWNER
            updated = True

        username = message.from_user.username or ""
        full_name = message.from_user.full_name
        if existing.username != username:
            existing.username = username
            updated = True
        if existing.full_name != full_name:
            existing.full_name = full_name
            updated = True

        if updated:
            await user_repo.update(existing)

        return existing, True

    user = User(
        telegram_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
        role=expected_role,
        is_active=True,
    )
    created = await user_repo.create(user)
    return created, False


async def get_user_or_reply(message: Message) -> User | None:
    user = await user_repo.get_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer(
            "Не могу найти тебя в системе.\nОбратись к @admin")
        return None
    return user


def _chat_title_and_type(message: Message) -> tuple[str, str]:
    chat_title = message.chat.title or message.chat.full_name or "Личный чат"
    chat_type = message.chat.type
    return chat_title, chat_type


async def ensure_chat_exists(message: Message) -> None:
    existing = await chat_repo.get_by_id(message.chat.id)
    if existing:
        return

    chat_title, chat_type = _chat_title_and_type(message)
    chat = Chat(
        chat_id=message.chat.id,
        chat_title=chat_title,
        chat_type=chat_type,
        created_at=datetime.utcnow(),
        is_active=True,
    )
    await chat_repo.create(chat)


async def _get_admin_contact_username() -> str:
    config = get_config()
    for admin_id_str in config.admins:
        try:
            admin_id = int(admin_id_str)
            user = await user_repo.get_by_telegram_id(admin_id)
            if user and user.username:
                return user.username
        except (ValueError, TypeError):
            continue
    return "admin"


def _build_role_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ученик",
                              callback_data="reg_role:student")],
        [InlineKeyboardButton(text="Преподаватель",
                              callback_data="reg_role:teacher")],
        [InlineKeyboardButton(text="Родитель",
                              callback_data="reg_role:parent")],
    ])


def _build_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Верно", callback_data="reg_confirm:yes")],
        [InlineKeyboardButton(text="Ошибся", callback_data="reg_confirm:no")],
    ])


# ==========================================
# ЛОГИКА ПРИВАТНОГО ЧАТА
# ==========================================
async def _handle_private_start(message: Message, state: FSMContext):
    config = get_config()
    admin_ids = {str(a).strip() for a in config.admins}
    sender_id = str(message.from_user.id)
    admin_contact = await _get_admin_contact_username()

    if sender_id in admin_ids:
        user, _ = await get_or_create_user(message)
        await message.answer(
            f"Приветствую, {user.full_name or user.username}!\n"
            f"Твоя роль: {user.role.value}\n"
            f"Если что-то неверно, то обратись к @{admin_contact} за помощью",
            reply_markup=main_menu_keyboard(user.role)
        )
        await message.answer("Быстрые действия:",
                             reply_markup=quick_actions_keyboard(user.role, is_group=False))
        return

    user = await user_repo.get_by_telegram_id(message.from_user.id)
    if user:
        await message.answer(
            f"Приветствую, {user.full_name or user.username}!\n"
            f"Твоя роль: {user.role.value}\n"
            f"Если что-то неверно, то обратись к @{admin_contact} за помощью",
            reply_markup=main_menu_keyboard(user.role)
        )
        await message.answer("Быстрые действия:",
                             reply_markup=quick_actions_keyboard(user.role, is_group=False))
    else:
        await message.answer(
            f"Не могу найти тебя в системе.\n"
            f"Обратись к @{admin_contact} за помощью"
        )


# ==========================================
# ЛОГИКА ГРУППОВОГО ЧАТА
# ==========================================
async def _handle_group_start(message: Message, state: FSMContext):
    await message.answer(
        "Приветствую, это Бот-помощник для проведения онлайн занятий.\n"
        "Расскажи мне об участниках и можем стартовать!\n\n"
        "⚠️ Telegram API не позволяет ботам автоматически получать ID участников.\n"
        "Пожалуйста, введите @username первого участника (или отправьте /done для завершения):"
    )
    await state.set_data({
        "members": [],
        "chat_id": message.chat.id,
        "idx": 0
    })
    await state.set_state(GroupRegSG.input_username)


@router.message(Command("done"), StateFilter(GroupRegSG.input_username))
async def _finish_username_input(message: Message, state: FSMContext):
    data = await state.get_data()
    members = data.get("members", [])

    if not members:
        await message.answer("✅ В чате нет участников для регистрации.")
        await state.clear()
        return

    await state.update_data(idx=0)
    await state.set_state(GroupRegSG.role_selection)
    await _ask_role_for_current_member(message, state)


# В начале файла, замените текущий USERNAME_PATTERN на:
USERNAME_PATTERN = re.compile(r'^@([a-zA-Z0-9_]{5,32})$')

@router.message(StateFilter(GroupRegSG.input_username))
async def _handle_username_input(message: Message, state: FSMContext):
    text = message.text.strip()
    logger.info(text)

    # Пропускаем команды, их обрабатывают другие хендлеры (опционально)
    if text.startswith("/"):
        await message.answer(
            "⚠️ Неверный формат. Пример: @ivan_ivanov или /done")
        return

    match = USERNAME_PATTERN.match(text)
    if not match:
        await message.answer(
            "⚠️ Неверный формат. Введите @username (без пробелов).\n"
            "Пример: @ivan_ivanov или /done для завершения.")
        return

    username = match.group(1)  # username без '@'
    data = await state.get_data()
    members = data.get("members", [])

    if any(m.get("username") == username for m in members):
        await message.answer(f"⚠️ @{username} уже в списке.")
        return

    # Пытаемся найти реальный ID. Если нет — ставим 0 (временный плейсхолдер)
    existing = await user_repo.get_by_username(username)
    user_id = existing.telegram_id if existing else 0

    members.append({"username": username, "id": user_id})
    await state.update_data(members=members)
    await message.answer(
        f"✅ @{username} добавлен. Введите следующего или /done:")


async def _ask_role_for_current_member(message: Message, state: FSMContext):
    data = await state.get_data()
    idx = data.get("idx", 0)
    members = data.get("members", [])

    if idx >= len(members):
        await _finish_group_registration(message, state)
        return

    current_user = members[idx]
    await state.update_data(current_user=current_user)
    await message.answer(f"Кто @{current_user['username']}?",
                         reply_markup=_build_role_keyboard())


async def _finish_group_registration(message: Message, state: FSMContext):
    await state.clear()

    # Определяем роль отправителя, чтобы показать соответствующие кнопки
    user = await user_repo.get_by_telegram_id(message.from_user.id)
    role = user.role if user else UserRole.STUDENT

    await message.answer(
        "✅ Регистрация успешно прошла, готов к работе!",
        reply_markup=main_menu_keyboard(role, is_group=True)
    )
    await message.answer(
        "Быстрые действия:",
        reply_markup=quick_actions_keyboard(role, is_group=True)
    )


# ==========================================
# FSM ХЕНДЛЕРЫ ГРУППОВОЙ РЕГИСТРАЦИИ
# ==========================================
@router.callback_query(F.data.startswith("reg_role:"),
                       GroupRegSG.role_selection)
async def _handle_role_selection(callback: CallbackQuery, state: FSMContext):
    role_value = callback.data.split(":", 1)[1]
    await state.update_data(temp_role=role_value)
    await state.set_state(GroupRegSG.name_input)

    data = await state.get_data()
    username = data["current_user"]["username"]
    await callback.message.edit_text(f"Как зовут @{username}?")
    await callback.answer()


@router.message(GroupRegSG.name_input)
async def _handle_name_input(message: Message, state: FSMContext):
    full_name = message.text.strip()
    if not full_name:
        await message.answer("Пожалуйста, введите имя и фамилию.")
        return

    await state.update_data(temp_name=full_name)
    await state.set_state(GroupRegSG.confirmation)

    data = await state.get_data()
    username = data["current_user"]["username"]
    role_display = {
        "student": "Ученик",
        "teacher": "Преподаватель",
        "parent": "Родитель"
    }.get(data["temp_role"], data["temp_role"])

    await message.answer(
        f"Запомнил! @{username} - {full_name}\nРоль - {role_display}",
        reply_markup=_build_confirmation_keyboard()
    )


@router.callback_query(F.data.startswith("reg_confirm:"),
                       GroupRegSG.confirmation)
async def _handle_confirmation(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()

    if action == "no":
        await state.set_state(GroupRegSG.role_selection)
        await _ask_role_for_current_member(callback.message, state)
        await callback.answer()
        return

    current_user = data["current_user"]
    username = current_user["username"]

    # Гарантируем non-null ID. Если юзер не писал боту, ставим 0.
    # Telegram ID всегда > 0, поэтому 0 безопасен как временный маркер.
    telegram_id = current_user.get("id") or 0

    role_map = {
        "student": UserRole.STUDENT,
        "teacher": UserRole.TEACHER,
        "parent": UserRole.STUDENT,
    }

    new_user = User(
        telegram_id=telegram_id,
        username=username if "ID_" not in username else "",
        full_name=data["temp_name"],
        role=role_map.get(data["temp_role"], UserRole.STUDENT),
        is_active=True,
    )

    # Логика Upsert: если юзер уже есть — обновляем, если нет — создаём
    existing_by_id = await user_repo.get_by_telegram_id(
        telegram_id) if telegram_id != 0 else None
    existing_by_username = await user_repo.get_by_username(username)
    existing = existing_by_id or existing_by_username

    if existing:
        existing.full_name = new_user.full_name
        existing.role = new_user.role
        await user_repo.update(existing)
    else:
        try:
            await user_repo.create(new_user)
        except Exception:
            pass  # Игнорируем конфликты уникальности, если запись уже появилась

    await state.update_data(idx=data["idx"] + 1)
    await state.set_state(GroupRegSG.role_selection)
    await _ask_role_for_current_member(callback.message, state)
    await callback.answer()


# ==========================================
# ОСНОВНОЙ ХЕНДЛЕР /start
# ==========================================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.chat.type == "private":
        await _handle_private_start(message, state)
    else:
        await _handle_group_start(message, state)


# ==========================================
# ВСЕ ОСТАЛЬНЫЕ ХЕНДЛЕРЫ (БЕЗ ИЗМЕНЕНИЙ)
# ==========================================
@router.message(F.text == "Мои занятия")
async def menu_lessons(message: Message, state: FSMContext):
    await cmd_lessons(message, state)


@router.message(F.text == "Добавить занятие")
async def menu_add_lesson(message: Message, state: FSMContext):
    await cmd_add_lesson(message, state)


@router.message(F.text == "Удалить занятие")
async def menu_remove_lesson(message: Message, state: FSMContext):
    await cmd_remove_lesson(message, state)


@router.message(F.text == "Добавить напоминание")
async def menu_add_reminder(message: Message, state: FSMContext):
    await cmd_add_reminder(message, state)


@router.message(F.text == "Удалить напоминание")
async def menu_remove_reminder(message: Message, state: FSMContext):
    await cmd_remove_reminder(message, state)


@router.message(F.text == "Статистика")
async def menu_stats(message: Message):
    await cmd_stats(message)


@router.message(F.text == "SQL консоль")
async def menu_sql(message: Message, state: FSMContext):
    await cmd_sql(message, state)


@router.callback_query(F.data.startswith("ux:"))
async def ux_callback_router(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":", 1)[1]

    if action == "lessons":
        await cmd_lessons(callback.message, state)
    elif action == "add_lesson":
        await cmd_add_lesson(callback.message, state)
    elif action == "add_reminder":
        await cmd_add_reminder(callback.message, state)
    elif action == "stats":
        await cmd_stats(callback.message)
    elif action == "sql":
        await cmd_sql(callback.message, state)
    else:
        await callback.message.answer("Неизвестное действие")

    await callback.answer()


@router.message(Command("lessons"))
async def cmd_lessons(message: Message, state: FSMContext):
    user = await get_user_or_reply(message)
    if not user:
        return

    if user.role in (UserRole.ADMIN, UserRole.OWNER):
        await message.answer("Введите тег пользователя")
        await state.set_state("admin_find_user")
        return

    lessons = await lesson_service.list_for_user(user.telegram_id)
    if not lessons:
        await message.answer(
            "Сейчас нет назначенных занятий\nИспользуй /addLesson")
        return

    text = "Ваши занятия:\n" + "\n".join(
        f"{i + 1}) {l.topic} — {l.scheduled_at.strftime('%d:%m %H:%M')}" for
        i, l in enumerate(lessons)
    )
    await message.answer(text)


@router.message(StateFilter("admin_find_user"))
async def admin_find_user(message: Message, state: FSMContext):
    user = await user_repo.get_by_username(message.text.lstrip("@"))
    if not user:
        await message.answer("Пользователь не найден")
        return

    lessons = await lesson_service.list_for_user(user.telegram_id)
    if not lessons:
        await message.answer("Нет занятий")
        await state.clear()
        return

    text = f"Занятия пользователя {user.username}:\n" + "\n".join(
        f"{i + 1}) {l.topic} — {l.scheduled_at.strftime('%d:%m %H:%M')}" for
        i, l in enumerate(lessons)
    )
    await message.answer(text)
    await state.clear()


# ==========================================
# ДОБАВЛЕНИЕ ЗАНЯТИЯ (НОВЫЙ ПОРЯДОК)
# ==========================================

@router.message(Command("addLesson"))
@router.message(F.text == "Добавить занятие")
async def cmd_add_lesson(message: Message, state: FSMContext):
    user = await get_user_or_reply(message)
    if not user:
        return
    try:
        auth_service.ensure_role(user, [UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER])
    except PermissionDeniedException:
        await message.answer("У вас нет доступа к этой команде")
        return

    await ensure_chat_exists(message)

    await message.answer("Введите тему занятия")
    await state.set_state(AddLessonSG.topic)


@router.message(AddLessonSG.topic)
async def add_lesson_topic(message: Message, state: FSMContext):
    topic = message.text.strip()
    if not topic:
        await message.answer("Тема не может быть пустой. Попробуйте ещё раз.")
        return

    await state.update_data(topic=topic)

    # Формируем клавиатуру с днями недели
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=day, callback_data=f"weekday:{i}")]
            for i, day in enumerate(days)
        ]
    )

    await message.answer(
        "Выберите день, когда хотите провести занятие, или введите дату, "
        "если занятие не в ближайшую неделю (формат дд:мм):",
        reply_markup=kb
    )
    await state.set_state(AddLessonSG.day_selection)


@router.callback_query(F.data.startswith("weekday:"), AddLessonSG.day_selection)
async def add_lesson_weekday_selected(callback: CallbackQuery, state: FSMContext):
    weekday_index = int(callback.data.split(":")[1])  # 0 = Пн, 6 = Вс
    # Преобразуем в Python weekday (0 = Пн, 6 = Вс)
    today = datetime.now().date()
    # Находим ближайшую дату с нужным днём недели (включая сегодня)
    days_ahead = (weekday_index - today.weekday()) % 7
    target_date = today + timedelta(days=days_ahead if days_ahead > 0 else 7)

    await state.update_data(target_date=target_date)
    await callback.message.edit_text(
        f"Выбран день: {target_date.strftime('%d.%m.%Y')} ({['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][weekday_index]})\n"
        f"Теперь введите время занятия (чч:мм):"
    )
    await state.set_state(AddLessonSG.time)
    await callback.answer()


@router.message(AddLessonSG.day_selection)
async def add_lesson_custom_date(message: Message, state: FSMContext):
    """Обработка ручного ввода даты в формате дд:мм"""
    text = message.text.strip()
    try:
        day, month = map(int, text.split(":"))
        now = datetime.now()
        # Предполагаем текущий год, если дата уже прошла — следующий год
        target_date = datetime(now.year, month, day).date()
        if target_date < now.date():
            target_date = datetime(now.year + 1, month, day).date()
    except (ValueError, TypeError):
        await message.answer("❌ Неверный формат. Введите дату как дд:мм (например, 15:04).")
        return

    await state.update_data(target_date=target_date)
    await message.answer(
        f"Выбрана дата: {target_date.strftime('%d.%m.%Y')}\n"
        f"Теперь введите время занятия (чч:мм):"
    )
    await state.set_state(AddLessonSG.time)


@router.message(AddLessonSG.time)
async def add_lesson_time(message: Message, state: FSMContext):
    text = message.text.strip()
    try:
        hour, minute = map(int, text.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ Неверный формат времени. Введите как чч:мм (например, 16:30).")
        return

    data = await state.get_data()
    target_date = data["target_date"]
    scheduled_at = datetime.combine(target_date, datetime.min.time().replace(hour=hour, minute=minute))

    # Проверяем, что время ещё не прошло (если дата сегодня)
    if scheduled_at <= datetime.now():
        await message.answer("⚠️ Указанное время уже прошло. Пожалуйста, выберите будущее время.")
        return

    await state.update_data(scheduled_at=scheduled_at)

    topic = data["topic"]
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Верно", callback_data="confirm_lesson:yes")],
        [InlineKeyboardButton(text="🔄 Неверно", callback_data="confirm_lesson:no")],
    ])

    await message.answer(
        f"Проверьте данные:\n\n"
        f"📚 Тема: {topic}\n"
        f"📅 Дата и время: {scheduled_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Всё верно?",
        reply_markup=confirm_kb
    )
    await state.set_state(AddLessonSG.confirmation)


@router.callback_query(F.data.startswith("confirm_lesson:"), AddLessonSG.confirmation)
async def add_lesson_confirmation(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]

    if action == "no":
        await state.clear()
        await callback.message.edit_text("❌ Добавление занятия отменено. Начните заново с /addLesson")
        await callback.answer()
        return

    # Действие "yes"
    await callback.message.edit_text(
        "✅ Данные подтверждены. Теперь введите ссылку на занятие (Zoom, Google Meet и т.п.):"
    )
    await state.set_state(AddLessonSG.link)
    await callback.answer()


@router.message(AddLessonSG.link)
async def add_lesson_link(message: Message, state: FSMContext):
    link = message.text.strip()
    if not link:
        await message.answer("Ссылка не может быть пустой. Попробуйте ещё раз.")
        return

    data = await state.get_data()
    topic = data["topic"]
    scheduled_at = data["scheduled_at"]
    actor = await get_user_or_reply(message)
    if not actor:
        return

    try:
        # Создаём занятие (без repeat_type, можно добавить опционально)
        await lesson_service.schedule(
            actor=actor,
            chat_id=message.chat.id,
            scheduled_at=scheduled_at,
            topic=topic,
            lesson_link=link,
            repeat_type=None,  # или добавить позже
        )
        await message.answer(
            f"✅ Занятие назначено!\n\n"
            f"📚 Тема: {topic}\n"
            f"📅 Дата и время: {scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"🔗 Ссылка: {link}"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании занятия: {str(e)}")
    finally:
        await state.clear()


@router.message(Command("removeLesson"))
async def cmd_remove_lesson(message: Message, state: FSMContext):
    lessons = await lesson_service.list_for_chat(message.chat.id)
    if not lessons:
        await message.answer("Нет занятий для удаления")
        await state.clear()
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{l.topic} — {l.scheduled_at.strftime('%d:%m %H:%M')}",
                    callback_data=f"lesson_delete:{l.id}",
                )
            ]
            for l in lessons[:10]
        ]
    )
    await message.answer("Выберите занятие для удаления:", reply_markup=kb)
    await state.set_state(RemoveLessonSG.select_lesson)


@router.callback_query(F.data.startswith("lesson_delete:"),
                       RemoveLessonSG.select_lesson)
async def delete_lesson(callback: CallbackQuery, state: FSMContext):
    lesson_id = int(callback.data.split(":")[1])
    await lesson_service.delete(lesson_id)
    await callback.message.answer("Занятие удалено")
    await callback.answer()
    await state.clear()


@router.message(Command("addReminder"))
async def cmd_add_reminder(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Себе", callback_data="target:self")],
            [InlineKeyboardButton(text="Студенту",
                                  callback_data="target:student")],
        ]
    )
    await message.answer("Кого напомнить?", reply_markup=kb)
    await state.set_state(AddReminderSG.target)


@router.callback_query(F.data.startswith("target:"), AddReminderSG.target)
async def reminder_target(callback: CallbackQuery, state: FSMContext):
    target = callback.data.split(":")[1]
    await state.update_data(target=target)

    if target == "student":
        students = await user_repo.get_all_students()
        if not students:
            await callback.message.answer("Нет студентов")
            await state.clear()
            await callback.answer()
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=s.username,
                                      callback_data=f"student:{s.telegram_id}")]
                for s in students[:10]
            ]
        )
        await callback.message.answer("Выберите студента:", reply_markup=kb)
        await state.set_state(AddReminderSG.student)
        await callback.answer()
        return

    lessons = await lesson_service.upcoming(10)
    if not lessons:
        await callback.message.answer("Сейчас нет назначенных занятий")
        await state.clear()
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{l.topic} — {l.scheduled_at.strftime('%d:%m %H:%M')}",
                    callback_data=f"lesson:{l.id}",
                )
            ]
            for l in lessons[:10]
        ]
    )
    await callback.message.answer("Выберите занятие:", reply_markup=kb)
    await state.set_state(AddReminderSG.lesson)
    await callback.answer()


@router.callback_query(F.data.startswith("student:"), AddReminderSG.student)
async def reminder_student(callback: CallbackQuery, state: FSMContext):
    student_id = int(callback.data.split(":")[1])
    await state.update_data(student_id=student_id)

    lessons = await lesson_service.upcoming(10)
    if not lessons:
        await callback.message.answer("Сейчас нет назначенных занятий")
        await state.clear()
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{l.topic} — {l.scheduled_at.strftime('%d:%m %H:%M')}",
                    callback_data=f"lesson:{l.id}",
                )
            ]
            for l in lessons[:10]
        ]
    )
    await callback.message.answer("Выберите занятие:", reply_markup=kb)
    await state.set_state(AddReminderSG.lesson)
    await callback.answer()


@router.callback_query(F.data.startswith("lesson:"), AddReminderSG.lesson)
async def reminder_lesson(callback: CallbackQuery, state: FSMContext):
    lesson_id = int(callback.data.split(":")[1])
    await state.update_data(lesson_id=lesson_id)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Занятие",
                                  callback_data="topic:lesson")],
            [InlineKeyboardButton(text="Домашка",
                                  callback_data="topic:homework")],
            [InlineKeyboardButton(text="Свое", callback_data="topic:custom")],
        ]
    )
    await callback.message.answer("Выберите тип напоминания:", reply_markup=kb)
    await state.set_state(AddReminderSG.topic)
    await callback.answer()


@router.callback_query(F.data.startswith("topic:"), AddReminderSG.topic)
async def reminder_topic(callback: CallbackQuery, state: FSMContext):
    topic = callback.data.split(":")[1]
    await state.update_data(topic=topic)

    if topic == "custom":
        await callback.message.answer("Напишите текст напоминания")
        await state.set_state(AddReminderSG.custom_text)
        await callback.answer()
        return

    await callback.message.answer(
        "Выберите время: 5m/10m/15m/30m/1h/2h/4h/8h/12h/1d или custom")
    await state.set_state(AddReminderSG.time)
    await callback.answer()


@router.message(AddReminderSG.custom_text)
async def reminder_custom_text(message: Message, state: FSMContext):
    await state.update_data(custom_text=message.text)
    await message.answer(
        "Выберите время: 5m/10m/15m/30m/1h/2h/4h/8h/12h/1d или dd:hh:mm")
    await state.set_state(AddReminderSG.time)


@router.message(AddReminderSG.time)
async def reminder_time(message: Message, state: FSMContext):
    data = await state.get_data()
    time_val = (message.text or "").strip()

    actor, _ = await get_or_create_user(message)
    target_id = actor.telegram_id if data.get(
        "target") == "self" else data.get("student_id")
    if not target_id:
        await message.answer("Цель напоминания не выбрана")
        await state.clear()
        return

    try:
        await reminder_service.create_for_lesson(
            actor=actor,
            target_user_id=int(target_id),
            lesson_id=int(data["lesson_id"]),
            reminder_type=ReminderType(data["topic"]),
            time_value=time_val,
            custom_text=data.get("custom_text"),
        )
        await message.answer("Напоминание создано")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
    finally:
        await state.clear()


@router.message(Command("removeReminder"))
async def cmd_remove_reminder(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Себе", callback_data="target:self")],
            [InlineKeyboardButton(text="Студенту",
                                  callback_data="target:student")],
        ]
    )
    await message.answer("Выберите цель:", reply_markup=kb)
    await state.set_state(RemoveReminderSG.target)


@router.callback_query(F.data.startswith("target:"), RemoveReminderSG.target)
async def remove_reminder_target(callback: CallbackQuery, state: FSMContext):
    target = callback.data.split(":")[1]

    if target == "student":
        students = await user_repo.get_all_students()
        if not students:
            await callback.message.answer("Нет студентов")
            await state.clear()
            await callback.answer()
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=s.username,
                                      callback_data=f"student:{s.telegram_id}")]
                for s in students[:10]
            ]
        )
        await callback.message.answer("Выберите студента:", reply_markup=kb)
        await state.set_state(RemoveReminderSG.student)
        await callback.answer()
        return

    reminders = await reminder_service.list_for_user(callback.from_user.id)
    if not reminders:
        await callback.message.answer("Нет напоминаний")
        await state.clear()
        await callback.answer()
        return

    await callback.message.answer("Выберите напоминание:",
                                  reply_markup=_reminders_keyboard(reminders))
    await state.set_state(RemoveReminderSG.select_reminder)
    await callback.answer()


@router.callback_query(F.data.startswith("student:"), RemoveReminderSG.student)
async def remove_reminder_student(callback: CallbackQuery, state: FSMContext):
    student_id = int(callback.data.split(":")[1])
    reminders = await reminder_service.list_for_user(student_id)
    if not reminders:
        await callback.message.answer("Нет напоминаний")
        await state.clear()
        await callback.answer()
        return

    await callback.message.answer("Выберите напоминание:",
                                  reply_markup=_reminders_keyboard(reminders))
    await state.set_state(RemoveReminderSG.select_reminder)
    await callback.answer()


def _reminders_keyboard(reminders: list) -> "InlineKeyboardMarkup":
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{r.reminder_type.value} — {r.remind_at.strftime('%d:%m %H:%M')}",
                    callback_data=f"reminder_delete:{r.id}",
                )
            ]
            for r in reminders[:10]
        ]
    )
    return kb


@router.callback_query(F.data.startswith("reminder_delete:"),
                       RemoveReminderSG.select_reminder)
async def delete_reminder(callback: CallbackQuery, state: FSMContext):
    reminder_id = int(callback.data.split(":")[1])
    await reminder_service.delete(reminder_id)
    await callback.message.answer("Напоминание удалено")
    await callback.answer()
    await state.clear()


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    user = await get_user_or_reply(message)
    if not user:
        return

    try:
        if user.role not in (UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER):
            await message.answer(
                "🔒 У вас нет доступа к этой команде\n"
                "Статистика доступна преподавателям и администраторам"
            )
            return

        await message.bot.send_chat_action(message.chat.id, "typing")

        period_stats = await statistics_service.get_period_statistics(
            actor=user,
            period_days=30
        )

        stats_text = statistics_service.format_period_statistics(period_stats)
        await message.answer(stats_text)

        if user.role == UserRole.TEACHER:
            teacher_stats = await statistics_service.get_teacher_statistics(
                actor=user,
                period_days=30
            )
            teacher_text = statistics_service.format_teacher_statistics(
                teacher_stats,
                period_days=30
            )
            await message.answer(f"\n{teacher_text}")

    except PermissionDeniedException as e:
        await message.answer(f"🔒 {str(e)}")
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении статистики: {str(e)}")


@router.message(Command("sql"))
async def cmd_sql(message: Message, state: FSMContext):
    user, _ = await get_or_create_user(message)
    if user.role != UserRole.OWNER:
        await message.answer(
            "🔒 У вас нет доступа к этой команде\n"
            "Только владелец может выполнять SQL-запросы"
        )
        return

    help_text = (
        "📊 SQL-консоль для аналитики\n\n"
        "Отправьте SELECT-запрос для получения данных.\n\n"
        "⚡️ Особенности:\n"
        "• Разрешены только SELECT-запросы\n"
        "• Таймаут: 10 секунд\n"
        "• Результаты > 15 строк → CSV-файл\n"
        "• Режим Read-Only\n\n"
        "📝 Пример:\n"
        "<code>SELECT * FROM users LIMIT 10</code>\n\n"
        "Введите запрос:"
    )
    await message.answer(help_text, parse_mode="HTML")
    await state.set_state(SqlConsoleSG.query)


@router.message(SqlConsoleSG.query)
async def sql_query(message: Message, state: FSMContext):
    user, _ = await get_or_create_user(message)

    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        result = await analytics_service.execute_query(
            actor=user,
            query=message.text
        )

        if analytics_service.should_export_to_csv(result):
            summary = analytics_service.format_result_as_text(result,
                                                              max_rows=5)

            from aiogram.types import BufferedInputFile
            csv_file = analytics_service.export_to_csv(result)
            input_file = BufferedInputFile(
                csv_file.read(),
                filename=csv_file.name
            )

            await message.answer(summary)
            await message.answer_document(
                input_file,
                caption=f"📎 Полный результат ({result.row_count} строк)"
            )
        else:
            text_result = analytics_service.format_result_as_text(result)
            await message.answer(text_result)

    except PermissionDeniedException as e:
        await message.answer(f"🔒 {str(e)}")
    except ValidationException as e:
        await message.answer(f"❌ {str(e)}")
    except Exception as e:
        await message.answer(
            f"❌ Непредвиденная ошибка:\n{str(e)}\n\n"
            f"Проверьте синтаксис запроса и повторите попытку."
        )
    finally:
        await state.clear()


@router.callback_query(F.data.startswith("complete_lesson:"))
async def complete_lesson_callback(callback: CallbackQuery, state: FSMContext):
    try:
        parts = callback.data.split(":")
        lesson_id = int(parts[1])
        duration_value = parts[2]

        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        if duration_value == "custom":
            await state.update_data(lesson_id=lesson_id)
            await state.set_state(CompleteLessonSG.custom_duration)
            await callback.message.edit_text(
                f"{callback.message.text}\n\n"
                "✏️ Введите длительность в минутах (например: 75):"
            )
            await callback.answer()
            return

        duration_minutes = int(duration_value)

        try:
            lesson = await lesson_service.complete_lesson(
                lesson_id=lesson_id,
                actor=user,
                duration_minutes=duration_minutes,
            )

            await callback.message.edit_text(
                f"✅ Занятие завершено!\n\n"
                f"📚 Тема: {lesson.topic}\n"
                f"⏱ Длительность: {duration_minutes} мин\n"
                f"🕐 Запланировано: {lesson.scheduled_at.strftime('%d.%m %H:%M')}\n"
                f"✔️ Статус: Завершено"
            )
            await callback.answer("Занятие успешно завершено!",
                                  show_alert=True)

        except (ValidationException, PermissionDeniedException) as e:
            await callback.answer(f"Ошибка: {str(e)}", show_alert=True)

    except Exception as e:
        await callback.answer(f"Произошла ошибка: {str(e)}", show_alert=True)


@router.message(CompleteLessonSG.custom_duration)
async def complete_lesson_custom_duration(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        lesson_id = data.get("lesson_id")

        if not lesson_id:
            await message.answer("Ошибка: занятие не найдено")
            await state.clear()
            return

        try:
            duration_minutes = int(message.text.strip())
        except ValueError:
            await message.answer(
                "❌ Неверный формат.\n"
                "Пожалуйста, введите число (количество минут), например: 75"
            )
            return

        if duration_minutes <= 0 or duration_minutes > 300:
            await message.answer(
                "❌ Длительность должна быть от 1 до 300 минут.\n"
                "Пожалуйста, введите корректное значение:"
            )
            return

        user = await user_repo.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("Пользователь не найден")
            await state.clear()
            return

        try:
            lesson = await lesson_service.complete_lesson(
                lesson_id=lesson_id,
                actor=user,
                duration_minutes=duration_minutes,
            )

            await message.answer(
                f"✅ Занятие завершено!\n\n"
                f"📚 Тема: {lesson.topic}\n"
                f"⏱ Длительность: {duration_minutes} мин\n"
                f"🕐 Запланировано: {lesson.scheduled_at.strftime('%d.%m %H:%M')}\n"
                f"✔️ Статус: Завершено"
            )

        except (ValidationException, PermissionDeniedException) as e:
            await message.answer(f"❌ Ошибка: {str(e)}")

    except Exception as e:
        await message.answer(f"❌ Произошла ошибка: {str(e)}")
    finally:
        await state.clear()

# ==========================================
# КОМАНДЫ /commands и /help
# ==========================================

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Показывает справку по доступным командам."""
    help_text = (
        "📋 Доступные команды:\n\n"
        "/start — начать работу с ботом, после выполнения будут доступны другие действия\n"
        "/help — эта справка\n\n"
        "Если у вас есть вопросы, обратитесь к администратору."
    )
    await message.answer(help_text)