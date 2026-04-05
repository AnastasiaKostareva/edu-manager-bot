import yaml
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
    if not path.exists():
        _config = AppConfig()
        return _config

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    _config = AppConfig(
        bot=BotConfig(**data.get("bot", {})),
        database=DatabaseConfig(**data.get("database", {})),
        scheduler=SchedulerConfig(**data.get("scheduler", {})),
        roles=data.get("roles", ["student", "teacher", "admin", "owner"]),
        admins=data.get("admins", [])
    )
    return _config


def get_config() -> AppConfig:
    if _config is None:
        return load_config()
    return _config
