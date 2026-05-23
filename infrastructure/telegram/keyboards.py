from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, \
    KeyboardButton, ReplyKeyboardMarkup

from domain.entities import User, UserRole


def main_menu_keyboard(role: UserRole,
                       is_group: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню (Reply-кнопки). В групповом чате убираем кнопки напоминаний."""
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text="Мои занятия")]
    ]

    if not is_group:
        rows.append([KeyboardButton(text="Добавить напоминание"),
                     KeyboardButton(text="Удалить напоминание")])
    if is_group:
        rows.append([KeyboardButton(text="Добавить занятие"),
                     KeyboardButton(text="Удалить занятие")])

    if role == UserRole.OWNER and not is_group:
        rows.append([KeyboardButton(text="SQL консоль"),KeyboardButton(text="Статистика")])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие или /cancel для отмены",
    )


def add_cancel_button(keyboard: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Добавляет кнопку 'Отмена' в конец инлайн-клавиатуры."""
    cancel_btn = [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
    # Если последняя строка уже содержит кнопки, добавим отмену новой строкой
    keyboard.inline_keyboard.append(cancel_btn)
    return keyboard


def quick_actions_keyboard(role: UserRole,
                           is_group: bool = False) -> InlineKeyboardMarkup:
    """Быстрые действия (Inline-кнопки). В групповом чате убираем кнопки напоминаний."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="Мои занятия", callback_data="ux:lessons")],
    ]

    if not is_group:
        rows.append([InlineKeyboardButton(text="Добавить напоминание",
                                          callback_data="ux:add_reminder")])

    rows.append(
        [InlineKeyboardButton(text="Статистика", callback_data="ux:stats")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_user_search_results_kb(users: list[User]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for u in users:
        name = (u.full_name or "").strip()
        handle = f"@{u.username}" if u.username else "нет юзернейма"
        label = f"{name} — {handle}" if name else handle
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"search_sel:{u.telegram_id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
