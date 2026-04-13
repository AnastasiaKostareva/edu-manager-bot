from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from domain.entities import UserRole


def main_menu_keyboard(role: UserRole) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text="Мои занятия"), KeyboardButton(text="Статистика")],
        [KeyboardButton(text="Добавить занятие"), KeyboardButton(text="Удалить занятие")],
        [KeyboardButton(text="Добавить напоминание"), KeyboardButton(text="Удалить напоминание")],
    ]

    if role == UserRole.OWNER:
        rows.append([KeyboardButton(text="SQL консоль")])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def quick_actions_keyboard(role: UserRole) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="Мои занятия", callback_data="ux:lessons")],
        [InlineKeyboardButton(text="Добавить занятие", callback_data="ux:add_lesson")],
        [InlineKeyboardButton(text="Добавить напоминание", callback_data="ux:add_reminder")],
        [InlineKeyboardButton(text="Статистика", callback_data="ux:stats")],
    ]

    if role == UserRole.OWNER:
        rows.append([InlineKeyboardButton(text="SQL консоль", callback_data="ux:sql")])

    return InlineKeyboardMarkup(inline_keyboard=rows)

