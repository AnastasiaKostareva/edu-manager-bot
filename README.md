# edu-manager-bot

Telegram-бот для управления онлайн-занятиями и напоминаниями.

## Архитектура

Проект построен по принципам **DDD (Domain-Driven Design)** и **Clean Architecture**:

```
edu-manager-bot/
├── application/           # Слой приложения
│   ├── config.py         # Конфигурация
│   ├── interfaces/       # Интерфейсы репозиториев
│   └── use_cases/        # Бизнес-логика
├── domain/               # Доменный слой
│   ├── entities.py       # Сущности и value objects
│   └── exceptions.py     # Доменные исключения
├── infrastructure/       # Инфраструктура
│   ├── database/         # ORM модели и репозитории
│   ├── monitoring/       # Scheduler
│   └── telegram/         # Telegram handlers
└── main.py               # Точка входа
```

## Роли пользователей

- **student** — студент
- **teacher** — преподаватель
- **admin** — администратор
- **owner** — владелец (полный доступ)

## Команды

| Команда | Описание |
|---------|----------|
| `/start` | Регистрация и приветствие |
| `/lessons` | Просмотр занятий |
| `/addLesson` | Создание занятия (teacher, admin) |
| `/removeLesson` | Удаление занятия |
| `/addReminder` | Создание напоминания |
| `/removeReminder` | Удаление напоминания |
| `/sql` | SQL-консоль (только owner) |

## Установка

1. Клонировать репозиторий
2. Установить зависимости:
```bash
pip install -r requirements.txt
```

3. Настроить `appsettings.yaml`:
```yaml
bot:
  token: "YOUR_BOT_TOKEN"

database:
  host: "localhost"
  port: 5432
  user: "postgres"
  password: "YOUR_PASSWORD"
  database: "edu_manager"

admins:
  - "8288568755"  # telegram_id владельца
```

`owner` определяется по списку `admins` в `appsettings.yaml`.

4. Запустить миграции:
```bash
aerich migrate
aerich upgrade
```

5. Запустить бота:
```bash
python main.py
```

## Требования

- Python 3.10+
- PostgreSQL 14+
- aiogram 3.x
- tortoise-orm
- PostgreSQL (asyncpg)
