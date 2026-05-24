-- upgrade --
ALTER TABLE "lessons" ADD COLUMN IF NOT EXISTS "start_notification_level" INT NOT NULL DEFAULT 0;
-- downgrade --
ALTER TABLE "lessons" DROP COLUMN IF EXISTS "start_notification_level";
