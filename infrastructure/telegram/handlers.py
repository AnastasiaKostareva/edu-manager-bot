from __future__ import annotations

from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from application.config import get_config
from application.use_cases.auth import AuthService
from application.use_cases.lesson import LessonService
from application.use_cases.reminder import ReminderService
from domain.entities import LessonStatus, ReminderTime, ReminderType, RepeatType, User, UserRole
from domain.exceptions import PermissionDeniedException, ValidationException
from infrastructure.database.repositories import LessonRepository, ReminderRepository, UserRepository
from infrastructure.telegram.states import AddLessonSG, AddReminderSG, RemoveLessonSG, RemoveReminderSG, SqlConsoleSG


router = Router()

user_repo = UserRepository()
lesson_repo = LessonRepository()
reminder_repo = ReminderRepository()

auth_service = AuthService()
lesson_service = LessonService(lesson_repo)
reminder_service = ReminderService(reminder_repo, lesson_repo)


def get_user_role(telegram_id: int) -> UserRole:
    config = get_config()
    return UserRole.OWNER if str(telegram_id) in config.admins else UserRole.STUDENT


async def get_or_create_user(message: Message) -> tuple[User, bool]:
    existing = await user_repo.get_by_telegram_id(message.from_user.id)
    if existing:
        return existing, True

    user = User(
        telegram_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
        role=get_user_role(message.from_user.id),
        is_active=True,
    )
    created = await user_repo.create(user)
    return created, False


async def get_user_or_reply(message: Message) -> User | None:
    user = await user_repo.get_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Не могу найти тебя в системе.\nОбратись к @admin")
        return None
    return user


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = await user_repo.get_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Не могу найти тебя в системе.\nОбратись к @admin")
        return

    await message.answer(
        f"Приветствую, {user.username}!\n"
        f"Твоя роль: {user.role.value}\n"
        f"Если что-то неверно — обратись к @admin"
    )


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
        await message.answer("Сейчас нет назначенных занятий\nИспользуй /addLesson")
        return

    text = "Ваши занятия:\n" + "\n".join(
        f"{i+1}) {l.topic} — {l.scheduled_at.strftime('%d:%m %H:%M')}" for i, l in enumerate(lessons)
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
        f"{i+1}) {l.topic} — {l.scheduled_at.strftime('%d:%m %H:%M')}" for i, l in enumerate(lessons)
    )
    await message.answer(text)
    await state.clear()


@router.message(Command("addLesson"))
async def cmd_add_lesson(message: Message, state: FSMContext):
    user = await get_user_or_reply(message)
    if not user:
        return
    try:
        auth_service.ensure_role(user, [UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER])
    except PermissionDeniedException:
        await message.answer("У вас нет доступа к этой команде")
        return

    await message.answer("Введите ссылку на занятие")
    await state.set_state(AddLessonSG.link)


@router.message(AddLessonSG.link)
async def add_lesson_link(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    await message.answer("Введите тему занятия")
    await state.set_state(AddLessonSG.title)


@router.message(AddLessonSG.title)
async def add_lesson_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="weekly", callback_data="repeat:weekly")],
            [InlineKeyboardButton(text="every_2_weeks", callback_data="repeat:every_2_weeks")],
            [InlineKeyboardButton(text="monthly", callback_data="repeat:monthly")],
            [InlineKeyboardButton(text="one_time", callback_data="repeat:one_time")],
        ]
    )
    await message.answer("Выберите тип повторения", reply_markup=kb)
    await state.set_state(AddLessonSG.repeat_type)


@router.callback_query(F.data.startswith("repeat:"), AddLessonSG.repeat_type)
async def add_lesson_repeat_type(callback: CallbackQuery, state: FSMContext):
    repeat_value = callback.data.split(":", 1)[1]
    await state.update_data(repeat_type=repeat_value)
    await callback.message.answer("Введите дату (dd:mm)")
    await state.set_state(AddLessonSG.date)
    await callback.answer()


@router.message(AddLessonSG.date)
async def add_lesson_date(message: Message, state: FSMContext):
    await state.update_data(date=message.text)
    await message.answer("Введите время (hh:mm)")
    await state.set_state(AddLessonSG.time)


