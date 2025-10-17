import logging
import pytest
from types import SimpleNamespace

from app.telegram_groupmembership import handle_other_chat_members
from app.database import get_user_state_repo, spammers_cache, configured_groups_cache

class DummyBot:
    async def send_message(self, chat_id, text):
        pass
    async def ban_chat_member(self, chat_id, user_id):
        pass
    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status="administrator")

@pytest.mark.asyncio
async def test_local_unban_marks_seen_and_clears_global(caplog):
    caplog.set_level(logging.DEBUG)
    repo = get_user_state_repo()
    chat = SimpleNamespace(id=7001, type='group', title='G7001')
    other_chat = SimpleNamespace(id=7002, type='group', title='G7002')
    configured_groups_cache.append({"group_id": chat.id, "settings": {}})
    configured_groups_cache.append({"group_id": other_chat.id, "settings": {}})
    user = SimpleNamespace(id=99001, first_name='Loc', last_name='Ban')
    # Mark user spammer in one group only
    repo.mark_spammer(user.id, chat.id)
    assert user.id in spammers_cache
    # Simulate unban event: old status banned -> new member in same chat
    old_member = SimpleNamespace(user=user, status='kicked')
    new_member = SimpleNamespace(user=user, status='member')
    update = SimpleNamespace(chat_member=SimpleNamespace(old_chat_member=old_member, new_chat_member=new_member), effective_chat=chat, update_id=92001)
    context = SimpleNamespace(bot=DummyBot())
    await handle_other_chat_members(update, context)  # type: ignore
    # Ensure unban_clear_spammer structured log
    assert any('unban_clear_spammer' in r.message for r in caplog.records), 'Missing unban_clear_spammer log'
    # Ensure global spammer flag cleared (no other groups)
    assert user.id not in spammers_cache, 'Global spammer flag not cleared'
    # Ensure seen flag now true
    assert repo.is_seen(user.id), 'Seen flag not set after local unban'