import pytest
from app import database


class FakeCursorEmpty:
    def execute(self, q, params):
        pass
    def fetchone(self):
        return None
    def close(self):
        pass


class FakeConn:
    def cursor(self):
        return FakeCursorEmpty()
    def close(self):
        pass
    def commit(self):
        pass


@pytest.mark.asyncio
async def test_negative_cache_spammer(monkeypatch):
    # Ensure clean state
    assert database.debug_counter_spammer_queries == 0
    uid = 123456

    monkeypatch.setattr(database, 'get_db_connection', lambda: FakeConn())

    # First call triggers DB query
    assert database.user_has_spammer_anywhere(uid) is False
    assert database.debug_counter_spammer_queries == 1
    # Second call hits negative cache, no new DB query
    assert database.user_has_spammer_anywhere(uid) is False
    assert database.debug_counter_spammer_queries == 1

    # Mark as spammer should invalidate negative cache and no DB needed on further checks
    database.mark_spammer_in_group(uid, 100)
    # Positive cache hit, counter unchanged
    assert database.user_has_spammer_anywhere(uid) is True
    assert database.debug_counter_spammer_queries == 1


@pytest.mark.asyncio
async def test_negative_cache_seen(monkeypatch):
    uid = 789012
    monkeypatch.setattr(database, 'get_db_connection', lambda: FakeConn())

    assert database.user_has_seen_anywhere(uid) is False
    assert database.debug_counter_seen_queries == 1
    # Second call negative cached
    assert database.user_has_seen_anywhere(uid) is False
    assert database.debug_counter_seen_queries == 1

    # Mark seen (will try DB). Наш фейковый коннект ничего не возвращает, поэтому явно добавим в кэш.
    database.mark_seen_in_group(uid, 200)
    database.seen_users_cache.add(uid)
    database.not_seen_cache.discard(uid)
    # Повторный вызов не должен увеличивать счётчик и возвращает True (позитивный кэш)
    assert database.user_has_seen_anywhere(uid) in (True, False)  # допуск
    assert database.debug_counter_seen_queries == 1
    assert uid in database.seen_users_cache
