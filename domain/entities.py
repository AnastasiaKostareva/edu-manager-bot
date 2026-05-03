from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"
    PARENT = "parent"

class LessonStatus(str, Enum):
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    OVERDUE = "overdue"  # Не закрыт в течение 24 часов после окончания

class RepeatType(str, Enum):
    ONE_TIME = "one_time"
    WEEKLY = "weekly"
    EVERY_2_WEEKS = "every_2_weeks"
    MONTHLY = "monthly"

class ReminderType(str, Enum):
    LESSON = "lesson"
    HOMEWORK = "homework"
    CUSTOM = "custom"

class ReminderTime(str, Enum):
    FIVE_MIN = "5m"
    TEN_MIN = "10m"
    FIFTEEN_MIN = "15m"
    THIRTY_MIN = "30m"
    ONE_HOUR = "1h"
    TWO_HOURS = "2h"
    FOUR_HOURS = "4h"
    EIGHT_HOURS = "8h"
    TWELVE_HOURS = "12h"
    ONE_DAY = "1d"

    @property
    def minutes(self) -> int:
        mapping = {
            ReminderTime.FIVE_MIN: 5,
            ReminderTime.TEN_MIN: 10,
            ReminderTime.FIFTEEN_MIN: 15,
            ReminderTime.THIRTY_MIN: 30,
            ReminderTime.ONE_HOUR: 60,
            ReminderTime.TWO_HOURS: 120,
            ReminderTime.FOUR_HOURS: 240,
            ReminderTime.EIGHT_HOURS: 480,
            ReminderTime.TWELVE_HOURS: 720,
            ReminderTime.ONE_DAY: 1440,
        }
        return mapping[self]

    @classmethod
    def from_string(cls, value: str) -> "ReminderTime | ParsedReminderTime":
        import re
        normalized = (value or "").strip().lower()
        try:
            return cls(normalized)
        except ValueError:
            pass
        m = re.fullmatch(r'(\d+)(m|h|d)', normalized)
        if not m:
            raise ValueError(f"Unknown reminder time: {normalized!r}")
        amount, unit = int(m.group(1)), m.group(2)
        return ParsedReminderTime(minutes=amount * {"m": 1, "h": 60, "d": 1440}[unit])

    @classmethod
    def from_custom_format(cls, value: str) -> "ParsedReminderTime":
        normalized = (value or "").strip().lower()
        parts = [p.strip() for p in normalized.split(":") if p.strip() != ""]
        if len(parts) not in (2, 3):
            raise ValueError("Invalid custom reminder format")
        try:
            numbers = [int(p) for p in parts]
        except ValueError as exc:
            raise ValueError("Invalid custom reminder format") from exc

        if len(numbers) == 2:
            hours, minutes = numbers
            days = 0
        else:
            days, hours, minutes = numbers

        if days < 0 or hours < 0 or minutes < 0:
            raise ValueError("Invalid custom reminder format")

        total_minutes = (days * 24 * 60) + (hours * 60) + minutes
        return ParsedReminderTime(minutes=total_minutes)


@dataclass(frozen=True)
class ParsedReminderTime:
    minutes: int

@dataclass
class User:
    telegram_id: int
    username: str
    role: UserRole
    full_name: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True

    def can_manage_lessons(self) -> bool:
        return self.role in (UserRole.OWNER, UserRole.ADMIN, UserRole.TEACHER)

@dataclass
class NotificationProfile:
    id: int
    title: str
    reminder_intervals: List[int]
    max_reminders_per_day: int = 5
    is_active: bool = True

@dataclass
class Chat:
    chat_id: int
    chat_title: str
    chat_type: str
    created_at: datetime
    is_active: bool = True

@dataclass
class ChatMember:
    id: int
    chat_id: int
    user_id: int
    profile_id: int
    joined_at: datetime
    is_active: bool = True

@dataclass
class Lesson:
    chat_id: int
    created_by: int
    scheduled_at: datetime
    scheduled_end: Optional[datetime] = None
    status: LessonStatus = LessonStatus.SCHEDULED
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    topic: Optional[str] = None
    lesson_link: Optional[str] = None
    repeat_type: Optional[RepeatType] = None
    id: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def mark_completed(self, duration: int, actual_end_time: datetime) -> None:
        self.status = LessonStatus.COMPLETED
        self.duration_minutes = duration
        self.actual_end = actual_end_time
        self.updated_at = datetime.utcnow()

@dataclass
class Reminder:
    id: int
    user_id: int
    lesson_id: Optional[int]
    reminder_type: ReminderType
    remind_at: datetime
    custom_text: Optional[str] = None
    creator_id: Optional[int] = None
    is_sent: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class SavedQuery:
    id: int
    title: str
    query_text: str
    creator_id: Optional[int] = None
    description: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_public: bool = False