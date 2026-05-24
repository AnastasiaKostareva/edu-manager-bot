"""
Общие inline-callback хендлеры (cancel, ux:*, start_lesson).
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from infrastructure.database.repositories import LessonRepository, UserRepository
from infrastructure.telegram.handlers.helpers import get_or_create_user, resolve_user_from_tg
from domain.entities import UserRole

router = Router()

user_repo = UserRepository()
lesson_repo = LessonRepository()


@router.callback_query(F.data == "cancel_action")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text("✅ Действие отменено.")
    except Exception:
        await callback.message.answer("✅ Действие отменено.")
    await callback.answer()


@router.callback_query(F.data.startswith("ux:"))
async def cb_ux_router(callback: CallbackQuery, state: FSMContext):
    """Обработчик быстрых действий. Корректно использует callback.from_user."""
    from infrastructure.telegram.handlers.private import (
        pm_lessons, pm_add_reminder, cmd_stats, pm_sql,
    )
    action = callback.data.split(":", 1)[1]

    # Создаём фиктивное сообщение-обёртку: подменяем from_user на реального пользователя
    # Передаём сам callback — функции должны работать с ним
    if action == "lessons":
        actor = await resolve_user_from_tg(callback.from_user)
        # Показываем занятия напрямую, не через message-хендлер
        from application.use_cases.lesson import LessonService
        lesson_service = LessonService(lesson_repo)
        lessons = await lesson_service.list_for_user(actor.telegram_id)

        from infrastructure.telegram.handlers.private import _fmt_dt
        from infrastructure.telegram.keyboards import add_cancel_button
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        if actor.role in (UserRole.ADMIN, UserRole.OWNER):
            kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="search_user_start")]
            ]))
        else:
            kb = None

        if not lessons:
            await callback.message.answer("📚 Нет назначенных занятий.", reply_markup=kb)
        else:
            text = "📚 Ваши занятия:\n\n" + "\n".join(
                f"{i + 1}. {l.topic} — {_fmt_dt(l.scheduled_at)}"
                for i, l in enumerate(lessons)
            )
            await callback.message.answer(text, reply_markup=kb)

    elif action == "add_reminder":
        if callback.message.chat.type != "private":
            await callback.message.answer(
                "⚠️ Создавать напоминания можно только в личных сообщениях с ботом."
            )
        else:
            actor = await resolve_user_from_tg(callback.from_user)
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            from infrastructure.telegram.keyboards import add_cancel_button
            from infrastructure.telegram.states import AddReminderSG

            if actor.role in (UserRole.ADMIN, UserRole.OWNER):
                kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Себе", callback_data="target:self")],
                    [InlineKeyboardButton(text="Студенту", callback_data="target:student")],
                    [InlineKeyboardButton(text="Преподу", callback_data="target:teacher")],
                ]))
            elif actor.role == UserRole.TEACHER:
                kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Себе", callback_data="target:self")],
                    [InlineKeyboardButton(text="Студенту", callback_data="target:student")],
                ]))
            else:
                kb = add_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Себе", callback_data="target:self")],
                ]))
            await callback.message.answer("Кому напоминание?", reply_markup=kb)
            await state.set_state(AddReminderSG.target)

    elif action == "stats":
        actor = await resolve_user_from_tg(callback.from_user)
        if actor.role not in (UserRole.TEACHER, UserRole.ADMIN, UserRole.OWNER):
            await callback.message.answer("🔒 Статистика доступна только преподавателям и администраторам.")
        else:
            from application.use_cases.statistics import StatisticsService
            statistics_service = StatisticsService()
            try:
                period_stats = await statistics_service.get_period_statistics(actor=actor, period_days=30)
                await callback.message.answer(statistics_service.format_period_statistics(period_stats))
            except Exception as e:
                await callback.message.answer(f"❌ Ошибка статистики: {str(e)}")

    elif action == "sql":
        actor = await resolve_user_from_tg(callback.from_user)
        if actor.role != UserRole.OWNER:
            await callback.message.answer("🔒 Только владелец может использовать SQL-консоль.")
        elif callback.message.chat.type != "private":
            await callback.message.answer("⚠️ SQL-консоль доступна только в личных сообщениях.")
        else:
            from infrastructure.telegram.states import SqlConsoleSG
            await callback.message.answer(
                "📊 SQL-консоль. Введите SELECT-запрос:"
            )
            await state.set_state(SqlConsoleSG.query)

    await callback.answer()


@router.callback_query(F.data.startswith("start_lesson:"))
async def cb_start_lesson(callback: CallbackQuery):
    """Нажатие 'Начать занятие' из напоминания планировщика."""
    lesson_id = int(callback.data.split(":")[1])
    lesson = await lesson_repo.get_by_id(lesson_id)
    if not lesson:
        await callback.answer("Занятие не найдено.", show_alert=True)
        return
    from infrastructure.telegram.handlers.private import _fmt_dt
    await callback.message.edit_text(
        f"▶️ Занятие начато!\n\n"
        f"📚 Тема: {lesson.topic}\n"
        f"📅 Запланировано: {_fmt_dt(lesson.scheduled_at)}"
    )
    await callback.answer()
