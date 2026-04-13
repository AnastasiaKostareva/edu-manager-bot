"""
Тесты для AnalyticsService - безопасное выполнение SQL-запросов.
"""
import pytest
from unittest.mock import AsyncMock, patch

from application.use_cases.analytics import AnalyticsService
from domain.entities import User, UserRole
from domain.exceptions import PermissionDeniedException, ValidationException


class TestAnalyticsService:
    """Тесты для аналитического сервиса."""

    @pytest.fixture
    def analytics_service(self):
        """Fixture для AnalyticsService."""
        return AnalyticsService()

    def test_only_owner_can_execute_queries(
        self,
        analytics_service,
        teacher_user,
        student_user
    ):
        """Только OWNER может выполнять SQL-запросы."""
        query = "SELECT * FROM users LIMIT 10"

        with pytest.raises(PermissionDeniedException):
            # Используем async context manager для тестирования
            import asyncio
            asyncio.run(analytics_service.execute_query(teacher_user, query))

        with pytest.raises(PermissionDeniedException):
            import asyncio
            asyncio.run(analytics_service.execute_query(student_user, query))

    def test_forbidden_keywords_rejected(self, analytics_service, owner_user):
        """Запрещенные SQL-операции отклоняются."""
        forbidden_queries = [
            "DROP TABLE users",
            "DELETE FROM lessons",
            "UPDATE users SET role = 'admin'",
            "INSERT INTO users VALUES (1, 'hacker')",
            "TRUNCATE TABLE chats",
            "ALTER TABLE users ADD COLUMN evil TEXT",
            "GRANT ALL ON users TO hacker",
        ]

        for query in forbidden_queries:
            with pytest.raises(ValidationException) as exc_info:
                import asyncio
                asyncio.run(analytics_service.execute_query(owner_user, query))

            error_message = str(exc_info.value).upper()
            # Проверяем, что ошибка связана с запрещенной операцией
            assert any(keyword in error_message for keyword in [
                "DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER", "GRANT"
            ])

    def test_only_select_allowed(self, analytics_service, owner_user):
        """Разрешены только SELECT запросы (или CTE с WITH)."""
        invalid_queries = [
            "CREATE TABLE test (id INT)",
            "EXEC sp_configure",
            "CALL some_procedure()",
        ]

        for query in invalid_queries:
            with pytest.raises(ValidationException) as exc_info:
                import asyncio
                asyncio.run(analytics_service.execute_query(owner_user, query))

            assert "SELECT" in str(exc_info.value) or "разрешены" in str(exc_info.value).lower()

    def test_empty_query_rejected(self, analytics_service, owner_user):
        """Пустой запрос отклоняется."""
        with pytest.raises(ValidationException) as exc_info:
            import asyncio
            asyncio.run(analytics_service.execute_query(owner_user, ""))

        assert "пуст" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower()

    def test_should_export_to_csv_logic(self, analytics_service):
        """Логика определения необходимости экспорта в CSV."""
        from application.use_cases.analytics import QueryResult

        # Меньше 15 строк - не нужен CSV
        small_result = QueryResult(
            rows=[{"id": i} for i in range(10)],
            row_count=10,
            execution_time_ms=100.0,
            columns=["id"]
        )
        assert not analytics_service.should_export_to_csv(small_result)

        # Больше 15 строк - нужен CSV
        large_result = QueryResult(
            rows=[{"id": i} for i in range(20)],
            row_count=20,
            execution_time_ms=150.0,
            columns=["id"]
        )
        assert analytics_service.should_export_to_csv(large_result)

        # Ровно 15 строк - не нужен CSV (граничный случай)
        exact_result = QueryResult(
            rows=[{"id": i} for i in range(15)],
            row_count=15,
            execution_time_ms=120.0,
            columns=["id"]
        )
        assert not analytics_service.should_export_to_csv(exact_result)

    def test_format_result_as_text(self, analytics_service):
        """Форматирование результата в текст."""
        from application.use_cases.analytics import QueryResult

        result = QueryResult(
            rows=[
                {"id": 1, "username": "user1"},
                {"id": 2, "username": "user2"},
            ],
            row_count=2,
            execution_time_ms=50.5,
            columns=["id", "username"]
        )

        text = analytics_service.format_result_as_text(result, max_rows=10)

        assert "50.5" in text  # Время выполнения
        assert "2" in text     # Количество строк
        assert "user1" in text
        assert "user2" in text

    def test_format_empty_result(self, analytics_service):
        """Форматирование пустого результата."""
        from application.use_cases.analytics import QueryResult

        empty_result = QueryResult(
            rows=[],
            row_count=0,
            execution_time_ms=10.0,
            columns=[]
        )

        text = analytics_service.format_result_as_text(empty_result)

        assert "0" in text  # Строк найдено: 0
        assert "10" in text or "10.0" in text  # Время выполнения

    def test_export_to_csv_creates_valid_file(self, analytics_service):
        """Экспорт в CSV создает валидный файл."""
        from application.use_cases.analytics import QueryResult

        result = QueryResult(
            rows=[
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ],
            row_count=2,
            execution_time_ms=100.0,
            columns=["id", "name"]
        )

        csv_file = analytics_service.export_to_csv(result)

        # Читаем содержимое
        content = csv_file.read().decode('utf-8')

        assert "id,name" in content  # Заголовки
        assert "Alice" in content
        assert "Bob" in content
        assert csv_file.name.endswith(".csv")
