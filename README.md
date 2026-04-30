# 🎓 edu-manager-bot

**Telegram-бот для управления онлайн-занятиями с автоматизацией напоминаний и аналитикой.**

Полнофункциональная CRM-система внутри Telegram для образовательных проектов с поддержкой:
- 📅 Планирования занятий с повторениями
- ⏰ Автоматических напоминаний
- ✅ Подтверждения длительности и статуса занятий
- 📊 Аналитики и статистики
- 🔍 SQL-консоли для владельца
- 🔐 Безопасной инициализации чатов

---

## 🏗 Архитектура

Проект построен по принципам **DDD (Domain-Driven Design)** и **Clean Architecture**:

```
edu-manager-bot/
├── application/              # Слой приложения
│   ├── config.py            # Конфигурация
│   ├── interfaces/          # Интерфейсы репозиториев (Dependency Inversion)
│   │   └── repositories.py
│   └── use_cases/           # Бизнес-логика (Use Cases)
│       ├── auth.py          # Авторизация и проверка прав
│       ├── chat.py          # Инициализация чатов
│       ├── lesson.py        # Управление занятиями
│       ├── reminder.py      # Напоминания
│       ├── analytics.py     # SQL-запросы (read-only)
│       └── statistics.py    # Статистика и метрики
│
├── domain/                  # Доменный слой (ядро бизнес-логики)
│   ├── entities.py          # Сущности: User, Lesson, Reminder, Chat
│   └── exceptions.py        # Доменные исключения
│
├── infrastructure/          # Инфраструктурный слой
│   ├── database/            # Persistence
│   │   ├── db_config.py     # Настройка Tortoise ORM
│   │   ├── models.py        # ORM модели (PostgreSQL)
│   │   └── repositories.py  # Реализация репозиториев
│   ├── monitoring/          # Фоновые задачи
│   │   ├── scheduler.py     # APScheduler для уведомлений
│   │   └── sentry.py        # Мониторинг ошибок
│   └── telegram/            # Telegram Bot API
│       ├── bot.py           # Инициализация бота
│       ├── handlers.py      # Обработчики команд
│       └── states.py        # FSM состояния
│
├── migrations/              # Aerich миграции БД
├── docs/                    # Документация
│   └── analytics_role_setup.md
├── tests/                   # Тесты (pytest)
└── main.py                  # Точка входа
```

### Принципы архитектуры

1. **Dependency Rule**: Внутренние слои не зависят от внешних
2. **Separation of Concerns**: Бизнес-логика изолирована от инфраструктуры
3. **Testability**: Use Cases легко тестируются без БД и Telegram API
4. **SOLID**: Применение Single Responsibility, Dependency Inversion

---

## 👥 Роли пользователей

| Роль | Описание | Права |
|------|----------|-------|
| **student** | Студент | Просмотр своих занятий, получение напоминаний |
| **teacher** | Преподаватель | Создание/удаление занятий, управление напоминаниями, статистика |
| **admin** | Администратор | Все права teacher + управление пользователями |
| **owner** | Владелец | Полный доступ + SQL-консоль, аудит |

Роль `owner` определяется через список `admins` в `appsettings.yaml`.

---

## 📋 Команды

### Основные команды

| Команда | Роль | Описание |
|---------|------|----------|
| `/start` | Все | Регистрация и приветствие |
| `/init @username` | Teacher+ | Инициализация чата с привязкой студента |
| `/lessons` | Все | Просмотр назначенных занятий |
| `/stats` | Teacher+ | Статистика за 30 дней |

### Управление занятиями

| Команда | Роль | Описание |
|---------|------|----------|
| `/addLesson` | Teacher+ | Создание занятия с повторениями (weekly/monthly/one-time) |
| `/removeLesson` | Teacher+ | Удаление занятия |

### Управление напоминаниями

| Команда | Роль | Описание |
|---------|------|----------|
| `/addReminder` | Teacher+ | Создание напоминания (для себя или студента) |
| `/removeReminder` | Teacher+ | Удаление напоминания |

### Аналитика (только Owner)

| Команда | Роль | Описание |
|---------|------|----------|
| `/sql` | Owner | SQL-консоль для выполнения SELECT-запросов |

---

## ⚡️ Основные фичи

