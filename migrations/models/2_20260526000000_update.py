from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "chat_members" DROP COLUMN IF EXISTS "profile_id";
        ALTER TABLE "reminders" ALTER COLUMN "user_id" DROP NOT NULL;
        ALTER TABLE "reminders" ADD COLUMN IF NOT EXISTS "creator_id" BIGINT REFERENCES "users" ("telegram_id") ON DELETE SET NULL;
        ALTER TABLE "reminders" ADD COLUMN IF NOT EXISTS "chat_id" BIGINT;
        ALTER TABLE "lessons" ADD COLUMN IF NOT EXISTS "start_notification_level" INT NOT NULL DEFAULT 0;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "lessons" DROP COLUMN IF EXISTS "start_notification_level";
        ALTER TABLE "reminders" DROP COLUMN IF EXISTS "chat_id";
        ALTER TABLE "reminders" DROP COLUMN IF EXISTS "creator_id";
        ALTER TABLE "reminders" ALTER COLUMN "user_id" SET NOT NULL;
        ALTER TABLE "chat_members" ADD COLUMN "profile_id" INT REFERENCES "notification_profiles" ("id") ON DELETE CASCADE;"""


MODELS_STATE = (
    "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"
    "KcsIvLzmXVTOgWbj+7uBRspHeFYLAP/4HFcN/cg=="
)
