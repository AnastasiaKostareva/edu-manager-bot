"""
Хендлеры для личных сообщений (private chat).
Все команды с напоминаниями работают только здесь.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, Message,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from infrastructure.database.models import Reminder
from application.use_cases.analytics import AnalyticsService
from application.use_cases.auth import AuthService
from application.use_cases.lesson import LessonService
from application.use_cases.reminder import ReminderService
from application.use_cases.statistics import StatisticsService
from domain.entities import ReminderType, UserRole
from domain.exceptions import PermissionDeniedException, ValidationException, UserNotRegisteredException
from infrastructure.database.repositories import (
    LessonRepository, ReminderRepository, UserRepository,
    ChatRepository, ChatMemberRepository,
)
from infrastructure.telegram.handlers.helpers import (
    MSK, get_or_create_user, resolve_user_from_tg, ensure_chat_exists,
    get_admin_contact_username, answer_or_edit,
    build_reminder_time_keyboard, reminder_payload_from_state, parse_reminder_time_payload,
)
from infrastructure.telegram.keyboards import main_menu_keyboard, quick_actions_keyboard, add_cancel_button
from infrastructure.telegram.states import (
    AddLessonSG, AddReminderSG, RemoveLessonSG, RemoveReminderSG,
    SqlConsoleSG, CompleteLessonSG,
)

logger = logging.getLogger(__name__)

router = Router()

# Инициализация репозиториев и сервисов
user_repo = UserRepository()
lesson_repo = LessonRepository()
reminder_repo = ReminderRepository()
chat_repo = ChatRepository()
chat_member_repo = ChatMemberRepository()

auth_service = AuthService()
lesson_service = LessonService(lesson_repo)
reminder_service = ReminderService(reminder_repo, lesson_repo)
analytics_service = AnalyticsService()
statistics_service = StatisticsService()

# Фильтр: только личные сообщения
_PRIVATE = F.chat.type == "private"


# ─────────────────────────────────────────
# /start
# ─────────────────────────────────────────

@router.message(_PRIVATE, CommandStart(), StateFilter("*"))
async def pm_start(message: Message, state: FSMContext):
    await state.clear()
    try:
        user, _ = await get_or_create_user(message)
    except UserNotRegisteredException:
        await message.answer(
            "🚫 <b>Вас нет в базе данных.</b>\n\n"
            "Обратитесь к преподавателю, чтобы он зарегистрировал вас в групповом чате или вручную."
        )
        return
    user, _ = await get_or_create_user(message)
    admin_contact = await get_admin_contact_username()

    await message.answer(
        f"Привет, {user.full_name or user.username}!\n"
        f"Твоя роль: {user.role.value}\n"
        f"Если что-то неверно — обратись к @{admin_contact}",
        reply_markup=main_menu_keyboard(user.role, is_group=False),
    )
    await message.answer(
        "Быстрые действия:",
        reply_markup=quick_actions_keyboard(user.role, is_group=False),
    )


# ─────────────────────────────────────────
# Мои занятия
# ─────────────────────────────────────────

@router.message(_PRIVATE, StateFilter("*"), F.text == "Мои занятия")
@router.message(_PRIVATE, StateFilter("*"), Command("lessons"))
async def pm_lessons(message: Message, state: FSMContext):
    await state.clear()
    user, _ = await get_or_create_user(message)
    lessons = await lesson_service.list_for_user(user.telegram_id)

    if user.role in (UserRole.ADMIN, UserRole.OWNER):
        kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin_find_user")]
        ]))
        if not lessons:
            await message.answer("📚 У вас пока нет назначенных занятий.", reply_markup=kb)
        else:
            text = "📚 Ваши занятия:\n\n" + "\n".join(
                f"{i + 1}. {l.topic} — {_fmt_dt(l.scheduled_at)}"
                for i, l in enumerate(lessons)
            )
            await message.answer(text, reply_markup=kb)
        return

    if not lessons:
        await message.answer(
            "Сейчас нет назначенных занятий.\n"
            "Используйте /addLesson (если вы преподаватель) "
            "или дождитесь назначения."
        )
        return

    text = "📚 Ваши занятия:\n\n" + "\n".join(
        f"{i + 1}. {l.topic} — {_fmt_dt(l.scheduled_at)}"
        for i, l in enumerate(lessons)
    )
    await message.answer(text)


@router.callback_query(_PRIVATE, F.data == "admin_find_user")
async def pm_admin_find_user_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state("admin_find_user_pm")
    await callback.message.answer("Введите @username пользователя:")
    await callback.answer()


@router.message(_PRIVATE, StateFilter("admin_find_user_pm"))
async def pm_admin_find_user(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@")
    user = await user_repo.get_by_username(username)
    await state.clear()
    if not user:
        await message.answer("❌ Пользователь не найден.")
        return
    lessons = await lesson_service.list_for_user(user.telegram_id)
    if not lessons:
        await message.answer(f"У @{user.username} нет занятий.")
        return
    text = f"📚 Занятия @{user.username}:\n\n" + "\n".join(
        f"{i + 1}. {l.topic} — {_fmt_dt(l.scheduled_at)}"
        for i, l in enumerate(lessons)
    )
    await message.answer(text)


# ─────────────────────────────────────────
# Добавить занятие (работает и в группе, поэтому БЕЗ _PRIVATE)
# ─────────────────────────────────────────

@router.message(StateFilter("*"), F.text == "Добавить занятие")
@router.message(StateFilter("*"), Command("addLesson"))
async def cmd_add_lesson(message: Message, state: FSMContext):
    if message.chat.type == "private":
        await message.answer(
            "⚠️ Эта команда доступна только в групповых чатах.")
        return
    await state.clear()
    user, _ = await get_or_create_user(message)
    try:
        auth_service.ensure_role(user, [UserRole.ADMIN, UserRole.OWNER])
    except PermissionDeniedException:
        await message.answer("У вас нет доступа к этой команде.")
        return
    await ensure_chat_exists(message)
    await _start_add_lesson(message, state)


@router.callback_query(F.data == "schedule_lesson")
async def cb_schedule_lesson(callback: CallbackQuery, state: FSMContext):
    user, _ = await get_or_create_user(callback)
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    await _start_add_lesson(callback.message, state)
    await callback.answer()


async def _start_add_lesson(message: Message, state: FSMContext):
    await state.update_data(lesson_author_id=message.from_user.id)
    await state.set_state(AddLessonSG.topic)
    await message.answer("Введите тему занятия:\n\n❌ Для отмены — /cancel")


@router.message(AddLessonSG.topic)
async def add_lesson_topic(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.chat.type != "private" and message.from_user.id != data.get("lesson_author_id"):
        return
    topic = message.text.strip()
    if not topic:
        await message.answer("Тема не может быть пустой. Попробуйте ещё раз.")
        return
    await state.update_data(topic=topic)

    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=d, callback_data=f"weekday:{i}")] for i, d in enumerate(days)]
    )
    await message.answer(
        "Выберите день или введите дату (дд:мм):",
        reply_markup=kb,
    )
    await state.set_state(AddLessonSG.day_selection)


@router.callback_query(F.data.startswith("weekday:"), AddLessonSG.day_selection)
async def add_lesson_weekday(callback: CallbackQuery, state: FSMContext):
    weekday_index = int(callback.data.split(":")[1])
    today = datetime.now(MSK).date()
    days_ahead = (weekday_index - today.weekday()) % 7
    target_date = today + timedelta(days=days_ahead if days_ahead > 0 else 7)
    await state.update_data(target_date=target_date)
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    await callback.message.edit_text(
        f"Выбран: {target_date.strftime('%d.%m.%Y')} ({day_names[weekday_index]})\n"
        f"Введите время (чч:мм) по МСК:"
    )
    await state.set_state(AddLessonSG.time)
    await callback.answer()


@router.message(AddLessonSG.day_selection)
async def add_lesson_custom_date(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.chat.type != "private" and message.from_user.id != data.get("lesson_author_id"):
        return
    text = message.text.strip()
    try:
        day, month = map(int, text.split(":"))
        now = datetime.now(MSK)
        target_date = datetime(now.year, month, day).date()
        if target_date < now.date():
            target_date = datetime(now.year + 1, month, day).date()
    except (ValueError, TypeError):
        await message.answer("❌ Неверный формат. Введите как дд:мм (например, 15:04).")
        return
    await state.update_data(target_date=target_date)
    await message.answer(f"Выбрана дата: {target_date.strftime('%d.%m.%Y')}\nВведите время (чч:мм) по МСК:")
    await state.set_state(AddLessonSG.time)


@router.message(AddLessonSG.time)
async def add_lesson_time(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.chat.type != "private" and message.from_user.id != data.get("lesson_author_id"):
        return
    text = message.text.strip()
    try:
        hour, minute = map(int, text.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ Неверный формат. Введите как чч:мм (например, 16:30).")
        return

    data = await state.get_data()
    target_date = data["target_date"]
    # Сохраняем как московское время (UTC+3)
    scheduled_at = datetime(
        target_date.year, target_date.month, target_date.day, hour, minute,
        tzinfo=MSK,
    )
    now_msk = datetime.now(MSK)
    if scheduled_at <= now_msk:
        await message.answer("⚠️ Это время уже прошло. Выберите будущее время.")
        return

    await state.update_data(scheduled_at=scheduled_at)
    topic = data["topic"]
    confirm_kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Верно", callback_data="confirm_lesson:yes")],
        [InlineKeyboardButton(text="🔄 Неверно", callback_data="confirm_lesson:no")],
    ]))
    await message.answer(
        f"Проверьте данные:\n\n"
        f"📚 Тема: {topic}\n"
        f"📅 Дата и время: {scheduled_at.strftime('%d.%m.%Y %H:%M')} МСК\n\n"
        f"Всё верно?",
        reply_markup=confirm_kb,
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
    await callback.message.edit_text(
        "✅ Данные подтверждены. Введите ссылку на занятие (Zoom, Google Meet и т.п.):"
    )
    await state.set_state(AddLessonSG.link)
    await callback.answer()


@router.message(AddLessonSG.link)
async def add_lesson_link(message: Message, state: FSMContext):
    data_check = await state.get_data()
    if message.chat.type != "private" and message.from_user.id != data_check.get("lesson_author_id"):
        return
    link = message.text.strip()
    if not link:
        await message.answer("Ссылка не может быть пустой. Попробуйте ещё раз.")
        return

    data = await state.get_data()
    topic = data["topic"]
    scheduled_at = data["scheduled_at"]
    actor, _ = await get_or_create_user(message)

    try:
        lesson = await lesson_service.schedule(
            actor=actor,
            chat_id=message.chat.id,
            scheduled_at=scheduled_at,
            topic=topic,
            lesson_link=link,
            repeat_type=None,
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании занятия: {str(e)}")
        await state.clear()
        return

    await message.answer(
        f"✅ Занятие назначено!\n\n"
        f"📚 Тема: {topic}\n"
        f"📅 Дата и время: {scheduled_at.strftime('%d.%m.%Y %H:%M')} МСК\n"
        f"🔗 Ссылка: {link}"
    )

    repeat_kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Единоразово", callback_data="repeat:one_time")],
        [InlineKeyboardButton(text="🔁 Еженедельно", callback_data="repeat:weekly")],
        [InlineKeyboardButton(text="🔁 Раз в 2 недели", callback_data="repeat:every_2_weeks")],
        [InlineKeyboardButton(text="🔁 Ежемесячно", callback_data="repeat:monthly")],
    ]))
    await state.update_data(lesson_id=lesson.id)
    await state.set_state(AddLessonSG.repeat_type)
    await message.answer("🔄 Как часто проводить это занятие?", reply_markup=repeat_kb)


@router.callback_query(F.data.startswith("chat_rem:"),
                       AddLessonSG.chat_reminder)
async def process_chat_reminder(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]

    if action == "skip":
        await callback.message.edit_text("Напоминание для чата пропущено.")
        await state.clear()
        await callback.answer()
        return

    minutes = int(action)
    data = await state.get_data()
    lesson_id = data.get("lesson_id")
    lesson = await lesson_repo.get_by_id(lesson_id)

    if not lesson:
        await callback.message.edit_text("Ошибка: занятие не найдено.")
        await state.clear()
        return

    remind_at = lesson.scheduled_at - timedelta(minutes=minutes)
    if remind_at < datetime.now(MSK):
        await callback.message.edit_text(
            "⚠️ Это время уже прошло. Напоминание не создано.")
        await state.clear()
        await callback.answer()
        return

    await reminder_repo.create(Reminder(
        user_id=None,
        chat_id=callback.message.chat.id,
        lesson_id=lesson_id,
        reminder_type=ReminderType.LESSON,
        remind_at=remind_at,
        custom_text=None,
        creator_id=callback.from_user.id,
        is_sent=False,
    ))

    await callback.message.edit_text(
        f"✅ Напоминание для чата создано!\n⏰ Напомню за {minutes} мин до начала."
    )
    await state.clear()
    await callback.answer()



@router.callback_query(F.data.startswith("repeat:"), AddLessonSG.repeat_type)
async def add_lesson_repeat_type(callback: CallbackQuery, state: FSMContext):
    repeat_val = callback.data.split(":")[1]
    data = await state.get_data()
    lesson_id = data.get("lesson_id")

    if repeat_val != "one_time" and lesson_id:
        from domain.entities import RepeatType
        lesson = await lesson_repo.get_by_id(lesson_id)
        if lesson:
            lesson.repeat_type = RepeatType(repeat_val)
            await lesson_repo.update(lesson)

    repeat_texts = {
        "one_time": "Единоразовое",
        "weekly": "Еженедельное",
        "every_2_weeks": "Раз в 2 недели",
        "monthly": "Ежемесячное",
    }
    repeat_label = repeat_texts.get(repeat_val, repeat_val)
    await callback.message.edit_text(f"✅ Периодичность: {repeat_label}")

    kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="15 мин до", callback_data="chat_rem:15")],
        [InlineKeyboardButton(text="1 час до", callback_data="chat_rem:60")],
        [InlineKeyboardButton(text="Пропустить", callback_data="chat_rem:skip")],
    ]))
    await state.set_state(AddLessonSG.chat_reminder)
    await callback.message.answer("📅 Создать напоминание для всего чата?", reply_markup=kb)
    await callback.answer()


# ─────────────────────────────────────────
# Удалить занятие
# ─────────────────────────────────────────

@router.message(StateFilter("*"), F.text == "Удалить занятие")
@router.message(Command("removeLesson"))
async def cmd_remove_lesson(message: Message, state: FSMContext):
    if message.chat.type == "private":
        await message.answer(
            "⚠️ Эта команда доступна только в групповых чатах.")
        return
    user, _ = await get_or_create_user(message)
    try:
        auth_service.ensure_role(user, [UserRole.ADMIN, UserRole.OWNER])
    except PermissionDeniedException:
        await message.answer("У вас нет доступа к этой команде.")
        return
    await state.clear()
    lessons = await lesson_service.list_for_chat(message.chat.id)
    if not lessons:
        await message.answer("Нет занятий для удаления.")
        return
    kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{l.topic} — {_fmt_dt(l.scheduled_at)}",
            callback_data=f"lesson_delete:{l.id}",
        )]
        for l in lessons[:10]
    ]))
    await message.answer("Выберите занятие для удаления:", reply_markup=kb)
    await state.set_state(RemoveLessonSG.select_lesson)


@router.callback_query(F.data.startswith("lesson_delete:"), RemoveLessonSG.select_lesson)
async def delete_lesson_cb(callback: CallbackQuery, state: FSMContext):
    lesson_id = int(callback.data.split(":")[1])
    await lesson_service.delete(lesson_id)
    await callback.message.answer("Занятие удалено.")
    await callback.answer()
    await state.clear()


# ─────────────────────────────────────────
# Добавить напоминание (только ЛС)
# ─────────────────────────────────────────

@router.message(_PRIVATE, StateFilter("*"), F.text == "Добавить напоминание")
@router.message(_PRIVATE, StateFilter("*"), Command("addReminder"))
async def pm_add_reminder(message: Message, state: FSMContext):
    await state.clear()
    user, _ = await get_or_create_user(message)
    if user.role in (UserRole.ADMIN, UserRole.OWNER):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Себе", callback_data="target:self")],
            [InlineKeyboardButton(text="Студенту", callback_data="target:student")],
            [InlineKeyboardButton(text="Преподу", callback_data="target:teacher")],
        ])
    elif user.role == UserRole.TEACHER:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Себе", callback_data="target:self")],
            [InlineKeyboardButton(text="Студенту", callback_data="target:student")],
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Себе", callback_data="target:self")],
        ])
    await message.answer(
        "Кому напоминание?\n\n❌ Для отмены — /cancel",
        reply_markup=add_cancel_button(kb),
    )
    await state.set_state(AddReminderSG.target)


@router.message(StateFilter("*"), Command("addReminder"))
async def cmd_add_reminder_group_guard(message: Message):
    """Блокирует /addReminder в группе."""
    if message.chat.type != "private":
        await message.answer("⚠️ Личные напоминания можно создавать только в личных сообщениях с ботом.")


@router.callback_query(F.data.startswith("target:"), AddReminderSG.target)
async def reminder_target(callback: CallbackQuery, state: FSMContext):
    target = callback.data.split(":")[1]
    await state.update_data(target=target)
    data = await state.get_data()

    # Если lesson_id уже в состоянии (из авто-потока после addLesson) — пропускаем выбор занятия
    existing_lesson_id = data.get("lesson_id")

    if target == "student":
        students = await user_repo.get_all_students()
        if not students:
            await answer_or_edit(callback.message, "Нет студентов.", state=state)
            await state.clear()
            await callback.answer()
            return
        kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=s.full_name or s.username, callback_data=f"student:{s.telegram_id}")]
            for s in students[:10]
        ]))
        await answer_or_edit(callback.message, "Выберите студента:", reply_markup=kb, state=state)
        await state.set_state(AddReminderSG.student)
        await callback.answer()
        return

    if target == "teacher":
        teachers = await user_repo.get_all_teachers()
        if not teachers:
            await answer_or_edit(callback.message, "Нет преподавателей.", state=state)
            await state.clear()
            await callback.answer()
            return
        kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t.full_name or t.username, callback_data=f"teacher:{t.telegram_id}")]
            for t in teachers[:10]
        ]))
        await answer_or_edit(callback.message, "Выберите преподавателя:", reply_markup=kb, state=state)
        await state.set_state(AddReminderSG.teacher)
        await callback.answer()
        return

    # target == "self"
    if existing_lesson_id:
        # Занятие уже выбрано — сразу к типу напоминания
        await _ask_reminder_type(callback.message, state)
    else:
        lessons = await lesson_service.upcoming(10)
        if not lessons:
            await answer_or_edit(callback.message, "Нет предстоящих занятий.", state=state)
            await state.clear()
            await callback.answer()
            return
        kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{l.topic} — {_fmt_dt(l.scheduled_at)}",
                callback_data=f"lesson:{l.id}",
            )]
            for l in lessons[:10]
        ]))
        await answer_or_edit(callback.message, "Выберите занятие:", reply_markup=kb, state=state)
        await state.set_state(AddReminderSG.lesson)
    await callback.answer()


@router.callback_query(F.data.startswith("student:"), AddReminderSG.student)
async def reminder_student(callback: CallbackQuery, state: FSMContext):
    student_id = int(callback.data.split(":")[1])
    await state.update_data(student_id=student_id)
    data = await state.get_data()

    existing_lesson_id = data.get("lesson_id")
    if existing_lesson_id:
        await _ask_reminder_type(callback.message, state)
        await callback.answer()
        return

    lessons = await lesson_service.upcoming(10)
    if not lessons:
        await answer_or_edit(callback.message, "Нет предстоящих занятий.", state=state)
        await state.clear()
        await callback.answer()
        return
    kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{l.topic} — {_fmt_dt(l.scheduled_at)}",
            callback_data=f"lesson:{l.id}",
        )]
        for l in lessons[:10]
    ]))
    await answer_or_edit(callback.message, "Выберите занятие:", reply_markup=kb, state=state)
    await state.set_state(AddReminderSG.lesson)
    await callback.answer()



@router.callback_query(F.data.startswith("teacher:"), AddReminderSG.teacher)
async def reminder_teacher(callback: CallbackQuery, state: FSMContext):
    teacher_id = int(callback.data.split(":")[1])
    await state.update_data(student_id=teacher_id)
    data = await state.get_data()
    existing_lesson_id = data.get("lesson_id")
    if existing_lesson_id:
        await _ask_reminder_type(callback.message, state)
        await callback.answer()
        return
    lessons = await lesson_service.upcoming(10)
    if not lessons:
        await answer_or_edit(callback.message, "Нет предстоящих занятий.", state=state)
        await state.clear()
        await callback.answer()
        return
    kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{l.topic} — {_fmt_dt(l.scheduled_at)}",
            callback_data=f"lesson:{l.id}",
        )]
        for l in lessons[:10]
    ]))
    await answer_or_edit(callback.message, "Выберите занятие:", reply_markup=kb, state=state)
    await state.set_state(AddReminderSG.lesson)
    await callback.answer()


@router.callback_query(F.data.startswith("lesson:"), AddReminderSG.lesson)
async def reminder_lesson(callback: CallbackQuery, state: FSMContext):
    lesson_id = int(callback.data.split(":")[1])
    await state.update_data(lesson_id=lesson_id)
    await _ask_reminder_type(callback.message, state)
    await callback.answer()


async def _ask_reminder_type(message: Message, state: FSMContext):
    kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Занятие", callback_data="rtype:lesson")],
        [InlineKeyboardButton(text="Домашка", callback_data="rtype:homework")],
        [InlineKeyboardButton(text="Свой текст", callback_data="rtype:custom")],
    ]))
    await answer_or_edit(message, "Тип напоминания:", reply_markup=kb, state=state)
    await state.set_state(AddReminderSG.topic)


@router.callback_query(F.data.startswith("rtype:"), AddReminderSG.topic)
async def reminder_type_selected(callback: CallbackQuery, state: FSMContext):
    rtype = callback.data.split(":")[1]
    await state.update_data(reminder_type=rtype)

    if rtype == "custom":
        await answer_or_edit(callback.message, "Напишите текст напоминания:", state=state)
        await state.set_state(AddReminderSG.custom_text)
        await callback.answer()
        return

    data = await state.get_data()
    await answer_or_edit(
        callback.message,
        "Выберите время напоминания до занятия:",
        reply_markup=build_reminder_time_keyboard(reminder_payload_from_state(data)),
        state=state,
    )
    await state.set_state(AddReminderSG.time)
    await callback.answer()


@router.message(AddReminderSG.custom_text)
async def reminder_custom_text(message: Message, state: FSMContext):
    await state.update_data(custom_text=message.text)
    data = await state.get_data()
    await answer_or_edit(
        message,
        "Выберите время напоминания до занятия:",
        reply_markup=build_reminder_time_keyboard(reminder_payload_from_state(data)),
        state=state,
    )
    await state.set_state(AddReminderSG.time)


@router.callback_query(F.data.startswith("rem_time:"), AddReminderSG.time)
async def reminder_time_quick(callback: CallbackQuery, state: FSMContext):
    raw = callback.data.split(":", 1)[1]
    value, payload = parse_reminder_time_payload(raw)

    if payload:
        update: dict = {}
        if payload.get("t"):
            update["target"] = payload["t"]
        if payload.get("s"):
            update["student_id"] = int(payload["s"])
        if payload.get("l"):
            update["lesson_id"] = int(payload["l"])
        if payload.get("tp"):
            update["reminder_type"] = payload["tp"]
        if update:
            await state.update_data(**update)

    if value == "custom":
        await answer_or_edit(callback.message, "Введите время (5m / 1h / 1:30:00):", state=state)
        await state.set_state(AddReminderSG.custom_time)
        await callback.answer()
        return

    actor = await resolve_user_from_tg(callback.from_user)
    await _create_reminder(callback.message, state, actor, value)
    await callback.answer()


@router.message(AddReminderSG.custom_time)
async def reminder_time_manual(message: Message, state: FSMContext):
    actor, _ = await get_or_create_user(message)
    await _create_reminder(message, state, actor, message.text)


@router.message(AddReminderSG.time)
async def reminder_time_text(message: Message, state: FSMContext):
    actor, _ = await get_or_create_user(message)
    await _create_reminder(message, state, actor, message.text)


async def _create_reminder(message: Message, state: FSMContext, actor, time_val: str):
    data = await state.get_data()

    target_val = data.get("target")
    student_id = data.get("student_id")
    lesson_id = data.get("lesson_id")
    reminder_type_val = data.get("reminder_type")

    target_id = actor.telegram_id if target_val == "self" else student_id

    if target_id is None or not lesson_id or not reminder_type_val:
        await answer_or_edit(
            message,
            "Не хватает данных для создания напоминания. Начните заново с /addReminder.",
            state=state,
        )
        await state.clear()
        return

    normalized = (time_val or "").strip().split()[0].lower()
    if not normalized:
        await answer_or_edit(message, "Введите время (5m / 1h / 1:30:00).", state=state)
        return

    try:
        await reminder_service.create_for_lesson(
            actor=actor,
            target_user_id=int(target_id),
            lesson_id=int(lesson_id),
            reminder_type=ReminderType(reminder_type_val),
            time_value=normalized,
            custom_text=data.get("custom_text"),
        )
        await answer_or_edit(message, "✅ Напоминание создано!", state=state)
    except Exception as e:
        await answer_or_edit(message, f"❌ {str(e)}", state=state)
    finally:
        await state.clear()


# ─────────────────────────────────────────
# Удалить напоминание (только ЛС)
# ─────────────────────────────────────────

@router.message(_PRIVATE, StateFilter("*"), F.text == "Удалить напоминание")
@router.message(_PRIVATE, StateFilter("*"), Command("removeReminder"))
async def pm_remove_reminder(message: Message, state: FSMContext):
    await state.clear()
    user, _ = await get_or_create_user(message)
    if user.role in (UserRole.ADMIN, UserRole.OWNER, UserRole.TEACHER):
        kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Себе", callback_data="target:self")],
            [InlineKeyboardButton(text="Студенту", callback_data="target:student")],
        ]))
    else:
        kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Себе", callback_data="target:self")],
        ]))
    await message.answer("Чьё напоминание удалить?", reply_markup=kb)
    await state.set_state(RemoveReminderSG.target)


@router.message(StateFilter("*"), Command("removeReminder"))
async def cmd_remove_reminder_group_guard(message: Message):
    if message.chat.type != "private":
        await message.answer("⚠️ Управлять напоминаниями можно только в личных сообщениях с ботом.")


@router.callback_query(F.data.startswith("target:"), RemoveReminderSG.target)
async def remove_reminder_target(callback: CallbackQuery, state: FSMContext):
    target = callback.data.split(":")[1]
    await state.update_data(target=target)

    if target == "student":
        students = await user_repo.get_all_students()
        if not students:
            await callback.message.answer("Нет студентов.")
            await state.clear()
            await callback.answer()
            return
        kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=s.full_name or s.username, callback_data=f"student:{s.telegram_id}")]
            for s in students[:10]
        ]))
        await callback.message.answer("Выберите студента:", reply_markup=kb)
        await state.set_state(RemoveReminderSG.student)
        await callback.answer()
        return

    # target == "self": показываем только те, что создал сам actor
    actor, _ = await get_or_create_user(callback)
    reminders = await reminder_service.list_for_user(callback.from_user.id)
    # Фильтруем: показываем только те, что создал сам пользователь
    own = [r for r in reminders if r.creator_id == actor.telegram_id]
    if not own:
        await callback.message.answer("Нет напоминаний, которые вы создали для себя.")
        await state.clear()
        await callback.answer()
        return

    await callback.message.answer("Выберите напоминание:", reply_markup=_reminders_kb(own))
    await state.set_state(RemoveReminderSG.select_reminder)
    await callback.answer()


@router.callback_query(F.data.startswith("student:"), RemoveReminderSG.student)
async def remove_reminder_student(callback: CallbackQuery, state: FSMContext):
    student_id = int(callback.data.split(":")[1])
    actor, _ = await get_or_create_user(callback)
    reminders = await reminder_service.list_for_user(student_id)
    # Показываем только те, что создал actor
    own = [r for r in reminders if r.creator_id == actor.telegram_id]
    if not own:
        await callback.message.answer("У этого студента нет напоминаний от вас.")
        await state.clear()
        await callback.answer()
        return
    await callback.message.answer("Выберите напоминание:", reply_markup=_reminders_kb(own))
    await state.set_state(RemoveReminderSG.select_reminder)
    await callback.answer()


@router.callback_query(F.data.startswith("reminder_delete:"), RemoveReminderSG.select_reminder)
async def delete_reminder_cb(callback: CallbackQuery, state: FSMContext):
    reminder_id = int(callback.data.split(":")[1])
    actor, _ = await get_or_create_user(callback)
    try:
        await reminder_service.delete(reminder_id, actor)
        await callback.message.answer("✅ Напоминание удалено.")
    except PermissionDeniedException as e:
        await callback.message.answer(f"❌ {str(e)}")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    await callback.answer()
    await state.clear()


def _reminders_kb(reminders: list) -> InlineKeyboardMarkup:
    return add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{r.reminder_type.value} — {_fmt_dt(r.remind_at)}",
            callback_data=f"reminder_delete:{r.id}",
        )]
        for r in reminders[:10]
    ]))


# ─────────────────────────────────────────
# Статистика
# ─────────────────────────────────────────

@router.message(StateFilter("*"), F.text == "Статистика")
@router.message(StateFilter("*"), Command("stats"))
async def cmd_stats(message: Message, state: FSMContext):
    await state.clear()
    user, _ = await get_or_create_user(message)

    if user.role not in (UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER):
        await message.answer("🔒 Статистика доступна только преподавателям и администраторам.")
        return

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
        period_stats = await statistics_service.get_period_statistics(actor=user, period_days=30)
        await message.answer(statistics_service.format_period_statistics(period_stats))

        if user.role == UserRole.TEACHER:
            teacher_stats = await statistics_service.get_teacher_statistics(actor=user, period_days=30)
            await message.answer(statistics_service.format_teacher_statistics(teacher_stats, period_days=30))

    except PermissionDeniedException as e:
        await message.answer(f"🔒 {str(e)}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")


# ─────────────────────────────────────────
# SQL-консоль (только OWNER, только ЛС)
# ─────────────────────────────────────────

@router.message(_PRIVATE, StateFilter("*"), F.text == "SQL консоль")
@router.message(_PRIVATE, StateFilter("*"), Command("sql"))
async def pm_sql(message: Message, state: FSMContext):
    await state.clear()
    user, _ = await get_or_create_user(message)
    if user.role != UserRole.OWNER:
        await message.answer("🔒 Только владелец может выполнять SQL-запросы.")
        return

    await message.answer(
        "📊 <b>SQL-консоль</b>\n\n"
        "Отправьте SELECT-запрос.\n\n"
        "• Разрешены только SELECT / WITH\n"
        "• Таймаут: 10 сек\n"
        "• Результат > 15 строк → CSV\n\n"
        "Пример: <code>SELECT * FROM users LIMIT 10</code>\n\nВведите запрос:",
        parse_mode="HTML",
    )
    await state.set_state(SqlConsoleSG.query)


@router.message(SqlConsoleSG.query)
async def sql_query(message: Message, state: FSMContext):
    user, _ = await get_or_create_user(message)
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        result = await analytics_service.execute_query(actor=user, query=message.text)

        if analytics_service.should_export_to_csv(result):
            summary = analytics_service.format_result_as_text(result, max_rows=5)
            from aiogram.types import BufferedInputFile
            csv_file = analytics_service.export_to_csv(result)
            await message.answer(summary)
            await message.answer_document(
                BufferedInputFile(csv_file.read(), filename=csv_file.name),
                caption=f"📎 Полный результат ({result.row_count} строк)",
            )
        else:
            await message.answer(analytics_service.format_result_as_text(result))

    except PermissionDeniedException as e:
        await message.answer(f"🔒 {str(e)}")
    except ValidationException as e:
        await message.answer(f"❌ {str(e)}")
    except Exception as e:
        await message.answer(f"❌ Непредвиденная ошибка:\n{str(e)}")
    finally:
        await state.clear()


# ─────────────────────────────────────────
# Общие команды
# ─────────────────────────────────────────

@router.message(StateFilter("*"), Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Действие отменено.")


@router.message(StateFilter("*"), Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📋 Команды:\n\n"
        "/start — начать работу\n"
        "/lessons — мои занятия\n"
        "/addLesson — добавить занятие\n"
        "/addReminder — добавить напоминание (только в ЛС)\n"
        "/removeReminder — удалить напоминание (только в ЛС)\n"
        "/stats — статистика\n"
        "/cancel — отменить текущее действие\n"
        "/help — эта справка"
    )


@router.message(CompleteLessonSG.custom_duration)
async def complete_lesson_custom_duration(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        lesson_id = data.get("lesson_id")
        if not lesson_id:
            await message.answer("Ошибка: занятие не найдено.")
            await state.clear()
            return

        try:
            duration_minutes = int(message.text.strip())
        except ValueError:
            await message.answer("❌ Введите число (минуты), например: 75")
            return

        if not (1 <= duration_minutes <= 300):
            await message.answer("❌ Длительность должна быть от 1 до 300 минут.")
            return

        user = await user_repo.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("Пользователь не найден.")
            await state.clear()
            return

        lesson = await lesson_service.complete_lesson(
            lesson_id=lesson_id, actor=user, duration_minutes=duration_minutes
        )
        await message.answer(
            f"✅ Занятие завершено!\n\n"
            f"📚 Тема: {lesson.topic}\n"
            f"⏱ Длительность: {duration_minutes} мин"
        )
    except (ValidationException, PermissionDeniedException) as e:
        await message.answer(f"❌ {str(e)}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        await state.clear()


# ─────────────────────────────────────────
# Вспомогательное
# ─────────────────────────────────────────

def _fmt_dt(dt: datetime) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is not None:
        dt = dt.astimezone(MSK)
    return dt.strftime("%d.%m %H:%M")
