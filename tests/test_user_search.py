"""
Тест-кейсы для функционала поиска пользователей.

Берутся напрямую из задания:
  - Сервис очищает запрос (strip) и делегирует репозиторию; пустой запрос → [].
  - Репозиторий:
      • запрос '@x' → строгое совпадение по username без учёта регистра;
      • остальное → частичное совпадение (case-insensitive) по username и
        полному имени (в реальной схеме это поле full_name).
  - Клавиатура с результатами строит по одной кнопке на пользователя,
    callback_data вида 'search_sel:{telegram_id}', без слова 'None' в подписи.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from tortoise import Tortoise

from application.use_cases.user import UserService
from application.interfaces.repositories import IUserRepository
from domain.entities import User, UserRole
from infrastructure.database.repositories import UserRepository
from infrastructure.telegram.keyboards import build_user_search_results_kb


# ─── Фейк-репозиторий для сервисных тестов ──────────────────────────────────

class FakeUserRepository(IUserRepository):
    def __init__(self, search_result: list[User] | None = None) -> None:
        self.search_result = search_result or []
        self.search_calls: list[str] = []

    async def search_users(self, query: str) -> list[User]:
        self.search_calls.append(query)
        return self.search_result

    async def get_by_telegram_id(self, telegram_id):  # pragma: no cover
        return None

    async def get_by_username(self, username):  # pragma: no cover
        return None

    async def create(self, user):  # pragma: no cover
        return user

    async def update(self, user):  # pragma: no cover
        return user

    async def get_all_students(self):  # pragma: no cover
        return []

    async def get_all_teachers(self):  # pragma: no cover
        return []

    async def get_all_admins(self):  # pragma: no cover
        return []

    async def get_all_active(self):  # pragma: no cover
        return []


# ─── Сервис: очистка запроса и делегирование ────────────────────────────────

class TestUserServiceSearch:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_without_repo_call(self):
        repo = FakeUserRepository()
        service = UserService(repo)

        result = await service.search_users("")

        assert result == []
        assert repo.search_calls == []

    @pytest.mark.asyncio
    async def test_whitespace_only_query_returns_empty_without_repo_call(self):
        repo = FakeUserRepository()
        service = UserService(repo)

        result = await service.search_users("   ")

        assert result == []
        assert repo.search_calls == []

    @pytest.mark.asyncio
    async def test_query_is_stripped_before_repo_call(self):
        repo = FakeUserRepository(search_result=[])
        service = UserService(repo)

        await service.search_users("   ivan  ")

        assert repo.search_calls == ["ivan"]

    @pytest.mark.asyncio
    async def test_returns_what_repo_returned(self):
        users = [
            User(telegram_id=1, username="a", role=UserRole.STUDENT, full_name="A"),
            User(telegram_id=2, username="b", role=UserRole.STUDENT, full_name="B"),
        ]
        repo = FakeUserRepository(search_result=users)
        service = UserService(repo)

        result = await service.search_users("a")

        assert result == users


# ─── Репозиторий: интеграционные тесты на in-memory SQLite ──────────────────

@pytest_asyncio.fixture
async def tortoise_db():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["infrastructure.database.models"]},
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest_asyncio.fixture
async def seeded_users(tortoise_db):
    from infrastructure.database.models import User as UserModel

    rows = [
        dict(telegram_id=1, username="ivan_petrov", full_name="Иван Петров", role="student"),
        dict(telegram_id=2, username="IvanK", full_name="Иван Кузнецов", role="student"),
        dict(telegram_id=3, username="masha", full_name="Мария Иванова", role="student"),
        dict(telegram_id=4, username="bob", full_name="Robert Smith", role="teacher"),
        dict(telegram_id=5, username="alice", full_name=None, role="student"),
    ]
    for r in rows:
        await UserModel.create(**r)
    return rows


class TestUserRepositorySearch:
    @pytest.mark.asyncio
    async def test_at_prefix_matches_username_exact(self, seeded_users):
        repo = UserRepository()

        result = await repo.search_users("@ivan_petrov")

        ids = {u.telegram_id for u in result}
        assert ids == {1}

    @pytest.mark.asyncio
    async def test_at_prefix_is_case_insensitive(self, seeded_users):
        repo = UserRepository()

        result = await repo.search_users("@IVAN_PETROV")

        ids = {u.telegram_id for u in result}
        assert ids == {1}

    @pytest.mark.asyncio
    async def test_at_prefix_requires_strict_match(self, seeded_users):
        repo = UserRepository()

        result = await repo.search_users("@ivan")

        assert result == []

    @pytest.mark.asyncio
    async def test_plain_query_partial_match_on_username(self, seeded_users):
        repo = UserRepository()

        result = await repo.search_users("ivan")

        ids = {u.telegram_id for u in result}
        assert ids == {1, 2}

    @pytest.mark.asyncio
    async def test_plain_query_partial_match_on_full_name(self, seeded_users):
        repo = UserRepository()

        result = await repo.search_users("Кузнецов")

        ids = {u.telegram_id for u in result}
        assert ids == {2}

    @pytest.mark.asyncio
    async def test_plain_query_ascii_case_insensitive(self, seeded_users):
        repo = UserRepository()

        lower = await repo.search_users("ivan")
        upper = await repo.search_users("IVAN")
        mixed = await repo.search_users("Ivan")

        ids = {u.telegram_id for u in lower}
        assert ids == {u.telegram_id for u in upper} == {u.telegram_id for u in mixed} == {1, 2}

    @pytest.mark.asyncio
    async def test_no_match_returns_empty_list(self, seeded_users):
        repo = UserRepository()

        result = await repo.search_users("nonexistent_xyz")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_domain_user_entities(self, seeded_users):
        repo = UserRepository()

        result = await repo.search_users("@alice")

        assert len(result) == 1
        assert isinstance(result[0], User)
        assert result[0].role == UserRole.STUDENT
        assert result[0].full_name is None


# ─── Клавиатура с результатами ──────────────────────────────────────────────

class TestSearchResultsKeyboard:
    def test_one_button_per_user_with_short_callback_prefix(self):
        users = [
            User(telegram_id=10, username="a", role=UserRole.STUDENT, full_name="A"),
            User(telegram_id=20, username="b", role=UserRole.STUDENT, full_name="B"),
        ]

        kb = build_user_search_results_kb(users)

        assert len(kb.inline_keyboard) == 2
        callbacks = [row[0].callback_data for row in kb.inline_keyboard]
        assert callbacks == ["search_sel:10", "search_sel:20"]

    def test_callback_data_fits_telegram_64_byte_limit(self):
        users = [
            User(telegram_id=10**18, username="x" * 32, role=UserRole.STUDENT, full_name="Y" * 64),
        ]

        kb = build_user_search_results_kb(users)

        cb = kb.inline_keyboard[0][0].callback_data
        assert len(cb.encode("utf-8")) <= 64

    def test_button_label_shows_full_name_and_username(self):
        users = [
            User(telegram_id=1, username="ivan_p", role=UserRole.STUDENT, full_name="Иван Петров"),
        ]

        kb = build_user_search_results_kb(users)

        label = kb.inline_keyboard[0][0].text
        assert "Иван Петров" in label
        assert "@ivan_p" in label

    def test_label_does_not_contain_none_when_full_name_missing(self):
        users = [
            User(telegram_id=1, username="alice", role=UserRole.STUDENT, full_name=None),
        ]

        kb = build_user_search_results_kb(users)

        label = kb.inline_keyboard[0][0].text
        assert "None" not in label
        assert "@alice" in label

    def test_label_does_not_contain_none_when_username_missing(self):
        users = [
            User(telegram_id=1, username=None, role=UserRole.STUDENT, full_name="Иван Петров"),
        ]

        kb = build_user_search_results_kb(users)

        label = kb.inline_keyboard[0][0].text
        assert "None" not in label
        assert "Иван Петров" in label

    def test_empty_user_list_produces_empty_keyboard(self):
        kb = build_user_search_results_kb([])

        assert kb.inline_keyboard == []
