import csv
import io
import logging
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass

from tortoise import connections
from tortoise.exceptions import OperationalError, DBConnectionError

from domain.entities import User, UserRole
from domain.exceptions import PermissionDeniedException, ValidationException

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Результат выполнения SQL-запроса."""
    rows: list[dict[str, Any]]
    row_count: int
    execution_time_ms: float
    columns: list[str]


class AnalyticsService:
    """
    Сервис для выполнения аналитических SQL-запросов с защитой от небезопасных операций.
    """

    # Запрещенные SQL-операции (для дополнительной защиты)
    FORBIDDEN_KEYWORDS = [
        "DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE",
        "ALTER", "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE"
    ]

    # Максимальное количество строк для вывода в сообщение
    MAX_INLINE_ROWS = 15

    # Таймаут выполнения запроса в миллисекундах
    QUERY_TIMEOUT_MS = 10000  # 10 секунд

    def __init__(self):
        self._connection_name = "default"

    async def execute_query(
        self,
        actor: User,
        query: str,
        timeout_ms: Optional[int] = None
    ) -> QueryResult:
        """
        Выполняет SELECT-запрос с защитой от небезопасных операций.

        Args:
            actor: Пользователь, выполняющий запрос (должен быть OWNER)
            query: SQL-запрос
            timeout_ms: Таймаут в миллисекундах (по умолчанию 10000)

        Returns:
            QueryResult с данными результата

        Raises:
            PermissionDeniedException: Если пользователь не OWNER
            ValidationException: Если запрос содержит запрещенные операции
        """
        # Проверка прав доступа
        if actor.role != UserRole.OWNER:
            raise PermissionDeniedException(
                "Только владелец может выполнять SQL-запросы"
            )

        # Очистка и валидация запроса
        clean_query = query.strip()
        if not clean_query:
            raise ValidationException("Пустой запрос")

        # Проверка на запрещенные операции (дополнительная защита)
        upper_query = clean_query.upper()
        for keyword in self.FORBIDDEN_KEYWORDS:
            if keyword in upper_query:
                raise ValidationException(
                    f"⛔️ Запрещенная операция: {keyword}\n"
                    f"Разрешены только SELECT-запросы для чтения данных."
                )

        # Проверка, что запрос начинается с SELECT
        if not upper_query.startswith("SELECT") and not upper_query.startswith("WITH"):
            raise ValidationException(
                "⛔️ Разрешены только SELECT-запросы (или CTE с WITH)"
            )

        timeout = timeout_ms or self.QUERY_TIMEOUT_MS

        try:
            conn = connections.get(self._connection_name)

            # Получаем низкоуровневое подключение для установки таймаута
            db = conn._connection

            start_time = datetime.now()

            # Устанавливаем таймаут и режим read-only для сессии
            await conn.execute_query(f"SET statement_timeout = {timeout};")
            await conn.execute_query("SET TRANSACTION READ ONLY;")

            # Выполняем запрос
            result = await conn.execute_query_dict(clean_query)

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds() * 1000

            # Извлекаем названия колонок
            columns = list(result[0].keys()) if result else []

            query_result = QueryResult(
                rows=result,
                row_count=len(result),
                execution_time_ms=round(execution_time, 2),
                columns=columns,
            )

            logger.info(
                f"Analytics query executed by {actor.telegram_id}: "
                f"{len(result)} rows, {execution_time:.2f}ms"
            )

            return query_result

        except OperationalError as e:
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "statement_timeout" in error_msg.lower():
                raise ValidationException(
                    f"⏱ Превышено время ожидания ({timeout}ms)\n"
                    f"Запрос выполняется слишком долго. "
                    f"Попробуйте упростить запрос или добавить LIMIT."
                )
            elif "permission denied" in error_msg.lower() or "read-only" in error_msg.lower():
                raise ValidationException(
                    f"🔒 Отказано в доступе\n"
                    f"Запрос пытается изменить данные. Разрешены только SELECT-запросы."
                )
            else:
                logger.error(f"Query execution error: {e}")
                raise ValidationException(f"Ошибка БД: {error_msg}")

        except DBConnectionError as e:
            logger.error(f"Database connection error: {e}")
            raise ValidationException("Ошибка подключения к базе данных")

        except Exception as e:
            logger.error(f"Unexpected error during query execution: {e}")
            raise ValidationException(f"Непредвиденная ошибка: {str(e)}")

    def format_result_as_text(self, result: QueryResult, max_rows: int = 10) -> str:
        """
        Форматирует результат запроса в текстовый вид для отправки в Telegram.

        Args:
            result: Результат запроса
            max_rows: Максимальное количество строк для вывода

        Returns:
            Отформатированная строка с результатами
        """
        if result.row_count == 0:
            return (
                "✅ Запрос выполнен успешно\n"
                f"⏱ Время выполнения: {result.execution_time_ms}ms\n"
                f"📊 Строк найдено: 0"
            )

        lines = [
            f"✅ Запрос выполнен успешно",
            f"⏱ Время: {result.execution_time_ms}ms",
            f"📊 Строк: {result.row_count}",
            "",
        ]

        # Показываем первые max_rows строк
        display_count = min(max_rows, result.row_count)

        for i, row in enumerate(result.rows[:display_count], 1):
            lines.append(f"[{i}]")
            for key, value in row.items():
                # Ограничиваем длину значений
                str_value = str(value)
                if len(str_value) > 100:
                    str_value = str_value[:97] + "..."
                lines.append(f"  {key}: {str_value}")
            lines.append("")

        if result.row_count > max_rows:
            lines.append(f"... и еще {result.row_count - max_rows} строк")
            lines.append("📎 Полный результат отправлен в CSV-файле")

        return "\n".join(lines)

    def export_to_csv(self, result: QueryResult) -> io.BytesIO:
        """
        Экспортирует результат в CSV-файл.

        Args:
            result: Результат запроса

        Returns:
            BytesIO объект с CSV-данными
        """
        output = io.StringIO()

        if result.row_count > 0:
            writer = csv.DictWriter(output, fieldnames=result.columns)
            writer.writeheader()
            writer.writerows(result.rows)

        # Преобразуем StringIO в BytesIO для отправки в Telegram
        csv_content = output.getvalue()
        bytes_output = io.BytesIO(csv_content.encode('utf-8'))
        bytes_output.name = f"query_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        bytes_output.seek(0)

        return bytes_output

    def should_export_to_csv(self, result: QueryResult) -> bool:
        """
        Определяет, нужно ли экспортировать результат в CSV.

        Args:
            result: Результат запроса

        Returns:
            True, если строк больше MAX_INLINE_ROWS
        """
        return result.row_count > self.MAX_INLINE_ROWS
