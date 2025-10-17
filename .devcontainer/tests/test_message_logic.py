import pytest  # type: ignore
from types import SimpleNamespace
from typing import Any, cast
from app.telegram_messages import handle_message  # type: ignore
from app.telegram_groupmembership import handle_other_chat_members  # type: ignore
from app.database import get_user_state_repo
from app import database  # type: ignore

# Моки для OpenAI и CAS
import app.antispam as antispam  # type: ignore

@pytest.fixture
def ham_env(monkeypatch):
    """Фикстура для сценариев, где хотим, чтобы пользователь считался unseen и not-seen-глобально."""
    # В conftest уже всё сброшено; дополнительно убеждаемся что repo.is_seen всегда False для детерминизма
    repo = get_user_state_repo()
    monkeypatch.setattr(repo, "is_seen", lambda uid: False)
    return repo

class DummyBot:
    def __init__(self):
        self.banned = []
        self.deleted = []
    async def ban_chat_member(self, chat_id, user_id):
        self.banned.append((chat_id, user_id))
    async def send_message(self, chat_id, text):
        pass
    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status="administrator")

class DummyMessage:
    def __init__(self, text=None, caption=None):
        self.text = text
        self.caption = caption
        self.deleted = False
        self.forward_origin = None
    async def delete(self):
        self.deleted = True
    async def reply_text(self, txt):
        pass

class DummyUpdate(SimpleNamespace):
    pass

class DummyContext(SimpleNamespace):
    pass

@pytest.mark.asyncio
async def test_new_user_first_message_ham(ham_env):
    bot = DummyBot()
    user = SimpleNamespace(id=1, first_name="A", last_name="", username=None)
    chat = SimpleNamespace(id=123, type="group", title="Test", username=None)
    msg = DummyMessage(text="hello world")
    update = DummyUpdate(message=msg, effective_chat=chat, effective_user=user, update_id=1)
    ctx = DummyContext(bot=bot)

    # Пользователь не в записях -> попадёт в suspicious, сообщение не SPAM -> seen
    await handle_message(cast(Any, update), cast(Any, ctx))
    assert user.id not in database.suspicious_users_cache
    assert user.id not in database.spammers_cache
    assert bot.banned == []
    assert msg.deleted is False

@pytest.mark.asyncio
async def test_new_user_first_message_spam(ham_env):
    bot = DummyBot()
    user = SimpleNamespace(id=2, first_name="B", last_name="", username=None)
    chat = SimpleNamespace(id=123, type="group", title="Test", username=None)
    msg = DummyMessage(text="buy SPAM now")
    update = DummyUpdate(message=msg, effective_chat=chat, effective_user=user, update_id=2)
    ctx = DummyContext(bot=bot)

    await handle_message(cast(Any, update), cast(Any, ctx))
    assert user.id in database.spammers_cache
    assert (123, 2) in bot.banned
    assert msg.deleted is True

@pytest.mark.asyncio
async def test_known_seen_user_skip_check(monkeypatch):
    # отмечаем как seen в другой группе: имитируем что он уже виделся
    database.configured_groups_cache.append({"group_id": 456, "settings": {"instructions": "test"}})
    database.suspicious_users_cache.discard(3)
    # вручную ставим seen запись добавив в user_entries замену: вместо БД просто поставим функцию monkeypatch если бы она существовала
    # упростим: пометим его как seen в кэше, добавив запись через mark_seen_in_group
    database.mark_seen_in_group = lambda uid, gid: None  # no-op override

    # считаем что user_has_seen_anywhere -> True
    def fake_seen_any(uid):
        return uid == 3
    antispam_user_has_seen_anywhere_backup = database.user_has_seen_anywhere
    database.user_has_seen_anywhere = fake_seen_any

    bot = DummyBot()
    user = SimpleNamespace(id=3, first_name="C", last_name="", username=None)
    chat = SimpleNamespace(id=123, type="group", title="Test", username=None)
    msg = DummyMessage(text="ordinary text")
    update = DummyUpdate(message=msg, effective_chat=chat, effective_user=user, update_id=3)
    ctx = DummyContext(bot=bot)

    await handle_message(cast(Any, update), cast(Any, ctx))
    assert user.id not in database.spammers_cache
    assert bot.banned == []

    database.user_has_seen_anywhere = antispam_user_has_seen_anywhere_backup

@pytest.mark.asyncio
async def test_global_spammer_auto_ban_on_message():
    database.spammers_cache.add(10)
    bot = DummyBot()
    user = SimpleNamespace(id=10, first_name="S", last_name="", username=None)
    chat = SimpleNamespace(id=123, type="group", title="Test", username=None)
    msg = DummyMessage(text="hello")
    update = DummyUpdate(message=msg, effective_chat=chat, effective_user=user, update_id=4)
    ctx = DummyContext(bot=bot)

    await handle_message(cast(Any, update), cast(Any, ctx))
    assert (123, 10) in bot.banned
    assert msg.deleted is True

@pytest.mark.asyncio
async def test_join_known_spammer_banned():
    # эмулируем join: user_has_spammer_anywhere -> True на уровне модуля обработчика
    import app.telegram_groupmembership as tgm
    repo = get_user_state_repo()
    # Monkeypatch repository to consider this user a global spammer
    repo.is_spammer = lambda uid: uid == 50  # type: ignore

    bot = DummyBot()
    user = SimpleNamespace(id=50, first_name="Bad", last_name="", username=None)
    chat = SimpleNamespace(id=123, type="group", title="Test", username=None)
    new_member = SimpleNamespace(user=user, status="member")
    update = DummyUpdate(chat_member=SimpleNamespace(new_chat_member=new_member, old_chat_member=None), effective_chat=chat, update_id=5)
    ctx = DummyContext(bot=bot)

    await tgm.handle_other_chat_members(cast(Any, update), cast(Any, ctx))
    assert (123, 50) in bot.banned

@pytest.mark.asyncio
async def test_join_new_user_mark_suspicious(monkeypatch):
    repo = get_user_state_repo()
    repo.is_spammer = lambda uid: False  # type: ignore
    monkeypatch.setattr(repo, "is_seen", lambda uid: False)
    bot = DummyBot()
    user = SimpleNamespace(id=60, first_name="New", last_name="", username=None)
    chat = SimpleNamespace(id=123, type="group", title="Test", username=None)
    new_member = SimpleNamespace(user=user, status="member")
    update = DummyUpdate(chat_member=SimpleNamespace(new_chat_member=new_member, old_chat_member=None), effective_chat=chat, update_id=6)
    ctx = DummyContext(bot=bot)
    await handle_other_chat_members(cast(Any, update), cast(Any, ctx))
    assert 60 in database.suspicious_users_cache
