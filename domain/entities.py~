from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"

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