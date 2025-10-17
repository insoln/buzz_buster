import pytest
from types import SimpleNamespace
from typing import Any, cast

from app.telegram_groupmembership import handle_other_chat_members
from app.database import spammers_cache, configured_groups_cache, get_user_state_repo

class DummyBot:
    def __init__(self):
        self.banned = []
        self.messages = []
    async def ban_chat_member(self, chat_id, user_id):
        self.banned.append((chat_id, user_id))
    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))

class DummyUpdate(SimpleNamespace):
    pass

class DummyContext(SimpleNamespace):
    pass

@pytest.mark.asyncio
async def test_global_flag_cleared_only_after_last_unban(monkeypatch):
    # Setup two groups configured
    configured_groups_cache.clear()
    spammers_cache.clear()
    configured_groups_cache.append({"group_id": 100, "settings": {"instructions": "t"}})
    configured_groups_cache.append({"group_id": 200, "settings": {"instructions": "t"}})

    repo = get_user_state_repo()

    # Monkeypatch repo methods to avoid DB usage
    # Maintain per-group spam flags in memory
    spam_flags = {(999,100): True, (999,200): True}
    def fake_entry(uid, gid):
        flag = spam_flags.get((uid,gid))
        if flag is None:
            return None
        return (False, flag)
    repo.entry = lambda uid,gid: fake_entry(uid,gid)  # type: ignore
    repo.clear_spammer = lambda uid,gid: spam_flags.__setitem__((uid,gid), False)  # type: ignore
    repo.groups_with_spam_flag = lambda uid: [g for (u,g),flag in spam_flags.items() if u==uid and flag]  # type: ignore

    spammers_cache.add(999)

    bot = DummyBot()

    # First unban in group 100 (should NOT clear global because still spammer in 200)
    old_member = SimpleNamespace(user=SimpleNamespace(id=999, first_name="Sp", last_name="", username=None), status="kicked")
    new_member = SimpleNamespace(user=old_member.user, status="member")
    upd1 = DummyUpdate(chat_member=SimpleNamespace(new_chat_member=new_member, old_chat_member=old_member), effective_chat=SimpleNamespace(id=100, type="group", title="G1", username=None), update_id=1)
    ctx = DummyContext(bot=bot)
    await handle_other_chat_members(cast(Any, upd1), cast(Any, ctx))
    assert 999 in spammers_cache  # still globally flagged

    # Second unban in group 200 clears last flag
    old_member2 = SimpleNamespace(user=old_member.user, status="kicked")
    new_member2 = SimpleNamespace(user=old_member.user, status="member")
    upd2 = DummyUpdate(chat_member=SimpleNamespace(new_chat_member=new_member2, old_chat_member=old_member2), effective_chat=SimpleNamespace(id=200, type="group", title="G2", username=None), update_id=2)
    await handle_other_chat_members(cast(Any, upd2), cast(Any, ctx))
    assert 999 not in spammers_cache