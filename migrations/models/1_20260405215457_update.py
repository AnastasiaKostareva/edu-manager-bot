from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "lessons" ADD "lesson_link" TEXT;
        ALTER TABLE "lessons" ADD "repeat_type" VARCHAR(50);
        ALTER TABLE "lessons" ALTER COLUMN "scheduled_end" DROP NOT NULL;
        ALTER TABLE "lessons" ALTER COLUMN "actual_end" DROP NOT NULL;
        ALTER TABLE "lessons" ALTER COLUMN "actual_start" DROP NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "lessons" DROP COLUMN "lesson_link";
        ALTER TABLE "lessons" DROP COLUMN "repeat_type";
        ALTER TABLE "lessons" ALTER COLUMN "scheduled_end" SET NOT NULL;
        ALTER TABLE "lessons" ALTER COLUMN "actual_end" SET NOT NULL;
        ALTER TABLE "lessons" ALTER COLUMN "actual_start" SET NOT NULL;"""


MODELS_STATE = (
    "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"
    "A4q41puDTNl4UpsNXWAHp8Xo6O6Xl8f/AY4bIjc="
)
