# Настройка роли для аналитических запросов

## Обзор

Для безопасного выполнения SQL-запросов владельцем через `/sql` команду рекомендуется настроить отдельную read-only роль в PostgreSQL. Это предотвращает случайное или намеренное изменение данных.

## Зачем нужна отдельная роль?

✅ **Преимущества:**
- Защита от случайных `DROP TABLE`, `DELETE`, `UPDATE` и других опасных операций
- Изоляция аналитических запросов от основной работы приложения
- Возможность использования read-replica для снижения нагрузки на основную БД
- Аудит и мониторинг аналитических запросов отдельно от транзакционных

⚠️ **Без этого:**
- Риск повреждения данных при ошибке в запросе
- Возможность блокировки таблиц тяжелыми запросами
- Нет разделения обязанностей между транзакционной и аналитической нагрузкой

---

## Быстрая установка (для development)

### Вариант 1: Использование текущей роли с `SET TRANSACTION READ ONLY`

**Текущая реализация** в `AnalyticsService` уже использует защиту:

```python
# application/use_cases/analytics.py
await conn.execute_query("SET TRANSACTION READ ONLY;")
```

Это устанавливает read-only режим для каждой транзакции, что предотвращает любые изменения данных.

### Вариант 2: Создание отдельной read-only роли (рекомендуется для production)

#### Шаг 1: Создайте read-only роль

Подключитесь к PostgreSQL как superuser:

```bash
psql -U postgres -d edu_manager
```

Выполните SQL-команды:

```sql
-- Создаем роль для аналитики
CREATE ROLE analytics_role WITH LOGIN PASSWORD 'your_secure_password';

-- Даем права на подключение к БД
GRANT CONNECT ON DATABASE edu_manager TO analytics_role;

-- Даем права на использование схемы public
GRANT USAGE ON SCHEMA public TO analytics_role;

-- Даем права SELECT на все существующие таблицы
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics_role;

-- Даем права SELECT на все будущие таблицы (автоматически)
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO analytics_role;

-- Опционально: доступ к sequences (для просмотра ID)
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO analytics_role;

-- Устанавливаем таймауты для защиты от долгих запросов
ALTER ROLE analytics_role SET statement_timeout = '10s';
ALTER ROLE analytics_role SET lock_timeout = '5s';
```

#### Шаг 2: Проверьте права

```sql
-- Проверяем права на таблицы
SELECT
    table_schema,
    table_name,
    privilege_type
FROM information_schema.table_privileges
WHERE grantee = 'analytics_role'
ORDER BY table_name;
```

#### Шаг 3: Протестируйте роль

```sql
-- Подключитесь под analytics_role
\c edu_manager analytics_role

-- Попробуйте SELECT (должно работать)
SELECT * FROM users LIMIT 5;

-- Попробуйте UPDATE (должно быть отклонено)
UPDATE users SET username = 'test' WHERE telegram_id = 1;
-- ERROR: permission denied for table users

-- Попробуйте DELETE (должно быть отклонено)
DELETE FROM users WHERE telegram_id = 1;
-- ERROR: permission denied for table users
```

---

## Настройка для production с read-replica

### Использование read-replica для аналитики

Если у вас есть PostgreSQL read-replica (реплика для чтения), вы можете направить аналитические запросы туда:

#### Шаг 1: Настройте отдельное подключение

Добавьте в `appsettings.yaml`:

```yaml
database:
  # Основная БД (для транзакций)
  host: "db-primary.example.com"
  port: 5432
  user: "postgres"
  password: "your_password"
  database: "edu_manager"

# Аналитическая БД (read-replica)
analytics_database:
  host: "db-replica.example.com"
  port: 5432
  user: "analytics_role"
  password: "analytics_password"
  database: "edu_manager"
```

#### Шаг 2: Обновите код для использования отдельного подключения

Модифицируйте `AnalyticsService.__init__`:

```python
# В application/use_cases/analytics.py

def __init__(self, connection_name: str = "analytics"):
    self._connection_name = connection_name
```

И зарегистрируйте отдельное подключение в `infrastructure/database/db_config.py`:

```python
await Tortoise.init(
    db_url=f"postgres://{config.database.user}:{config.database.password}@"
           f"{config.database.host}:{config.database.port}/{config.database.database}",
    modules={"models": ["infrastructure.database.models"]},
)

# Дополнительное подключение для аналитики
await Tortoise.init(
    db_url=f"postgres://{config.analytics_database.user}:"
           f"{config.analytics_database.password}@"
           f"{config.analytics_database.host}:{config.analytics_database.port}/"
           f"{config.analytics_database.database}",
    modules={"models": ["infrastructure.database.models"]},
    connection_name="analytics"
)
```