@router.message(AddLessonSG.time)
async def add_lesson_time(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        date_parts = (data.get("date") or "").split(":")
        time_parts = (message.text or "").split(":")
        if len(date_parts) != 2 or len(time_parts) != 2:
            raise ValidationException("Неверный формат даты/времени")

        day = int(date_parts[0])
        month = int(date_parts[1])
        hour = int(time_parts[0])
        minute = int(time_parts[1])

        now = datetime.now()
        scheduled_at = datetime(now.year, month, day, hour, minute)
        if scheduled_at <= now:
            scheduled_at = scheduled_at.replace(year=now.year + 1)

        actor = await get_user_or_reply(message)
        if not actor:
            return

        repeat_type = None
        if data.get("repeat_type"):
            repeat_type = RepeatType(data["repeat_type"])
        await lesson_service.schedule(
            actor=actor,
            chat_id=message.chat.id,
            scheduled_at=scheduled_at,
            topic=data.get("title") or "",
            lesson_link=data.get("link"),
            repeat_type=repeat_type,
        )
        await message.answer("Занятие назначено")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
    finally:
        await state.clear()


@router.message(Command("removeLesson"))
async def cmd_remove_lesson(message: Message, state: FSMContext):
    lessons = await lesson_service.list_for_chat(message.chat.id)
    if not lessons:
        await message.answer("Нет занятий для удаления")
        await state.clear()
        return

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
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


@router.callback_query(F.data.startswith("lesson_delete:"), RemoveLessonSG.select_lesson)
async def delete_lesson(callback: CallbackQuery, state: FSMContext):
    lesson_id = int(callback.data.split(":")[1])
    await lesson_service.delete(lesson_id)
    await callback.message.answer("Занятие удалено")
    await callback.answer()
    await state.clear()


@router.message(Command("addReminder"))
async def cmd_add_reminder(message: Message, state: FSMContext):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Себе", callback_data="target:self")],
            [InlineKeyboardButton(text="Студенту", callback_data="target:student")],
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

        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=s.username, callback_data=f"student:{s.telegram_id}")]
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

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
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

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
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

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Занятие", callback_data="topic:lesson")],
            [InlineKeyboardButton(text="Домашка", callback_data="topic:homework")],
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

    await callback.message.answer("Выберите время: 5m/10m/15m/30m/1h/2h/4h/8h/12h/1d или custom")
    await state.set_state(AddReminderSG.time)
    await callback.answer()


@router.message(AddReminderSG.custom_text)
async def reminder_custom_text(message: Message, state: FSMContext):
    await state.update_data(custom_text=message.text)
    await message.answer("Выберите время: 5m/10m/15m/30m/1h/2h/4h/8h/12h/1d или dd:hh:mm")
    await state.set_state(AddReminderSG.time)


@router.message(AddReminderSG.time)
async def reminder_time(message: Message, state: FSMContext):
    data = await state.get_data()
    time_val = (message.text or "").strip()

    actor, _ = await get_or_create_user(message)
    target_id = actor.telegram_id if data.get("target") == "self" else data.get("student_id")
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
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Себе", callback_data="target:self")],
            [InlineKeyboardButton(text="Студенту", callback_data="target:student")],
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

        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=s.username, callback_data=f"student:{s.telegram_id}")]
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

    await callback.message.answer("Выберите напоминание:", reply_markup=_reminders_keyboard(reminders))
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

    await callback.message.answer("Выберите напоминание:", reply_markup=_reminders_keyboard(reminders))
    await state.set_state(RemoveReminderSG.select_reminder)
    await callback.answer()


def _reminders_keyboard(reminders: list) -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
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


@router.callback_query(F.data.startswith("reminder_delete:"), RemoveReminderSG.select_reminder)
async def delete_reminder(callback: CallbackQuery, state: FSMContext):
    reminder_id = int(callback.data.split(":")[1])
    await reminder_service.delete(reminder_id)
    await callback.message.answer("Напоминание удалено")
    await callback.answer()
    await state.clear()


@router.message(Command("sql"))
async def cmd_sql(message: Message, state: FSMContext):
    user, _ = await get_or_create_user(message)
    if user.role != UserRole.OWNER:
        await message.answer("У вас нет доступа к этой команде")
        return

    await message.answer("Введите SQL запрос")
    await state.set_state(SqlConsoleSG.query)


@router.message(SqlConsoleSG.query)
async def sql_query(message: Message, state: FSMContext):
    from tortoise import connections

    try:
        conn = connections.get("default")
        result = await conn.execute_query_dict(message.text)

        if result:
            text = "\n".join(str(row) for row in result[:10])
            await message.answer(f"Результат:\n{text}")
        else:
            await message.answer("Запрос выполнен")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
    finally:
        await state.clear()
