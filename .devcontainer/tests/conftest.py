import pytest
from app import database
import app.antispam as antispam

# Lightweight async test support fallback (if pytest-asyncio not active)
import asyncio, inspect, logging

def pytest_pyfunc_call(pyfuncitem):  # type: ignore
    """Run async test functions manually if no plugin handles them.
    Filters fixture arguments to only those accepted by the test function signature.
    """
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        sig_params = set(inspect.signature(pyfuncitem.obj).parameters.keys())
        filtered_args = {k: v for k, v in pyfuncitem.funcargs.items() if k in sig_params}
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(pyfuncitem.obj(**filtered_args))
        return True
    return None

@pytest.fixture(autouse=True)
def global_env(monkeypatch):
    """Авто-фикстура: очищает кэши, настраивает дефолтные моки и предоставляет общий baseline.
    Тесты могут поверх переопределять поведение репозитория/antispam.
    """
    # Очистка кэшей
    database.configured_groups_cache.clear()
    database.suspicious_users_cache.clear()
    database.spammers_cache.clear()
    database.seen_users_cache.clear()
    # Новые negative caches и счётчики
    if hasattr(database, 'not_spammers_cache'):
        database.not_spammers_cache.clear()
    if hasattr(database, 'not_seen_cache'):
        database.not_seen_cache.clear()
    if hasattr(database, 'debug_counter_spammer_queries'):
        database.debug_counter_spammer_queries = 0
    if hasattr(database, 'debug_counter_seen_queries'):
        database.debug_counter_seen_queries = 0

    # Общие тестовые группы по умолчанию (минимум 123 и 100 для разных сценариев)
    default_groups = [123, 100]
    for gid in default_groups:
        if not any(g["group_id"] == gid for g in database.configured_groups_cache):
            database.configured_groups_cache.append({"group_id": gid, "settings": {"instructions": "test"}})

    # Базовые моки OpenAI/CAS (мягкие: не делают пользователя спамером, пока тест явно не задаст условия)
    async def default_check_openai_spam(msg, instructions):  # pragma: no cover - простая заглушка
        if not msg:
            return False
        upper = msg.upper()
        return "SPAM" in upper or "FORWARDED" in upper
    monkeypatch.setattr(antispam, "check_openai_spam", default_check_openai_spam)
    # Важно: не переопределяем CAS здесь, чтобы специализированный тест мог подменить ClientSession сам.

    # Репозиторий: по умолчанию глобальный спамер определяется кэшем; seen — просто по seen_users_cache
    repo = database.get_user_state_repo()
    monkeypatch.setattr(repo, "is_spammer", lambda uid: uid in database.spammers_cache)
    monkeypatch.setattr(repo, "is_seen", lambda uid: uid in database.seen_users_cache)

    yield

    # (Опционально можно добавлять post-test проверки консистентности кэшей)
