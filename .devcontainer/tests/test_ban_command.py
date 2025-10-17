import logging
import pytest
from types import SimpleNamespace

from app.database import get_user_state_repo, configured_groups_cache, spammers_cache

class DummyBot:
    async def send_message(self, chat_id, text):
        pass
    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status="administrator")
    def __init__(self):
        self.ban_calls = []
    async def ban_chat_member(self, group_id, user_id):
        # Simulate success
        self.ban_calls.append((group_id, user_id))

class DummyMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []
    async def reply_text(self, txt):
        self.replies.append(txt)

@pytest.mark.asyncio
async def test_ban_command_marks_spammer(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    admin_id = 555001
    target_user = 777001
    target_group = 888001
    monkeypatch.setenv('ADMIN_TELEGRAM_ID', str(admin_id))
    from app import config as cfg
    monkeypatch.setattr(cfg, 'ADMIN_TELEGRAM_ID', str(admin_id))
    # Import command after overriding ADMIN_TELEGRAM_ID
    import app.telegram_commands as tgcmds
    monkeypatch.setattr(tgcmds, 'ADMIN_TELEGRAM_ID', str(admin_id))
    from app.telegram_commands import ban_command
    configured_groups_cache.append({"group_id": target_group, "settings": {}})
    admin = SimpleNamespace(id=admin_id)
    chat = SimpleNamespace(id=9000, type='private')
    msg = DummyMessage(f"/ban {target_user}@{target_group}")
    update = SimpleNamespace(message=msg, effective_chat=chat, effective_user=admin, update_id=93001)
    bot = DummyBot()
    context = SimpleNamespace(bot=bot)
    repo = get_user_state_repo()
    assert target_user not in spammers_cache
    await ban_command(update, context)  # type: ignore
    assert any('помечен как спамер' in r for r in msg.replies), 'No confirmation reply'
    assert target_user in spammers_cache, 'User not added to spammers cache'
    # Structured log admin_force_ban should be present
    assert any('admin_force_ban' in r.message for r in caplog.records), 'Missing admin_force_ban structured log'
    # Ban should have been attempted
    assert (target_group, target_user) in bot.ban_calls, 'ban_chat_member not called'