### 1. Инициализация чата (`/init`)
**Проблема:** Ученики могли случайно выбрать роль "преподаватель"
**Решение:** Жесткая привязка ролей через команду `/init @student_username`

- ✅ Только преподаватель может инициализировать чат
- ✅ Автоматическая проверка username в БД
- ✅ Защита от повторной инициализации
- ✅ Fallback: если username скрыт, студент пишет любое сообщение

### 2. Автоматическое подтверждение занятий
**Проблема:** Преподаватели забывают нажимать кнопку остановки таймера
**Решение:** Планировщик отправляет запрос на подтверждение после окончания

- ⏰ Триггер срабатывает по `scheduled_end_time`
- ⏱ Кнопки: "45 мин", "60 мин", "90 мин", "Свой вариант"
- ⚠️ Таймаут 24 часа → статус `OVERDUE` + алерт админам
- 📊 Фиксация `duration_minutes` и `actual_end` для биллинга

### 3. Безопасная SQL-консоль (`/sql`)
**Проблема:** Владельцу нужны кастомные выгрузки, но разработчик занят
**Решение:** Прямой интерфейс для SELECT-запросов с защитой

- 🔒 Доступ только для `UserRole.OWNER`
- 🛡 Многоуровневая защита:
  - Проверка роли на уровне приложения
  - Валидация запрещенных ключевых слов (`DROP`, `DELETE`, etc.)
  - `SET TRANSACTION READ ONLY` для каждой транзакции
  - `statement_timeout = 10s`
- 📎 Автоматический экспорт в CSV если > 15 строк
- 📖 [Документация по настройке analytics_role](docs/analytics_role_setup.md)

### 4. Статистика (`/stats`)
**Проблема:** Владельцу нужна быстрая оценка эффективности
**Решение:** Агрегирующие SQL-запросы с GROUP BY

Показывает за 30 дней:
- 📚 Количество занятий по статусам (completed/cancelled/overdue)
- ⏱ Общее время и среднюю длительность
- 🏆 Топ-5 преподавателей по количеству занятий
- 👥 Количество активных студентов
- ⚠️ No-show rate (процент пропущенных занятий)

### 5. Планировщик (Scheduler)
Автономное выполнение фоновых задач:
- ✉️ Отправка напоминаний за N минут до занятия
- ✅ Запрос на подтверждение длительности после окончания
- ⏰ Проверка просроченных занятий (>24 часов без ответа)
- 📢 Алерты о неактивных чатах (>7 дней без уроков)

---

## 🚀 Быстрый старт (Local Development)

### Требования

