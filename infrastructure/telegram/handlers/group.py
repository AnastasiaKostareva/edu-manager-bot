"""
Хендлеры для групповых чатов.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from aiogram import Router, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

from infrastructure.telegram.keyboards import main_menu_keyboard, quick_actions_keyboard, add_cancel_button
from infrastructure.telegram.states import GroupRegSG
from infrastructure.telegram.handlers.helpers import MSK, get_or_create_user, ensure_chat_exists
from application.use_cases.chat import ChatService
from application.use_cases.lesson import LessonService
from domain.entities import UserRole, LessonStatus, RepeatType, Lesson, Reminder
from infrastructure.database.repositories import (
    UserRepository, LessonRepository, ChatRepository, ChatMemberRepository, ReminderRepository,
)

logger = logging.getLogger(__name__)
router = Router()

user_repo = UserRepository()
lesson_repo = LessonRepository()
chat_repo = ChatRepository()
chat_member_repo = ChatMemberRepository()

lesson_service = LessonService(lesson_repo)
reminder_repo_grp = ReminderRepository()
chat_service = ChatService(chat_repo, chat_member_repo, user_repo)

USERNAME_PATTERN = __import__("re").compile(r'^@?([a-zA-Z0-9_]{5,32})$')
_GROUP = F.chat.type.in_({"group", "supergroup"})

# ─────────────────────────────────────────
# Клавиатуры
# ─────────────────────────────────────────

def _group_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Зарегистрировать участника", callback_data="group_reg:start")]
    ])

def _role_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ученик", callback_data="reg_role:student")],
        [InlineKeyboardButton(text="Преподаватель", callback_data="reg_role:teacher")],
        [InlineKeyboardButton(text="Родитель", callback_data="reg_role:parent")],
    ])

def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Верно", callback_data="reg_confirm:yes")],
        [InlineKeyboardButton(text="Ошибся", callback_data="reg_confirm:no")],
    ])

# ─────────────────────────────────────────
# /start → Приветствие + Кнопка
# ─────────────────────────────────────────

@router.message(_GROUP, CommandStart(), StateFilter("*"))
async def group_start(message: Message, state: FSMContext):
    await state.clear()
    await ensure_chat_exists(message)
    await state.update_data(initiator_id=message.from_user.id)
    await message.answer(
        "Привет! Я бот-помощник для онлайн-занятий.\n\n"
        "Для регистрации участников нажмите кнопку ниже:",
        reply_markup=_group_start_keyboard()
    )

# ─────────────────────────────────────────
# Нажатие на кнопку → запуск регистрации
# ─────────────────────────────────────────

@router.callback_query(F.data == "group_reg:start")
async def start_registration_flow(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.from_user.id != data.get("initiator_id"):
        await callback.answer("❌ Только тот, кто вызвал /start, может регистрировать участников.", show_alert=True)
        return

    user, _ = await get_or_create_user(callback)
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        await callback.answer("❌ Только администратор или владелец могут регистрировать участников.", show_alert=True)
        return

    await callback.message.edit_text("Введите @username участника или /done для завершения.")
    await state.set_state(GroupRegSG.waiting_for_username)
    await callback.answer()

# ─────────────────────────────────────────
# Завершение регистрации (/done)
# ─────────────────────────────────────────

@router.message(_GROUP, Command("done"), StateFilter(GroupRegSG.waiting_for_username))
async def group_reg_done_early(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.from_user.id != data.get("initiator_id"):
        return
    await state.clear()
    user, _ = await get_or_create_user(message)
    await message.answer("✅ Регистрация участников завершена!", reply_markup=main_menu_keyboard(user.role, is_group=True))
    await message.answer("🚀 Быстрые действия:", reply_markup=quick_actions_keyboard(user.role, is_group=True))

@router.message(_GROUP, Command("done"), StateFilter(GroupRegSG.role_selection, GroupRegSG.name_input, GroupRegSG.confirmation))
async def group_reg_done_anytime(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.from_user.id != data.get("initiator_id"):
        return
    await state.clear()
    user, _ = await get_or_create_user(message)
    await message.answer("✅ Регистрация завершена!", reply_markup=main_menu_keyboard(user.role, is_group=True))
    await message.answer("🚀 Быстрые действия:", reply_markup=quick_actions_keyboard(user.role, is_group=True))

# ─────────────────────────────────────────
# Ввод username → Выбор роли → Имя → Подтверждение
# ─────────────────────────────────────────

@router.message(_GROUP, StateFilter(GroupRegSG.waiting_for_username))
async def group_reg_username_input(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.from_user.id != data.get("initiator_id"):
        return
    text = message.text.strip()
    if text.startswith("/"):
        await message.answer("⚠️ Введите @username или /done для завершения.")
        return
    match = USERNAME_PATTERN.match(text)
    if not match:
        await message.answer("⚠️ Неверный формат. Введите @username (например, @ivan_ivanov) или /done.")
        return

    await state.update_data(current_username=match.group(1))
    await state.set_state(GroupRegSG.role_selection)
    await message.answer(
        f"Кто @{match.group(1)}?",
        reply_markup=add_cancel_button(_role_keyboard(), initiator_id=data.get("initiator_id")),
    )

@router.callback_query(F.data.startswith("reg_role:"), GroupRegSG.role_selection)
async def group_reg_role_selected(callback: CallbackQuery, state: FSMContext):
    role_value = callback.data.split(":", 1)[1]
    await state.update_data(temp_role=role_value)
    await state.set_state(GroupRegSG.name_input)
    data = await state.get_data()
    await callback.message.edit_text(f"Как зовут @{data['current_username']}?")
    await callback.answer()

@router.message(_GROUP, GroupRegSG.name_input)
async def group_reg_name_input(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.from_user.id != data.get("initiator_id"):
        return
    full_name = message.text.strip()
    if not full_name:
        await message.answer("Введите имя и фамилию.")
        return

    await state.update_data(temp_name=full_name)
    await state.set_state(GroupRegSG.confirmation)
    data = await state.get_data()
    role_display = {"student": "Ученик", "teacher": "Преподаватель", "parent": "Родитель"}.get(data["temp_role"], data["temp_role"])
    await message.answer(
        f"@{data['current_username']} — {full_name}, {role_display}\nВсё верно?",
        reply_markup=add_cancel_button(_confirm_keyboard(), initiator_id=data.get("initiator_id")),
    )

@router.callback_query(F.data.startswith("reg_confirm:"), GroupRegSG.confirmation)
async def group_reg_confirmation(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    username = data["current_username"]
    chat_id = callback.message.chat.id

    if action == "no":
        await state.set_state(GroupRegSG.role_selection)
        await callback.message.edit_text(
            f"Кто @{username}?",
            reply_markup=add_cancel_button(_role_keyboard(), initiator_id=data.get("initiator_id")),
        )
        await callback.answer()
        return

    clean_username = username.lstrip("@")
    bot_info = await callback.bot.get_me()
    if clean_username.lower() == bot_info.username.lower():
        await callback.message.edit_text("❌ Нельзя зарегистрировать бота.")
        await state.set_state(GroupRegSG.waiting_for_username)
        await callback.answer()
        return

    role_map = {"student": UserRole.STUDENT, "teacher": UserRole.TEACHER, "parent": UserRole.STUDENT}
    role = role_map.get(data["temp_role"], UserRole.STUDENT)

    existing = await user_repo.get_by_username(clean_username)
    if existing:
        existing.full_name = data["temp_name"]
        if existing.role not in (UserRole.OWNER, UserRole.ADMIN):
            existing.role = role
        await user_repo.update(existing)
        linked_user = existing
    else:
        await callback.message.edit_text(
            "🚫 Пользователя нет в базе данных.\n\n"
            "Обратитесь к преподавателю, чтобы он зарегистрировал вас в групповом чате или вручную."
        )
        await state.set_state(GroupRegSG.waiting_for_username)
        await callback.answer()
        return

    member_exists = await chat_member_repo.get_by_chat_and_user(chat_id, linked_user.telegram_id)
    if not member_exists:
        from domain.entities import ChatMember
        await chat_member_repo.create(ChatMember(
            chat_id=chat_id,
            user_id=linked_user.telegram_id,
            is_active=True,
        ))

    await callback.message.edit_text(
        f"✅ @{username} зарегистрирован и добавлен в чат.\n\nВведите следующий @username или /done."
    )
    await state.set_state(GroupRegSG.waiting_for_username)
    await callback.answer()

# ─────────────────────────────────────────
# Мои занятия / Управление занятиями
# ─────────────────────────────────────────

@router.message(_GROUP, StateFilter("*"), F.text == "Мои занятия")
@router.message(_GROUP, StateFilter("*"), Command("lessons"))
async def group_lessons(message: Message, state: FSMContext):
    await state.clear()
    if not await chat_service.is_chat_initialized(message.chat.id):
        await message.answer("⚠️ Чат ещё не настроен. Выполните /start для регистрации участников.")
        return
    lessons = await lesson_service.list_for_chat(message.chat.id)
    if not lessons:
        await message.answer("В этом чате пока нет назначенных занятий.")
        return
    text = "📚 Занятия в этом чате:\n\n" + "\n".join(
        f"{i + 1}. {l.topic} — {_fmt_dt(l.scheduled_at)}" for i, l in enumerate(lessons)
    )
    await message.answer(text)

@router.callback_query(F.data.startswith("start_lesson:"))
async def on_start_lesson(callback: CallbackQuery):
    lesson_id = int(callback.data.split(":")[1])
    user, _ = await get_or_create_user(callback)
    if user.role not in (UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER):
        await callback.answer("❌ Только преподаватель может начать занятие", show_alert=True)
        return
    lesson = await lesson_repo.get_by_id(lesson_id)
    if not lesson:
        await callback.answer("❌ Занятие не найдено", show_alert=True)
        return
    lesson.status = LessonStatus.IN_PROGRESS
    lesson.actual_start = datetime.now(timezone.utc)
    await lesson_repo.update(lesson)
    new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Завершить", callback_data=f"complete_lesson:{lesson_id}")]
    ])
    await callback.message.edit_text(
        f"🔴 Идет занятие: {lesson.topic}\n"
        f"Ссылка для подключения: {lesson.lesson_link}\n"
        f"🕐 Начато: {lesson.actual_start.astimezone(MSK).strftime('%H:%M')} МСК",
        reply_markup=new_keyboard
    )
    await callback.answer("Занятие начато!")

@router.callback_query(F.data.startswith("complete_lesson:"))
async def on_complete_lesson(callback: CallbackQuery):
    lesson_id = int(callback.data.split(":")[1])
    user, _ = await get_or_create_user(callback)
    if user.role not in (UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER):
        await callback.answer("❌ Только преподаватель может завершить занятие", show_alert=True)
        return
    lesson = await lesson_repo.get_by_id(lesson_id)
    if not lesson:
        await callback.answer("❌ Занятие не найдено", show_alert=True)
        return
    lesson.status = LessonStatus.COMPLETED
    lesson.actual_end = datetime.now(timezone.utc)
    if lesson.actual_start:
        lesson.duration_minutes = int((lesson.actual_end - lesson.actual_start).total_seconds() / 60)
    await lesson_repo.update(lesson)

    next_lesson_msg = ""
    if lesson.repeat_type and lesson.repeat_type != RepeatType.ONE_TIME:
        try:
            next_l = await _create_next_occurrence(lesson)
            if next_l:
                next_lesson_msg = f"\n\n🔁 Следующее занятие автоматически назначено на {_fmt_dt(next_l.scheduled_at)}"
        except Exception as e:
            logger.warning(f"Failed to create next occurrence: {e}")

    await callback.message.edit_text(
        f"✅ Занятие завершено: {lesson.topic}\n\n"
        f"🕐 Начало: {lesson.actual_start.astimezone(MSK).strftime('%H:%M')} МСК\n"
        f"🕑 Конец: {lesson.actual_end.astimezone(MSK).strftime('%H:%M')} МСК\n"
        f"⏱ Длительность: {lesson.duration_minutes or '—'} мин"
        + next_lesson_msg
    )
    await callback.answer("Занятие завершено!")


async def _create_next_occurrence(lesson: Lesson) -> "Lesson | None":
    """Создаёт следующее занятие для периодического расписания и копирует напоминания."""
    repeat_map = {
        RepeatType.WEEKLY: timedelta(weeks=1),
        RepeatType.EVERY_2_WEEKS: timedelta(weeks=2),
        RepeatType.MONTHLY: timedelta(days=30),
    }
    delta = repeat_map.get(lesson.repeat_type)
    if not delta:
        return None

    sched_at = lesson.scheduled_at
    if sched_at.tzinfo is None:
        sched_at = sched_at.replace(tzinfo=MSK)
    next_scheduled_at = sched_at + delta

    next_scheduled_end = None
    if lesson.scheduled_end:
        end = lesson.scheduled_end if lesson.scheduled_end.tzinfo else lesson.scheduled_end.replace(tzinfo=MSK)
        next_scheduled_end = end + delta

    next_lesson = Lesson(
        chat_id=lesson.chat_id,
        created_by=lesson.created_by,
        scheduled_at=next_scheduled_at,
        scheduled_end=next_scheduled_end,
        topic=lesson.topic,
        lesson_link=lesson.lesson_link,
        repeat_type=lesson.repeat_type,
        status=LessonStatus.SCHEDULED,
    )
    created = await lesson_repo.create(next_lesson)

    try:
        now = datetime.now(timezone.utc)
        old_reminders = await reminder_repo_grp.get_by_lesson_id(lesson.id)
        for old_rem in old_reminders:
            if old_rem.remind_at is None:
                continue
            old_rem_dt = old_rem.remind_at if old_rem.remind_at.tzinfo else old_rem.remind_at.replace(tzinfo=timezone.utc)
            offset = sched_at - old_rem_dt
            new_remind_at = next_scheduled_at - offset
            if new_remind_at > now:
                await reminder_repo_grp.create(Reminder(
                    reminder_type=old_rem.reminder_type,
                    remind_at=new_remind_at,
                    user_id=old_rem.user_id,
                    chat_id=old_rem.chat_id,
                    creator_id=old_rem.creator_id,
                    lesson_id=created.id,
                    custom_text=old_rem.custom_text,
                    is_sent=False,
                ))
    except Exception as e:
        logger.warning(f"Failed to copy reminders for next occurrence: {e}")

    return created

def _fmt_dt(dt) -> str:
    if dt is None: return "—"
    if dt.tzinfo is not None: dt = dt.astimezone(MSK)
    return dt.strftime("%d.%m %H:%M")