---

## Дополнительные меры безопасности

### 1. Ограничение ресурсов

Установите лимиты на уровне роли:

```sql
-- Максимальное время выполнения запроса
ALTER ROLE analytics_role SET statement_timeout = '10s';

-- Максимальное время ожидания блокировки
ALTER ROLE analytics_role SET lock_timeout = '5s';

-- Ограничение памяти для сортировки
ALTER ROLE analytics_role SET work_mem = '64MB';

-- Ограничение памяти для всей сессии
ALTER ROLE analytics_role SET temp_buffers = '32MB';
```

### 2. Аудит запросов

Включите логирование запросов для analytics_role:

```sql
ALTER ROLE analytics_role SET log_statement = 'all';
ALTER ROLE analytics_role SET log_duration = on;
```

### 3. Ограничение доступа по IP (pg_hba.conf)

В файле `pg_hba.conf`:

```
# Ограничиваем analytics_role доступом только с сервера приложения
host    edu_manager    analytics_role    10.0.0.5/32    md5
```

---

## Мониторинг

### Отслеживание долгих запросов

```sql
-- Посмотреть активные запросы analytics_role
SELECT
    pid,
    usename,
    query_start,
    state,
    query
FROM pg_stat_activity
WHERE usename = 'analytics_role'
    AND state = 'active';
```

### Статистика по запросам

```sql
-- Статистика по таблицам, которые читает analytics_role
SELECT
    schemaname,
    tablename,
    seq_scan,
    seq_tup_read,
    idx_scan,
    idx_tup_fetch
FROM pg_stat_user_tables
ORDER BY seq_tup_read DESC;
```

---

## Примеры использования

### Базовые аналитические запросы

```sql
-- 1. Статистика по урокам
SELECT
    status,
    COUNT(*) as count,
    AVG(duration_minutes) as avg_duration
FROM lessons
GROUP BY status;

-- 2. Топ-10 активных преподавателей
SELECT
    u.username,
    u.full_name,
    COUNT(l.id) as lessons_count,
    SUM(l.duration_minutes) as total_minutes
FROM users u
JOIN lessons l ON u.telegram_id = l.created_by
WHERE u.role = 'teacher'
    AND l.status = 'completed'
GROUP BY u.telegram_id, u.username, u.full_name
ORDER BY lessons_count DESC
LIMIT 10;

-- 3. Выручка за месяц (если есть таблица payments)
SELECT
    DATE_TRUNC('month', created_at) as month,
    COUNT(*) as lessons_count,
    SUM(duration_minutes) as total_minutes,
    SUM(duration_minutes) * 10 as estimated_revenue  -- 10 руб/мин
FROM lessons
WHERE status = 'completed'
    AND created_at >= NOW() - INTERVAL '6 months'
GROUP BY month
ORDER BY month DESC;
```

---

## Troubleshooting

### Проблема: "Permission denied for table"

**Решение:**

```sql
-- Убедитесь, что права выданы на все таблицы
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics_role;

-- Проверьте владельца таблиц
SELECT tablename, tableowner
FROM pg_tables
WHERE schemaname = 'public';
```

### Проблема: "Statement timeout"

**Решение:**

```sql
-- Временно увеличьте таймаут (только для development!)
ALTER ROLE analytics_role SET statement_timeout = '30s';

-- Или оптимизируйте запрос с помощью EXPLAIN
EXPLAIN ANALYZE SELECT ...;
```

### Проблема: "Database connection error"

**Решение:**

```bash
# Проверьте подключение
psql -h localhost -U analytics_role -d edu_manager

# Проверьте pg_hba.conf
sudo cat /etc/postgresql/*/main/pg_hba.conf | grep analytics_role
```

---

## Checklist для production

- [ ] Создана отдельная роль `analytics_role`
- [ ] Установлены права SELECT на все таблицы
- [ ] Настроены таймауты (`statement_timeout`, `lock_timeout`)
- [ ] Включено логирование запросов
- [ ] Настроено ограничение доступа по IP (pg_hba.conf)
- [ ] Протестированы попытки изменения данных (должны быть отклонены)
- [ ] Настроен мониторинг долгих запросов
- [ ] Документированы примеры аналитических запросов для владельца

---

## Ссылки

- [PostgreSQL: GRANT](https://www.postgresql.org/docs/current/sql-grant.html)
- [PostgreSQL: ALTER ROLE](https://www.postgresql.org/docs/current/sql-alterrole.html)
- [PostgreSQL: pg_hba.conf](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html)
