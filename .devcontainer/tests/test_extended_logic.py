import pytest
from types import SimpleNamespace
from typing import Any, cast

from app.telegram_messages import handle_message
from app.telegram_groupmembership import handle_other_chat_members
import app.telegram_groupmembership as membership
from app.database import configured_groups_cache, suspicious_users_cache, spammers_cache, get_user_state_repo
import app.antispam as antispam

@pytest.fixture
def extended_setup(monkeypatch):
    # Перенастраиваем CAS только для этого набора (777 => True)
    async def fake_cas(uid):
        return uid == 777
    monkeypatch.setattr(antispam, "check_cas_ban", fake_cas)
    monkeypatch.setattr(membership, "check_cas_ban", fake_cas)
    repo = get_user_state_repo()
    monkeypatch.setattr(repo, "is_seen", lambda uid: False)
    return repo

class DummyBot:
    def __init__(self):
        self.banned = []
    async def ban_chat_member(self, chat_id, user_id):
        self.banned.append((chat_id, user_id))
    async def get_chat_member(self, chat_id, user_id):  # for membership handler
        return SimpleNamespace(status="administrator")
    async def send_message(self, chat_id, text):
        pass

class DummyMessage:
    def __init__(self, text=None, caption=None, forwarded=False):
        self.text = text
        self.caption = caption
        self.deleted = False
        self.forward_origin = SimpleNamespace() if forwarded else None
    async def delete(self):
        self.deleted = True
    async def reply_text(self, txt):
        pass

class DummyUpdate(SimpleNamespace):
    pass

class DummyContext(SimpleNamespace):
    pass

@pytest.mark.asyncio
async def test_forwarded_message_auto_spam(extended_setup):
    bot = DummyBot()
    user = SimpleNamespace(id=11, first_name="X", last_name="", username=None)
    chat = SimpleNamespace(id=100, type="group", title="T", username=None)
    msg = DummyMessage(text="hello", forwarded=True)
    upd = DummyUpdate(message=msg, effective_chat=chat, effective_user=user, update_id=1)
    ctx = DummyContext(bot=bot)

    await handle_message(cast(Any, upd), cast(Any, ctx))
    # forwarded => spam => banned
    assert (100, 11) in bot.banned
    assert user.id in spammers_cache
    assert msg.deleted

@pytest.mark.asyncio
async def test_cas_join_ban(extended_setup):
    bot = DummyBot()
    user = SimpleNamespace(id=777, first_name="CAS", last_name="", username=None)
    chat = SimpleNamespace(id=100, type="group", title="T", username=None)
    new_member = SimpleNamespace(user=user, status="member")
    upd = DummyUpdate(chat_member=SimpleNamespace(new_chat_member=new_member, old_chat_member=None), effective_chat=chat, update_id=2)
    ctx = DummyContext(bot=bot)

    await handle_other_chat_members(cast(Any, upd), cast(Any, ctx))
    assert (100, 777) in bot.banned
    assert user.id in spammers_cache

@pytest.mark.asyncio
async def test_unban_flow_clears_flag(extended_setup):
    # User initially flagged as spammer in group 100
    spammers_cache.add(500)
    bot = DummyBot()
    chat = SimpleNamespace(id=100, type="group", title="T", username=None)
    user = SimpleNamespace(id=500, first_name="Bad", last_name="", username=None)
    # Simulate old banned -> new member (unban)
    old_member = SimpleNamespace(user=user, status="kicked")
    new_member = SimpleNamespace(user=user, status="member")
    upd = DummyUpdate(chat_member=SimpleNamespace(new_chat_member=new_member, old_chat_member=old_member), effective_chat=chat, update_id=3)
    ctx = DummyContext(bot=bot)

    await handle_other_chat_members(cast(Any, upd), cast(Any, ctx))
    # After clear if no other groups flagged user should be removed from global cache
    # (test setup only one group)
    assert user.id not in spammers_cache

@pytest.mark.asyncio
async def test_late_suspicious_path(extended_setup):
    # Simulate existing unseen entry (cache lost scenario)
    bot = DummyBot()
    user = SimpleNamespace(id=901, first_name="Late", last_name="", username=None)
    chat = SimpleNamespace(id=100, type="group", title="T", username=None)
    # Put user into suspicious manually
    suspicious_users_cache.add(901)
    msg = DummyMessage(text="normal text")
    upd = DummyUpdate(message=msg, effective_chat=chat, effective_user=user, update_id=4)
    ctx = DummyContext(bot=bot)

    await handle_message(cast(Any, upd), cast(Any, ctx))
    # Should become seen if not spam
    assert 901 not in suspicious_users_cache
    assert 901 not in spammers_cache