- Python 3.10+
- PostgreSQL 14+
- Telegram Bot Token (получить у [@BotFather](https://t.me/BotFather))

### Установка за 5 минут

1. **Клонировать репозиторий**
```bash
git clone https://github.com/yourusername/edu-manager-bot.git
cd edu-manager-bot
```

2. **Создать виртуальное окружение**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# или
venv\Scripts\activate  # Windows
```

3. **Установить зависимости**
```bash
pip install -r requirements.txt
```

4. **Создать БД в PostgreSQL**
```bash
psql -U postgres
CREATE DATABASE edu_manager;
CREATE USER edu_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE edu_manager TO edu_user;
\q
```

5. **Настроить `appsettings.yaml`**
```yaml
bot:
  name: "lesson_assistant_bot"
  token: "YOUR_BOT_TOKEN_FROM_BOTFATHER"
  description: "Бот для управления занятиями"

database:
  host: "localhost" #или db если через докер
  port: 5432
  user: "edu_user"
  password: "your_password"
  database: "edu_manager"

scheduler:
  check_interval_seconds: 60
  reminder_before_minutes: 5

admins:
  - "123456789"  # Ваш telegram_id (узнать у @userinfobot)
```

6. **Инициализировать миграции (первый раз)**
```bash
aerich init -t infrastructure.database.db_config.TORTOISE_ORM
aerich init-db
```

**Или применить существующие миграции:**
```bash
aerich upgrade
```

7. **Запустить бота**
```bash
python main.py
```

Бот готов! Откройте Telegram и напишите `/start`.

---

## 🐳 Деплой (Production)

### Docker Compose (рекомендуется)

1. **Создать `.env` файл**
```env
BOT_TOKEN=your_bot_token_here
DB_PASSWORD=your_secure_password
POSTGRES_PASSWORD=your_secure_password
ADMIN_TELEGRAM_ID=123456789
```

2. **Создать `docker-compose.yml`**
```yaml
version: '3.8'

services:
  db:
    image: postgres:14-alpine
    environment:
      POSTGRES_USER: edu_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: edu_manager
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  bot:
    build: .
    depends_on:
      - db
    environment:
      BOT_TOKEN: ${BOT_TOKEN}
      DB_HOST: db
      DB_PASSWORD: ${DB_PASSWORD}
      ADMIN_TELEGRAM_ID: ${ADMIN_TELEGRAM_ID}
    volumes:
      - ./appsettings.yaml:/app/appsettings.yaml
    restart: unless-stopped

volumes:
  postgres_data:
```

3. **Создать `Dockerfile`**
```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

4. **Запустить**
```bash
docker-compose up -d
```

### Systemd Service (альтернатива)

1. **Создать `/etc/systemd/system/edu-bot.service`**
```ini
[Unit]
Description=Edu Manager Telegram Bot
After=network.target postgresql.service

[Service]
Type=simple
User=bot
WorkingDirectory=/opt/edu-manager-bot
ExecStart=/opt/edu-manager-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

2. **Активировать**
```bash
sudo systemctl daemon-reload
sudo systemctl enable edu-bot
sudo systemctl start edu-bot
sudo systemctl status edu-bot
```

---

## 📊 Мониторинг и логи

### Просмотр логов (Docker)
```bash
docker-compose logs -f bot
```

### Просмотр логов (Systemd)
```bash
journalctl -u edu-bot -f
```

### Интеграция с Sentry (опционально)

Добавьте в `appsettings.yaml`:
```yaml
sentry:
  dsn: "https://your-sentry-dsn@sentry.io/project-id"
  environment: "production"
```

---

## 🧪 Тесты

### Запуск unit-тестов
```bash
pytest tests/ -v
```

### Запуск с coverage
```bash
pytest tests/ --cov=application --cov=domain --cov-report=html
```

Отчет будет доступен в `htmlcov/index.html`.

---

## 🔧 Разработка

### Создание новой миграции
```bash
# После изменения models.py
aerich migrate --name "add_new_field"
aerich upgrade
```

### Откат миграции
```bash
aerich downgrade
```

### Pre-commit hooks (опционально)
```bash
pip install pre-commit
pre-commit install
```

---

## 📚 Дополнительная документация

- [Настройка analytics_role для SQL-консоли](docs/analytics_role_setup.md)
- [Архитектура и принципы проектирования](docs/architecture.md) *(TODO)*
- [API Use Cases](docs/use_cases.md) *(TODO)*

---

## 🛡 Безопасность

### Чеклист перед production

- [ ] Изменить пароли БД (не использовать дефолтные)
- [ ] Настроить `analytics_role` для SQL-консоли ([инструкция](docs/analytics_role_setup.md))
- [ ] Ограничить доступ к PostgreSQL через `pg_hba.conf` (только с IP сервера)
- [ ] Включить SSL для подключения к БД
- [ ] Настроить backup БД (pg_dump в cron)
- [ ] Включить Sentry для мониторинга ошибок
- [ ] Проверить, что `.env` и `appsettings.yaml` в `.gitignore`

---

## 📈 Метрики и KPI

Система автоматически собирает метрики:
- **Completion Rate**: Процент завершенных занятий от запланированных
- **No-show Rate**: Процент пропущенных занятий
- **Average Duration**: Средняя длительность занятия
- **Overdue Rate**: Процент просроченных (не закрытых вовремя) занятий

Доступно через команду `/stats` для teacher+ ролей.

---

## 🤝 Contribution

Pull requests приветствуются! Для крупных изменений создайте Issue для обсуждения.

### Стиль кода
- PEP 8 для Python
- Type hints обязательны
- Docstrings в формате Google Style
- Максимальная длина строки: 100 символов

---

## 📄 Лицензия

MIT License - см. [LICENSE](LICENSE)

---

## 👨‍💻 Автор

Создано для автоматизации управления онлайн-занятиями в образовательных проектах.

**Bus Factor**: 1 → Требуется документация и тесты для снижения зависимости от одного разработчика.
