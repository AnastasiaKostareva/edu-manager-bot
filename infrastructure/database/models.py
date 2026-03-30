from tortoise import fields, models
from tortoise.contrib.postgres import fields as pg_fields


class User(models.Model):
    """
    Таблица users
    """
    telegram_id = fields.BigIntField(pk=True, unique=True)
    username = fields.CharField(max_length=255, null=False)
    full_name = fields.CharField(max_length=255, null=True)
    phone = fields.CharField(max_length=20, null=True)
    role = fields.CharField(max_length=255, null=False)
    is_active = fields.BooleanField(default=True)

    class Meta:
        table = "users"
        ordering = ["-telegram_id"]

    def __str__(self):
        return f"User({self.telegram_id}, {self.username})"


class NotificationProfile(models.Model):
    """
    Таблица notification_profiles
    """
    id = fields.IntField(pk=True)
    title = fields.CharField(max_length=255, null=False)
    # INTEGER ARRAY не поддерживается напрямую, используем JSONField
    reminder_intervals = pg_fields.ArrayField(int, null=False) 
    max_reminders_per_day = fields.IntField(default=5, null=False)
    is_active = fields.BooleanField(default=True)

    class Meta:
        table = "notification_profiles"
        ordering = ["id"]

    def __str__(self):
        return f"Profile({self.id}, {self.title})"


class Chat(models.Model):
    """
    Таблица chats
    """
    chat_id = fields.BigIntField(pk=True, unique=True)
    chat_title = fields.CharField(max_length=255, null=False)
    chat_type = fields.CharField(max_length=255, null=False)
    created_at = fields.DatetimeField(auto_now_add=True)
    is_active = fields.BooleanField(default=True)

    class Meta:
        table = "chats"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Chat({self.chat_id}, {self.chat_title})"


class ChatMember(models.Model):
    """
    Таблица chat_members
    Составной PK (chat_id, user_id). 
    """
    id = fields.IntField(pk=True)
    chat = fields.ForeignKeyField(
        "models.Chat", 
        related_name="members", 
        on_delete=fields.CASCADE,
        source_field="chat_id",
        to_field="chat_id"
    )
    user = fields.ForeignKeyField(
        "models.User", 
        related_name="chat_memberships", 
        on_delete=fields.CASCADE,
        source_field="user_id",
        to_field="telegram_id"
    )
    profile = fields.ForeignKeyField(
        "models.NotificationProfile", 
        related_name="chat_memberships",
        source_field="profile_id",
        to_field="id"
    )
    joined_at = fields.DatetimeField(auto_now_add=True)
    is_active = fields.BooleanField(default=True)

    class Meta:
        table = "chat_members"
        unique_together = ("chat_id", "user_id")
        ordering = ["-joined_at"]

    def __str__(self):
        return f"Member({self.chat_id}, {self.user_id})"


class Lesson(models.Model):
    """
    Таблица lessons
    """
    id = fields.IntField(pk=True)
    chat = fields.ForeignKeyField(
        "models.Chat",
        related_name="lessons",
        on_delete=fields.NO_ACTION,
        source_field="chat_id",
        to_field="chat_id"
    )
    created_by = fields.ForeignKeyField(
        "models.User",
        related_name="lessons",
        on_delete=fields.NO_ACTION,
        source_field="created_by",
        to_field="telegram_id"
    )
    scheduled_at = fields.DatetimeField()
    actual_start = fields.DatetimeField()
    scheduled_end = fields.DatetimeField()
    actual_end = fields.DatetimeField()
    duration_minutes = fields.IntField(null=True)
    
    status = fields.CharField(
        max_length=50, 
        default='scheduled',
        description="scheduled, confirmed, in_progress, completed, cancelled, no_show"
    )
    
    topic = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "lessons"
        ordering = ["-scheduled_at"]

    def __str__(self):
        return f"Lesson({self.id}, {self.status})"


class SavedQuery(models.Model):
    """
    Таблица saved_queries
    """
    id = fields.IntField(pk=True)
    creator = fields.ForeignKeyField(
        "models.User",
        related_name="saved_queries",
        on_delete=fields.NO_ACTION,
        source_field="creator_id",
        to_field="telegram_id",
        null=True
    )
    title = fields.CharField(max_length=255, null=False)
    description = fields.TextField(null=True)
    query_text = fields.TextField(null=False)
    created_at = fields.DatetimeField(auto_now_add=True)
    is_public = fields.BooleanField(
        default=False, 
        description="могут ли другие админы видеть"
    )

    class Meta:
        table = "saved_queries"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Query({self.id}, {self.title})"