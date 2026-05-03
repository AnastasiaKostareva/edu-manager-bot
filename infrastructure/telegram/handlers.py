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
    RemoveLessonSG, RemoveReminderSG, SqlConsoleSG, CompleteLessonSG, GroupRegSG
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

USERNAME_PATTERN = re.compile(r'^@([a-zA-Z0-9_]{5,32})$')

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


def _build_reminder_time_keyboard(payload: dict[str, str] | None = None) -> InlineKeyboardMarkup:
    options = ["5m", "10m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d"]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    suffix = ""
    if payload:
        parts = []
        for key in ("t", "s", "l", "tp"):
            value = payload.get(key)
            if value is not None and value != "":
                parts.append(f"{key}={value}")
        if parts:
            suffix = "|" + ",".join(parts)

    for idx, opt in enumerate(options, start=1):
        row.append(InlineKeyboardButton(text=opt, callback_data=f"rem_time:{opt}{suffix}"))
        if idx % 3 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(text="Вручную", callback_data=f"rem_time:custom{suffix}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _reminder_payload_from_state(data: dict) -> dict[str, str]:
    payload: dict[str, str] = {}
    if data.get("target"):
        payload["t"] = str(data["target"])
    if data.get("student_id"):
        payload["s"] = str(data["student_id"])
    if data.get("lesson_id"):
        payload["l"] = str(data["lesson_id"])
    if data.get("topic"):
        payload["tp"] = str(data["topic"])
    return payload


def _parse_reminder_time_payload(raw: str) -> tuple[str, dict[str, str]]:
    if "|" not in raw:
        return raw, {}
    value, payload_raw = raw.split("|", 1)
    payload: dict[str, str] = {}
    for part in payload_raw.split(","):
        if "=" in part:
            key, val = part.split("=", 1)
            payload[key] = val
    return value, payload


async def _resolve_actor_from_user(user) -> User:
    existing = await user_repo.get_by_telegram_id(user.id)
    if existing:
        return existing

    created = User(
        telegram_id=user.id,
        username=user.username or "",
        full_name=user.full_name,
        role=get_user_role(user.id),
        is_active=True,
    )
    return await user_repo.create(created)


async def _answer_or_edit(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    state: FSMContext | None = None,
) -> None:
    """Редактирует последний бот-сообщение в диалоге если возможно, иначе отправляет новое.

    Логика:
    - Если переданный message — это сообщение бота (callback.message), пробуем его отредактировать.
    - Иначе, если в FSM state сохранено last_bot_message, пробуем отредактировать его.
    - В противном случае отправляем новое сообщение и сохраняем его id в state (если state передан).
    """
    bot = message.bot

    # Если передали сообщение бота — редактируем его
    if getattr(message, "from_user", None) and getattr(message.from_user, "is_bot", False):
        try:
            await message.edit_text(text, reply_markup=reply_markup)
            # Сохраняем ссылку на редактируемое сообщение в state (если есть)
            if state is not None:
                await state.update_data(last_bot_message={"chat_id": message.chat.id, "message_id": message.message_id})
            return
        except Exception:
            pass

    # Пытаемся редактировать последнее бот-сообщение из state
    if state is not None:
        data = await state.get_data()
        last = data.get("last_bot_message")
        if isinstance(last, dict) and last.get("chat_id") and last.get("message_id"):
            try:
                await bot.edit_message_text(
                    text=text,
                    chat_id=last["chat_id"],
                    message_id=last["message_id"],
                    reply_markup=reply_markup,
                )
                return
            except Exception:
                # Если редактирование по сохранённому id не удалось — продолжим и отправим новое сообщение
                pass

    # Фоллбэк: отправляем новое сообщение и сохраняем его id в state
    sent = await message.answer(text, reply_markup=reply_markup)
    if state is not None:
        try:
            await state.update_data(last_bot_message={"chat_id": sent.chat.id, "message_id": sent.message_id})
        except Exception:
            pass


async def _create_reminder_from_state(
    message: Message,
    state: FSMContext,
    actor: User,
    time_val: str,
) -> None:
    data = await state.get_data()

    target_val = data.get("target")
    student_id = data.get("student_id")
    lesson_id = data.get("lesson_id")
    topic = data.get("topic")

    target_id = actor.telegram_id if target_val == "self" else student_id

    if target_id is None or not lesson_id or not topic:
        await _answer_or_edit(
            message,
            f"Похоже, сценарий напоминания прервался или не хватает данных.\n\n"
            f"Отладка состояния:\n"
            f"• Цель (target): {target_val}\n"
            f"• ID студента (student_id): {student_id}\n"
            f"• ID занятия (lesson_id): {lesson_id}\n"
            f"• Тема (topic): {topic}\n"
            f"• Вычисленный target_id: {target_id}\n\n"
            f"Пожалуйста, начните заново с /addReminder.",
            state=state,
        )
        await state.clear()
        return

    normalized_time = (time_val or "").strip().split()[0].lower()
    if not normalized_time:
        await _answer_or_edit(message, "Введите время в формате 5m/10m/1h или dd:hh:mm.", state=state)
        return

    try:
        await reminder_service.create_for_lesson(
            actor=actor,
            target_user_id=int(target_id),
            lesson_id=int(lesson_id),
            reminder_type=ReminderType(topic),
            time_value=normalized_time,
            custom_text=data.get("custom_text"),
        )
        await _answer_or_edit(message, "Напоминание успешно создано!", state=state)
    except Exception as e:
        await _answer_or_edit(message, f"Ошибка при создании: {str(e)}", state=state)
    finally:
        await state.clear()


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
# ==========================================
# ГРУППОВАЯ РЕГИСТРАЦИЯ (НОВАЯ ЛОГИКА)
# ==========================================

async def _handle_group_start(message: Message, state: FSMContext):
    """Начало регистрации в группе: приглашение ввести первый @username."""
    await message.answer(
        "Приветствую, это Бот-помощник для проведения онлайн занятий.\n"
        "Расскажи мне об участниках и можем стартовать!\n\n"
        "⚠️ Telegram API не позволяет ботам автоматически получать ID участников.\n"
        "Пожалуйста, введите @username первого участника или отправьте /done для завершения."
    )
    await state.set_state(GroupRegSG.waiting_for_username)


@router.message(Command("done"), StateFilter(GroupRegSG.waiting_for_username))
async def group_reg_done_early(message: Message, state: FSMContext):
    """Завершение регистрации до ввода пользователей."""
    await state.clear()
    await message.answer("✅ Регистрация завершена. Если хотите добавить участников позже, используйте /start снова.")


@router.message(StateFilter(GroupRegSG.waiting_for_username))
async def group_reg_username_input(message: Message, state: FSMContext):
    """Обработка ввода @username: начинаем регистрацию этого пользователя."""
    text = message.text.strip()
    if text.startswith("/"):
        await message.answer("⚠️ Неверный формат. Введите @username или /done для завершения.")
        return

    match = USERNAME_PATTERN.match(text)
    if not match:
        await message.answer("⚠️ Неверный формат. Введите @username (например, @ivan_ivanov) или /done.")
        return

    username = match.group(1)
    await state.update_data(current_username=username)
    await state.set_state(GroupRegSG.role_selection)

    await message.answer(
        f"Кто @{username}?",
        reply_markup=_build_role_keyboard()
    )


@router.callback_query(F.data.startswith("reg_role:"), GroupRegSG.role_selection)
async def group_reg_role_selected(callback: CallbackQuery, state: FSMContext):
    role_value = callback.data.split(":", 1)[1]
    await state.update_data(temp_role=role_value)
    await state.set_state(GroupRegSG.name_input)

    data = await state.get_data()
    username = data["current_username"]
    await callback.message.edit_text(f"Как зовут @{username}?")
    await callback.answer()


@router.message(GroupRegSG.name_input)
async def group_reg_name_input(message: Message, state: FSMContext):
    full_name = message.text.strip()
    if not full_name:
        await message.answer("Пожалуйста, введите имя и фамилию.")
        return

    await state.update_data(temp_name=full_name)
    await state.set_state(GroupRegSG.confirmation)

    data = await state.get_data()
    username = data["current_username"]
    role_display = {
        "student": "Ученик",
        "teacher": "Преподаватель",
        "parent": "Родитель"
    }.get(data["temp_role"], data["temp_role"])

    await message.answer(
        f"Запомнил! @{username} - {full_name}\nРоль - {role_display}",
        reply_markup=_build_confirmation_keyboard()
    )


@router.callback_query(F.data.startswith("reg_confirm:"), GroupRegSG.confirmation)
async def group_reg_confirmation(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    username = data["current_username"]

    if action == "no":
        # Возвращаемся к выбору роли для этого же пользователя
        await state.set_state(GroupRegSG.role_selection)
        await callback.message.edit_text(
            f"Кто @{username}?",
            reply_markup=_build_role_keyboard()
        )
        await callback.answer()
        return

    # Действие "yes": сохраняем пользователя в БД
    telegram_id = 0  # временный ID (0 означает, что пользователь ещё не писал боту)
    existing_by_username = await user_repo.get_by_username(username)
    # Если пользователь уже существует, обновим его данные
    if existing_by_username:
        existing_by_username.full_name = data["temp_name"]
        existing_by_username.role = {
            "student": UserRole.STUDENT,
            "teacher": UserRole.TEACHER,
            "parent": UserRole.STUDENT,
        }.get(data["temp_role"], UserRole.STUDENT)
        await user_repo.update(existing_by_username)
    else:
        new_user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=data["temp_name"],
            role={
                "student": UserRole.STUDENT,
                "teacher": UserRole.TEACHER,
                "parent": UserRole.STUDENT,
            }.get(data["temp_role"], UserRole.STUDENT),
            is_active=True,
        )
        try:
            await user_repo.create(new_user)
        except Exception:
            pass  # Игнорируем конфликты уникальности

    # После успешного сохранения возвращаемся к вводу следующего @username
    await callback.message.edit_text(
        f"✅ @{username} зарегистрирован.\n\n"
        "Введите следующий @username или отправьте /done для завершения."
    )
    await state.set_state(GroupRegSG.waiting_for_username)
    await callback.answer()


@router.message(Command("done"), StateFilter(GroupRegSG.role_selection, GroupRegSG.name_input, GroupRegSG.confirmation))
async def group_reg_done_anytime(message: Message, state: FSMContext):
    """Завершение регистрации в любой момент (кроме ожидания username)."""
    await state.clear()
    await message.answer("✅ Регистрация завершена. Готов к работе!")

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
@router.message(F.text == "Мои занятия")
async def cmd_lessons(message: Message, state: FSMContext):
    """Показывает занятия: в группе – занятия чата, в личке – свои (кроме админов)."""

    # === ГРУППОВОЙ ЧАТ ===
    if message.chat.type != "private":
        # Проверяем, инициализирован ли чат
        is_initialized = await chat_service.is_chat_initialized(
            message.chat.id)
        if not is_initialized:
            await message.answer(
                "⚠️ Чат ещё не настроен. Выполните /start для регистрации участников."
            )
            return

        # Получаем занятия, назначенные в этом чате
        lessons = await lesson_service.list_for_chat(message.chat.id)
        if not lessons:
            await message.answer("В этом чате пока нет назначенных занятий.")
            return

        # Формируем список занятий
        text = "📚 Занятия в этом чате:\n\n" + "\n".join(
            f"{i + 1}. {l.topic} — {l.scheduled_at.strftime('%d.%m %H:%M')}"
            for i, l in enumerate(lessons)
        )
        await message.answer(text)
        return

    # === ЛИЧНЫЕ СООБЩЕНИЯ ===
    user = await get_user_or_reply(message)
    if not user:
        return

    # Администраторы и владельцы могут смотреть занятия других пользователей
    if user.role in (UserRole.ADMIN, UserRole.OWNER):
        await message.answer(
            "Введите @username пользователя, чьи занятия хотите посмотреть:")
        await state.set_state("admin_find_user")
        return

    # Для обычных пользователей показываем их собственные занятия
    lessons = await lesson_service.list_for_user(user.telegram_id)
    if not lessons:
        await message.answer(
            "Сейчас нет назначенных занятий.\nИспользуйте /addLesson (если вы преподаватель) "
            "или дождитесь назначения от преподавателя."
        )
        return

    text = "📚 Ваши занятия:\n\n" + "\n".join(
        f"{i + 1}. {l.topic} — {l.scheduled_at.strftime('%d.%m %H:%M')}"
        for i, l in enumerate(lessons)
    )
    await message.answer(text)


@router.message(StateFilter("admin_find_user"))
async def admin_find_user(message: Message, state: FSMContext):
    """Обработка запроса админа на просмотр занятий конкретного пользователя."""
    username = message.text.strip().lstrip("@")
    user = await user_repo.get_by_username(username)

    if not user:
        await message.answer(
            "❌ Пользователь не найден. Проверьте правильность @username.")
        await state.clear()
        return

    lessons = await lesson_service.list_for_user(user.telegram_id)
    if not lessons:
        await message.answer(f"У пользователя @{user.username} нет занятий.")
        await state.clear()
        return

    text = f"📚 Занятия пользователя @{user.username}:\n\n" + "\n".join(
        f"{i + 1}. {l.topic} — {l.scheduled_at.strftime('%d.%m %H:%M')}"
        for i, l in enumerate(lessons)
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
            await _answer_or_edit(callback.message, "Нет студентов", state=state)
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
        await _answer_or_edit(callback.message, "Выберите студента:", reply_markup=kb, state=state)
        await state.set_state(AddReminderSG.student)
        await callback.answer()
        return

    lessons = await lesson_service.upcoming(10)
    if not lessons:
        await _answer_or_edit(callback.message, "Сейчас нет назначенных занятий", state=state)
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
    await _answer_or_edit(callback.message, "Выберите занятие:", reply_markup=kb, state=state)
    await state.set_state(AddReminderSG.lesson)
    await callback.answer()


@router.callback_query(F.data.startswith("student:"), AddReminderSG.student)
async def reminder_student(callback: CallbackQuery, state: FSMContext):
    student_id = int(callback.data.split(":")[1])
    await state.update_data(student_id=student_id)

    lessons = await lesson_service.upcoming(10)
    if not lessons:
        await _answer_or_edit(callback.message, "Сейчас нет назначенных занятий", state=state)
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
    await _answer_or_edit(callback.message, "Выберите занятие:", reply_markup=kb, state=state)
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
    await _answer_or_edit(callback.message, "Выберите тип напоминания:", reply_markup=kb, state=state)
    await state.set_state(AddReminderSG.topic)
    await callback.answer()


@router.callback_query(F.data.startswith("topic:"), AddReminderSG.topic)
async def reminder_topic(callback: CallbackQuery, state: FSMContext):
    topic = callback.data.split(":")[1]
    await state.update_data(topic=topic)

    if topic == "custom":
        await _answer_or_edit(callback.message, "Напишите текст напоминания", state=state)
        await state.set_state(AddReminderSG.custom_text)
        await callback.answer()
        return

    data = await state.get_data()
    await _answer_or_edit(
        callback.message,
        "Выберите время кнопками ниже или нажмите 'Вручную' для ввода.",
        reply_markup=_build_reminder_time_keyboard(_reminder_payload_from_state(data)),
        state=state,
    )
    await state.set_state(AddReminderSG.time)
    await callback.answer()


@router.callback_query(F.data.startswith("rem_time:"), AddReminderSG.time)
async def reminder_time_quick_select(callback: CallbackQuery, state: FSMContext):
    raw = callback.data.split(":", 1)[1]
    value, payload = _parse_reminder_time_payload(raw)
    if payload:
        update_data: dict = {}
        if payload.get("t"):
            update_data["target"] = payload["t"]
        if payload.get("s"):
            update_data["student_id"] = int(payload["s"])
        if payload.get("l"):
            update_data["lesson_id"] = int(payload["l"])
        if payload.get("tp"):
            update_data["topic"] = payload["tp"]
        if update_data:
            await state.update_data(**update_data)

    if value == "custom":
        await _answer_or_edit(callback.message, "Введите время (5m/10m/1h или dd:hh:mm):", state=state)
        await state.set_state(AddReminderSG.custom_time)
        await callback.answer()
        return

    actor = await _resolve_actor_from_user(callback.from_user)
    await _create_reminder_from_state(callback.message, state, actor, value)
    await callback.answer()


@router.message(AddReminderSG.custom_text)
async def reminder_custom_text(message: Message, state: FSMContext):
    await state.update_data(custom_text=message.text)
    data = await state.get_data()
    await _answer_or_edit(
        message,
        "Выберите время кнопками ниже или нажмите 'Вручную' для ввода.",
        reply_markup=_build_reminder_time_keyboard(_reminder_payload_from_state(data)),
        state=state,
    )
    await state.set_state(AddReminderSG.time)


@router.message(AddReminderSG.custom_time)
async def reminder_time_manual(message: Message, state: FSMContext):
    actor, _ = await get_or_create_user(message)
    await _create_reminder_from_state(message, state, actor, message.text)


@router.message(AddReminderSG.time)
async def reminder_time(message: Message, state: FSMContext):
    actor, _ = await get_or_create_user(message)
    await _create_reminder_from_state(message, state, actor, message.text)


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
