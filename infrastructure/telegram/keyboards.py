from __future__ import annotations

import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, \
    KeyboardButton, ReplyKeyboardMarkup

from domain.entities import User, UserRole

_DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def build_weekday_keyboard(today: datetime.date) -> InlineKeyboardMarkup:
    """Day-of-week selection keyboard.

    Buttons run from today (offset=0) through today+6 (offset=6).
    callback_data = "weekday_offset:{0..6}"
    offset=0 means TODAY, never the next occurrence of that weekday.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for offset in range(7):
        date = today + datetime.timedelta(days=offset)
        label = f"{_DAY_NAMES[date.weekday()]} {date.strftime('%d.%m')}"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"weekday_offset:{offset}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_keyboard(role: UserRole, is_group: bool = False) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text="Мои занятия")]
    ]

    if not is_group:
        rows.append([
            KeyboardButton(text="Добавить напоминание"),
            KeyboardButton(text="Удалить напоминание"),
        ])

    if is_group and role in (UserRole.OWNER, UserRole.ADMIN):
        rows.append([
            KeyboardButton(text="Добавить занятие"),
            KeyboardButton(text="Удалить занятие"),
        ])

    if role == UserRole.OWNER and not is_group:
        rows.append([KeyboardButton(text="SQL консоль"), KeyboardButton(text="Статистика")])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие или /cancel для отмены",
    )


def add_cancel_button(
    keyboard: InlineKeyboardMarkup,
    initiator_id: int | None = None,
) -> InlineKeyboardMarkup:
    """Add a cancel button as the last row.

    If initiator_id is given the callback_data becomes "cancel_action:{initiator_id}"
    so cb_cancel can verify the presser without touching FSM state (which is
    per-user in aiogram 3 and would always be empty for non-initiators).
    """
    if initiator_id is not None:
        cb_data = f"cancel_action:{initiator_id}"
    else:
        cb_data = "cancel_action"
    keyboard.inline_keyboard.append(
        [InlineKeyboardButton(text="\u274c Отмена", callback_data=cb_data)]
    )
    return keyboard


def quick_actions_keyboard(role: UserRole, is_group: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="Мои занятия", callback_data="ux:lessons")],
    ]

    if not is_group:
        rows.append([InlineKeyboardButton(text="Добавить напоминание",
                                          callback_data="ux:add_reminder")])

    rows.append([InlineKeyboardButton(text="Статистика", callback_data="ux:stats")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_user_search_results_kb(users: list[User]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for u in users:
        name = (u.full_name or "").strip()
        no_username = "нет юзернейма"
        handle = f"@{u.username}" if u.username else no_username
        label = f"{name} — {handle}" if name else handle
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"search_sel:{u.telegram_id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
