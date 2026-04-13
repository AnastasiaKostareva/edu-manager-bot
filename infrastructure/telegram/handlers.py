from __future__ import annotations

from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup

from application.config import get_config
from application.use_cases.auth import AuthService
from application.use_cases.lesson import LessonService
from application.use_cases.reminder import ReminderService
from application.use_cases.chat import ChatService
from application.use_cases.analytics import AnalyticsService
from application.use_cases.statistics import StatisticsService
from domain.entities import LessonStatus, ReminderTime, ReminderType, RepeatType, User, UserRole, Chat
from domain.exceptions import PermissionDeniedException, ValidationException
from infrastructure.database.repositories import (
    LessonRepository,
    ReminderRepository,
    UserRepository,
    ChatRepository,
    ChatMemberRepository,
)
from infrastructure.telegram.states import AddLessonSG, AddReminderSG, RemoveLessonSG, RemoveReminderSG, SqlConsoleSG, CompleteLessonSG
from infrastructure.telegram.keyboards import main_menu_keyboard, quick_actions_keyboard


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


def get_user_role(telegram_id: int) -> UserRole:
    config = get_config()
    admin_ids = {str(admin_id).strip() for admin_id in config.admins}
    return UserRole.OWNER if str(telegram_id) in admin_ids else UserRole.STUDENT


async def get_or_create_user(message: Message) -> tuple[User, bool]:
    existing = await user_repo.get_by_telegram_id(message.from_user.id)
    expected_role = get_user_role(message.from_user.id)

    if existing:
        updated = False

        # Автоповышаем пользователя до owner, если его id добавили в appsettings.yaml позже.
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
        await message.answer("Не могу найти тебя в системе.\nОбратись к @admin")
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


@router.message(CommandStart())
async def cmd_start(message: Message):
    user, existed = await get_or_create_user(message)

    if existed:
        await message.answer(
            f"Приветствую, {user.username}!\n"
            f"Твоя роль: {user.role.value}\n"
            f"Если что-то неверно — обратись к @admin",
            reply_markup=main_menu_keyboard(user.role),
        )
        await message.answer(
            "Быстрые действия:",
            reply_markup=quick_actions_keyboard(user.role),
        )
        return

    await message.answer(
        f"Добро пожаловать, {user.username}!\n"
        f"Регистрация завершена. Твоя роль: {user.role.value}\n"
        f"Если нужно изменить роль — обратись к @admin",
        reply_markup=main_menu_keyboard(user.role),
    )
    await message.answer(
        "Быстрые действия:",
        reply_markup=quick_actions_keyboard(user.role),
    )


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


