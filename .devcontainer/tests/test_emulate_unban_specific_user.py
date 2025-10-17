import logging
import pytest
from types import SimpleNamespace

from app.database import get_user_state_repo, spammers_cache
from app.telegram_groupmembership import handle_other_chat_members

TARGET_USER = 6387336677
TARGET_GROUP = -1002256895550

class DummyBot:
    async def send_message(self, chat_id, text):
        pass

@pytest.mark.asyncio
async def test_emulate_unban_specific_user(caplog):
    caplog.set_level(logging.DEBUG)
    repo = get_user_state_repo()

    # 1) Mark user as spammer in the target group (simulate prior ban reason)
    repo.mark_spammer(TARGET_USER, TARGET_GROUP)
    assert TARGET_USER in spammers_cache, 'User should be globally recognized as spammer before unban.'

    # 2) Simulate membership update: old status banned -> new status member
    old_member = SimpleNamespace(status='banned', user=SimpleNamespace(id=TARGET_USER))
    new_member = SimpleNamespace(status='member', user=SimpleNamespace(id=TARGET_USER))
    chat = SimpleNamespace(id=TARGET_GROUP)
    update = SimpleNamespace(chat_member=SimpleNamespace(old_chat_member=old_member, new_chat_member=new_member), effective_chat=chat, update_id=123456789)
    context = SimpleNamespace(bot=DummyBot())

    await handle_other_chat_members(update, context)  # type: ignore

    # 3) Assert unban_clear_spammer logged
    assert any('unban_clear_spammer' in r.message for r in caplog.records), 'Expected unban_clear_spammer log not found.'
