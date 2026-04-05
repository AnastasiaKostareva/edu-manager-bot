from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


class UserRole(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"
    OWNER = "owner"


class LessonStatus(str, Enum):
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class RepeatType(str, Enum):
    WEEKLY = "weekly"
    EVERY_2_WEEKS = "every_2_weeks"
    MONTHLY = "monthly"
    ONE_TIME = "one_time"


class ReminderType(str, Enum):
    LESSON = "lesson"
    HOMEWORK = "homework"
    CUSTOM = "custom"


class ReminderTarget(str, Enum):
    SELF = "self"
    STUDENT = "student"


@dataclass
class User:
    telegram_id: int
    username: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: UserRole = UserRole.STUDENT
    is_active: bool = True


@dataclass
class Chat:
    chat_id: int
    chat_title: str
    chat_type: str
    created_at: Optional[datetime] = None
    is_active: bool = True


@dataclass
class Lesson:
    id: Optional[int] = None
    chat_id: Optional[int] = None
    created_by: Optional[int] = None
    lesson_link: Optional[str] = None
    repeat_type: Optional[RepeatType] = None
    scheduled_at: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    status: LessonStatus = LessonStatus.SCHEDULED
    topic: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Reminder:
    id: Optional[int] = None
    user_id: Optional[int] = None
    lesson_id: Optional[int] = None
    reminder_type: ReminderType = ReminderType.LESSON
    custom_text: Optional[str] = None
    remind_at: Optional[datetime] = None
    is_sent: bool = False
    created_at: Optional[datetime] = None


@dataclass
class ReminderTime:
    minutes: int

    @classmethod
    def from_string(cls, value: str) -> "ReminderTime":
        mapping = {
            "5m": 5, "10m": 10, "15m": 15, "30m": 30,
            "1h": 60, "2h": 120, "4h": 240, "8h": 480,
            "12h": 720, "1d": 1440
        }
        return cls(mapping.get(value, 0))

    @classmethod
    def from_custom_format(cls, value: str) -> "ReminderTime":
        parts = value.split(":")
        days = int(parts[0]) if len(parts) > 0 else 0
        hours = int(parts[1]) if len(parts) > 1 else 0
        minutes = int(parts[2]) if len(parts) > 2 else 0
        return cls(days * 1440 + hours * 60 + minutes)