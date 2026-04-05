from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "chats" (
    "chat_id" BIGSERIAL NOT NULL PRIMARY KEY,
    "chat_title" VARCHAR(255) NOT NULL,
    "chat_type" VARCHAR(255) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "is_active" BOOL NOT NULL DEFAULT True
);
COMMENT ON TABLE "chats" IS 'Таблица chats';
CREATE TABLE IF NOT EXISTS "notification_profiles" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "title" VARCHAR(255) NOT NULL,
    "reminder_intervals" INT[] NOT NULL,
    "max_reminders_per_day" INT NOT NULL DEFAULT 5,
    "is_active" BOOL NOT NULL DEFAULT True
);
COMMENT ON TABLE "notification_profiles" IS 'Таблица notification_profiles';
CREATE TABLE IF NOT EXISTS "users" (
    "telegram_id" BIGSERIAL NOT NULL PRIMARY KEY,
    "username" VARCHAR(255) NOT NULL,
    "full_name" VARCHAR(255),
    "phone" VARCHAR(20),
    "role" VARCHAR(255) NOT NULL,
    "is_active" BOOL NOT NULL DEFAULT True
);
COMMENT ON TABLE "users" IS 'Таблица users';
CREATE TABLE IF NOT EXISTS "chat_members" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "joined_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "is_active" BOOL NOT NULL DEFAULT True,
    "chat_id" BIGINT NOT NULL REFERENCES "chats" ("chat_id") ON DELETE CASCADE,
    "profile_id" INT NOT NULL REFERENCES "notification_profiles" ("id") ON DELETE CASCADE,
    "user_id" BIGINT NOT NULL REFERENCES "users" ("telegram_id") ON DELETE CASCADE,
    CONSTRAINT "uid_chat_member_chat_id_0a2a2a" UNIQUE ("chat_id", "user_id")
);
COMMENT ON TABLE "chat_members" IS 'Таблица chat_members';
CREATE TABLE IF NOT EXISTS "lessons" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "scheduled_at" TIMESTAMPTZ NOT NULL,
    "actual_start" TIMESTAMPTZ NOT NULL,
    "scheduled_end" TIMESTAMPTZ NOT NULL,
    "actual_end" TIMESTAMPTZ NOT NULL,
    "duration_minutes" INT,
    "status" VARCHAR(50) NOT NULL DEFAULT 'scheduled',
    "topic" TEXT,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "chat_id" BIGINT NOT NULL REFERENCES "chats" ("chat_id") ON DELETE NO ACTION,
    "created_by" BIGINT NOT NULL REFERENCES "users" ("telegram_id") ON DELETE NO ACTION
);
COMMENT ON COLUMN "lessons"."status" IS 'scheduled, confirmed, in_progress, completed, cancelled, no_show';
COMMENT ON TABLE "lessons" IS 'Таблица lessons';
CREATE TABLE IF NOT EXISTS "reminders" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "reminder_type" VARCHAR(50) NOT NULL,
    "custom_text" TEXT,
    "remind_at" TIMESTAMPTZ NOT NULL,
    "is_sent" BOOL NOT NULL DEFAULT False,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lesson_id" INT REFERENCES "lessons" ("id") ON DELETE CASCADE,
    "user_id" BIGINT NOT NULL REFERENCES "users" ("telegram_id") ON DELETE CASCADE
);
COMMENT ON TABLE "reminders" IS 'Таблица reminders';
CREATE TABLE IF NOT EXISTS "saved_queries" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "title" VARCHAR(255) NOT NULL,
    "description" TEXT,
    "query_text" TEXT NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "is_public" BOOL NOT NULL DEFAULT False,
    "creator_id" BIGINT REFERENCES "users" ("telegram_id") ON DELETE NO ACTION
);
COMMENT ON COLUMN "saved_queries"."is_public" IS 'могут ли другие админы видеть';
COMMENT ON TABLE "saved_queries" IS 'Таблица saved_queries';
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSONB NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "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"
)