@router.message(Command("init"))
async def cmd_init(message: Message):
    """
    Команда /init для инициализации чата преподавателем.
    Использование: /init @username или /init (если студент уже писал в чат)
    """
    # Получаем пользователя-инициатора
    actor = await user_repo.get_by_telegram_id(message.from_user.id)
    if not actor:
        await message.answer("Не могу найти тебя в системе.\nОбратись к @admin")
        return

    # Проверка прав доступа
    if actor.role not in (UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER):
        await message.answer(
            "❌ Отказано в доступе.\n"
            "Только преподаватели и администраторы могут инициализировать чаты."
        )
        return

    # Проверяем, не инициализирован ли чат уже
    is_initialized = await chat_service.is_chat_initialized(message.chat.id)
    if is_initialized:
        members = await chat_member_repo.get_members_by_chat(message.chat.id)
        member_names = []
        for member in members:
            user = await user_repo.get_by_telegram_id(member.user_id)
            if user:
                member_names.append(f"{user.full_name or user.username} ({user.role.value})")

        await message.answer(
            f"⚠️ Чат уже инициализирован.\n"
            f"Участники:\n" + "\n".join(f"• {name}" for name in member_names)
        )
        return

    # Парсим аргументы команды
    command_parts = message.text.split(maxsplit=1)
    student_username = command_parts[1] if len(command_parts) > 1 else None

    try:
        chat_title = message.chat.title or message.chat.full_name or "Личный чат"
        chat_type = message.chat.type

        # Попытка инициализации с username
        if student_username:
            chat, teacher_member, student_member = await chat_service.initialize_chat(
                actor=actor,
                chat_id=message.chat.id,
                chat_title=chat_title,
                chat_type=chat_type,
                student_username=student_username,
            )

            student = await user_repo.get_by_telegram_id(student_member.user_id)
            await message.answer(
                f"✅ Чат успешно настроен!\n\n"
                f"👨‍🏫 Преподаватель: {actor.full_name or actor.username}\n"
                f"👨‍🎓 Студент: {student.full_name or student.username}\n\n"
                f"Теперь вы можете использовать команды для управления расписанием."
            )
        else:
            await message.answer(
                "⚠️ Не указан username студента.\n\n"
                "Используйте: /init @username\n\n"
                "Если у студента скрыт username:\n"
                "1. Попросите студента написать любое сообщение в этот чат\n"
                "2. Повторите команду /init с его telegram_id"
            )

    except ValidationException as e:
        await message.answer(f"❌ Ошибка валидации: {str(e)}")
    except PermissionDeniedException as e:
        await message.answer(f"❌ Отказано в доступе: {str(e)}")
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка: {str(e)}")


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

    await ensure_chat_exists(message)

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

    from aiogram.types import InlineKeyboardButton
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

    from aiogram.types import InlineKeyboardButton
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
    from aiogram.types import InlineKeyboardButton
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

        from aiogram.types import InlineKeyboardButton
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

    from aiogram.types import InlineKeyboardButton
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

    from aiogram.types import InlineKeyboardButton
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

    from aiogram.types import InlineKeyboardButton
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
    from aiogram.types import InlineKeyboardButton
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

        from aiogram.types import InlineKeyboardButton
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
    from aiogram.types import InlineKeyboardButton
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


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """
    Команда для просмотра статистики.
    Доступна преподавателям, администраторам и владельцу.
    """
    user = await get_user_or_reply(message)
    if not user:
        return

    try:
        # Проверяем права доступа
        if user.role not in (UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER):
            await message.answer(
                "🔒 У вас нет доступа к этой команде\n"
                "Статистика доступна преподавателям и администраторам"
            )
            return

        # Отправляем индикатор "печатает"
        await message.bot.send_chat_action(message.chat.id, "typing")

        # Получаем статистику за 30 дней
        period_stats = await statistics_service.get_period_statistics(
            actor=user,
            period_days=30
        )

        # Форматируем и отправляем
        stats_text = statistics_service.format_period_statistics(period_stats)
        await message.answer(stats_text)

        # Если это преподаватель, показываем его личную статистику
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
    """
    Команда для выполнения SQL-запросов.
    Доступна только владельцу для получения аналитики.
    """
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
    """
    Обработчик SQL-запроса с экспортом в CSV для больших результатов.
    """
    user, _ = await get_or_create_user(message)

    # Отправляем индикатор "печатает", т.к. запрос может выполняться долго
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        # Выполняем запрос через защищенный сервис
        result = await analytics_service.execute_query(
            actor=user,
            query=message.text
        )

        # Проверяем, нужно ли экспортировать в CSV
        if analytics_service.should_export_to_csv(result):
            # Отправляем краткую статистику + CSV-файл
            summary = analytics_service.format_result_as_text(result, max_rows=5)

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
            # Отправляем результат текстом
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
    """
    Обработчик нажатия кнопок завершения занятия.
    Формат: complete_lesson:<lesson_id>:<duration|custom>
    """
    try:
        parts = callback.data.split(":")
        lesson_id = int(parts[1])
        duration_value = parts[2]

        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        if duration_value == "custom":
            # Переход в режим ввода кастомной длительности
            await state.update_data(lesson_id=lesson_id)
            await state.set_state(CompleteLessonSG.custom_duration)
            await callback.message.edit_text(
                f"{callback.message.text}\n\n"
                "✏️ Введите длительность в минутах (например: 75):"
            )
            await callback.answer()
            return

        # Обработка стандартной длительности
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
            await callback.answer("Занятие успешно завершено!", show_alert=True)

        except (ValidationException, PermissionDeniedException) as e:
            await callback.answer(f"Ошибка: {str(e)}", show_alert=True)

    except Exception as e:
        await callback.answer(f"Произошла ошибка: {str(e)}", show_alert=True)


@router.message(CompleteLessonSG.custom_duration)
async def complete_lesson_custom_duration(message: Message, state: FSMContext):
    """
    Обработчик ввода кастомной длительности занятия.
    """
    try:
        data = await state.get_data()
        lesson_id = data.get("lesson_id")

        if not lesson_id:
            await message.answer("Ошибка: занятие не найдено")
            await state.clear()
            return

        # Парсим введенное значение
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
