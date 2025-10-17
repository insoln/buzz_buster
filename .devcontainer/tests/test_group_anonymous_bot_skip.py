import pytest
from types import SimpleNamespace
from typing import Any, cast
from app.telegram_messages import handle_message
from app import database

class DummyBot:
    def __init__(self):
        self.banned = []
    async def ban_chat_member(self, chat_id, user_id):
        self.banned.append((chat_id, user_id))

class DummyMessage:
    def __init__(self, text=None):
        self.text = text
        self.caption = None
        self.forward_origin = None
        self.deleted = False
    async def delete(self):
        self.deleted = True
    async def reply_text(self, txt):
        pass

class DummyUpdate(SimpleNamespace):
    pass

class DummyContext(SimpleNamespace):
    pass

@pytest.mark.asyncio
async def test_group_anonymous_bot_skipped(monkeypatch):
    bot = DummyBot()
    user = SimpleNamespace(id=1087968824, first_name='Group', is_bot=True, username='GroupAnonymousBot')
    chat = SimpleNamespace(id=500, type='supergroup', title='TestGroup', username='test_group')
    msg = DummyMessage(text='anon test')
    update = DummyUpdate(message=msg, effective_chat=chat, effective_user=user, update_id=12345)
    ctx = DummyContext(bot=bot)

    database.configured_groups_cache.append({'group_id': chat.id, 'settings': {'instructions': 'instr'}})

    # Monkeypatch repo methods to fail if called for spam classification
    repo = database.get_user_state_repo()
    monkeypatch.setattr(repo, 'is_spammer', lambda uid: False)
    monkeypatch.setattr(repo, 'is_suspicious', lambda uid: False)

    await handle_message(cast(Any, update), cast(Any, ctx))

    assert bot.banned == []
    assert user.id in database.seen_users_cache
    assert user.id not in database.spammers_cache
