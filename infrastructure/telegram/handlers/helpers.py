from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from application.config import get_config
from domain.entities import User, UserRole, Chat
from infrastructure.database.repositories import UserRepository, ChatRepository
from infrastructure.telegram.keyboards import add_cancel_button

MSK = timezone(timedelta(hours=3))

user_repo = UserRepository()
chat_repo = ChatRepository()


def get_user_role(telegram_id: int) -> UserRole:
    config = get_config()
    admin_ids = {str(a).strip() for a in config.admins}
    return UserRole.OWNER if str(telegram_id) in admin_ids else UserRole.STUDENT


async def get_or_create_user(event: Message | CallbackQuery) -> tuple[User, bool]:
    """Получает или создаёт пользователя. Синхронизирует роль с конфигом."""
    from_user = event.from_user
    user_id = from_user.id
    username = from_user.username or f"user_{user_id}"
    full_name = from_user.full_name
    expected_role = get_user_role(user_id)

    existing = await user_repo.get_by_telegram_id(user_id)
    if existing:
        if (
            existing.username != username
            or existing.full_name != full_name
            or existing.role != expected_role
        ):
            existing.username = username
            existing.full_name = full_name
            existing.role = expected_role
            await user_repo.update(existing)
        return existing, False

    new_user = User(
        telegram_id=user_id,
        username=username,
        full_name=full_name,
        role=expected_role,
    )
    await user_repo.create(new_user)
    return new_user, True


async def resolve_user_from_tg(tg_user) -> User:
    """Получает или создаёт пользователя из объекта TelegramUser (не из Message)."""
    existing = await user_repo.get_by_telegram_id(tg_user.id)
    if existing:
        return existing
    new_user = User(
        telegram_id=tg_user.id,
        username=tg_user.username or f"user_{tg_user.id}",
        full_name=tg_user.full_name,
        role=get_user_role(tg_user.id),
        is_active=True,
    )
    return await user_repo.create(new_user)


async def ensure_chat_exists(message: Message) -> None:
    existing = await chat_repo.get_by_id(message.chat.id)
    if existing:
        return
    chat_title = message.chat.title or message.chat.full_name or "Личный чат"
    chat = Chat(
        chat_id=message.chat.id,
        chat_title=chat_title,
        chat_type=message.chat.type,
        created_at=datetime.now(timezone.utc),
        is_active=True,
    )
    await chat_repo.create(chat)


async def get_admin_contact_username() -> str:
    config = get_config()
    for admin_id_str in config.admins:
        try:
            user = await user_repo.get_by_telegram_id(int(admin_id_str))
            if user and user.username:
                return user.username
        except (ValueError, TypeError):
            continue
    return "admin"


def build_reminder_time_keyboard(payload: dict[str, str] | None = None) -> InlineKeyboardMarkup:
    options = ["5m", "10m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d"]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    suffix = ""
    if payload:
        parts = [f"{k}={v}" for k, v in payload.items() if v is not None and v != ""]
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
    return add_cancel_button(InlineKeyboardMarkup(inline_keyboard=rows))


def reminder_payload_from_state(data: dict) -> dict[str, str]:
    payload: dict[str, str] = {}
    if data.get("target"):
        payload["t"] = str(data["target"])
    if data.get("student_id"):
        payload["s"] = str(data["student_id"])
    if data.get("lesson_id"):
        payload["l"] = str(data["lesson_id"])
    if data.get("reminder_type"):
        payload["tp"] = str(data["reminder_type"])
    return payload


def parse_reminder_time_payload(raw: str) -> tuple[str, dict[str, str]]:
    if "|" not in raw:
        return raw, {}
    value, payload_raw = raw.split("|", 1)
    payload: dict[str, str] = {}
    for part in payload_raw.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            payload[k] = v
    return value, payload


async def answer_or_edit(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    state: FSMContext | None = None,
) -> None:
    """Редактирует последнее бот-сообщение если возможно, иначе отправляет новое."""
    bot = message.bot

    if getattr(message, "from_user", None) and getattr(message.from_user, "is_bot", False):
        try:
            await message.edit_text(text, reply_markup=reply_markup)
            if state is not None:
                await state.update_data(
                    last_bot_message={"chat_id": message.chat.id, "message_id": message.message_id}
                )
            return
        except Exception:
            pass

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
                pass

    sent = await message.answer(text, reply_markup=reply_markup)
    if state is not None:
        try:
            await state.update_data(
                last_bot_message={"chat_id": sent.chat.id, "message_id": sent.message_id}
            )
        except Exception:
            pass
