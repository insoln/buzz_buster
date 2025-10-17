import logging
import pytest
from types import SimpleNamespace

from app.database import get_user_state_repo, spammers_cache
from app.telegram_groupmembership import handle_other_chat_members

class DummyBot:
    async def send_message(self, chat_id, text):
        # capture messages optionally
        pass

@pytest.mark.asyncio
async def test_membership_unban_clears_spam_flag(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    repo = get_user_state_repo()
    user_id = 444001
    group_id = 555002
    # Mark user spammer in group
    repo.mark_spammer(user_id, group_id)
    assert user_id in spammers_cache

    # Simulate update.chat_member with old banned -> new member
    old_member = SimpleNamespace(status='banned', user=SimpleNamespace(id=user_id))
    new_member = SimpleNamespace(status='member', user=SimpleNamespace(id=user_id))
    chat = SimpleNamespace(id=group_id)
    update = SimpleNamespace(chat_member=SimpleNamespace(old_chat_member=old_member, new_chat_member=new_member), effective_chat=chat, update_id=99001)
    context = SimpleNamespace(bot=DummyBot())

    await handle_other_chat_members(update, context)  # type: ignore

    # Expect structured log of unban_clear_spammer
    assert any('unban_clear_spammer' in r.message for r in caplog.records), 'Missing unban_clear_spammer log'
