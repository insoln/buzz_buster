import pytest
from app import database
import app.antispam as antispam

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
