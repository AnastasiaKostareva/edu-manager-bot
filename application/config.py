import yaml
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BotConfig:
    name: str = "lesson_assistant_bot"
    token: str = ""
    description: str = ""


@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    database: str = "edu_manager"


@dataclass
class SchedulerConfig:
    check_interval_seconds: int = 60
    reminder_before_minutes: int = 5


@dataclass
class AppConfig:
    bot: BotConfig = field(default_factory=BotConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    roles: list[str] = field(default_factory=lambda: ["student", "teacher", "admin", "owner"])
    admins: list[str] = field(default_factory=list)


_config: Optional[AppConfig] = None


def load_config(config_path: str = "appsettings.yaml") -> AppConfig:
    global _config
    if _config is not None:
        return _config

    path = Path(config_path)
    data = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    # Приоритет переменных окружения над appsettings.yaml
    db_data = data.get("database", {})
    bot_data = data.get("bot", {})
    scheduler_data = data.get("scheduler", {})

    # Database settings with ENV priority
    db_host = os.getenv("DB_HOST", db_data.get("host", "localhost"))
    db_port = int(os.getenv("DB_PORT", db_data.get("port", 5432)))
    db_user = os.getenv("DB_USER", db_data.get("user", "postgres"))
    db_password = os.getenv("DB_PASSWORD", db_data.get("password", ""))
    db_name = os.getenv("DB_NAME", db_data.get("database", "edu_manager"))

    # Bot settings with ENV priority
    bot_token = os.getenv("BOT_TOKEN", bot_data.get("token", ""))
    bot_name = os.getenv("BOT_NAME", bot_data.get("name", "lesson_assistant_bot"))

    _config = AppConfig(
        bot=BotConfig(
            token=bot_token,
            name=bot_name,
            description=bot_data.get("description", "")
        ),
        database=DatabaseConfig(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            database=db_name
        ),
        scheduler=SchedulerConfig(**scheduler_data),
        roles=data.get("roles", ["student", "teacher", "admin", "owner"]),
        admins=data.get("admins", [])
    )
    
    # Optional: override admins from ENV
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if admin_id and admin_id not in _config.admins:
        _config.admins.append(admin_id)

    return _config


def get_config() -> AppConfig:
    if _config is None:
        return load_config()
    return _config

