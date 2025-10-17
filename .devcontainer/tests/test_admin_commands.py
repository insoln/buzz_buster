import logging
import pytest
from types import SimpleNamespace

from app.telegram_commands import user_command, unban_command
from app.database import configured_groups_cache, spammers_cache, get_user_state_repo, mark_spammer_in_group

class DummyBot:
    def __init__(self):
        self.messages = []
    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))
    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status="administrator")

class DummyMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []
    async def reply_text(self, txt):
        self.replies.append(txt)

@pytest.mark.asyncio
async def test_user_command_inspection(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    import os
    admin = SimpleNamespace(id=int(os.getenv('ADMIN_TELEGRAM_ID') or 999999))
    chat = SimpleNamespace(id=555, type='private')
    configured_groups_cache.append({"group_id": 1001, "settings": {"instructions": "instr"}})
    configured_groups_cache.append({"group_id": 1002, "settings": {"instructions": "instr"}})
    target_id = 777777
    # Simulate spammer in two groups
    repo = get_user_state_repo()
    repo.mark_spammer(target_id, 1001)
    repo.mark_spammer(target_id, 1002)
    msg = DummyMessage(f"/user {target_id}")
    update = SimpleNamespace(message=msg, effective_chat=chat, effective_user=admin, update_id=91001)
    context = SimpleNamespace(bot=DummyBot())
    # Ensure ADMIN_TELEGRAM_ID matches admin.id
    monkeypatch.setenv('ADMIN_TELEGRAM_ID', str(admin.id))
    from app import config as cfg
    monkeypatch.setattr(cfg, 'ADMIN_TELEGRAM_ID', str(admin.id))
    await user_command(update, context)  # type: ignore
    # Verify reply contains spam groups
    assert any('Spam groups:' in r for r in msg.replies), 'No inspection output found'
    # Structured log not essential -> no specific pattern enforced, just ensure debug log line present
    assert any('inspected user' in r.message for r in caplog.records if r.levelno == logging.DEBUG)

@pytest.mark.asyncio
async def test_unban_command_global(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    import os
    admin = SimpleNamespace(id=int(os.getenv('ADMIN_TELEGRAM_ID') or 999998))
    chat = SimpleNamespace(id=556, type='private')
    target_id = 888888
    # Simulate spammer in two groups via repo mark_spammer
    repo = get_user_state_repo()
    repo.mark_spammer(target_id, 2001)
    repo.mark_spammer(target_id, 2002)
    assert target_id in spammers_cache
    msg = DummyMessage(f"/unban {target_id}")
    update = SimpleNamespace(message=msg, effective_chat=chat, effective_user=admin, update_id=91002)
    context = SimpleNamespace(bot=DummyBot())
    monkeypatch.setenv('ADMIN_TELEGRAM_ID', str(admin.id))
    from app import config as cfg
    monkeypatch.setattr(cfg, 'ADMIN_TELEGRAM_ID', str(admin.id))
    await unban_command(update, context)  # type: ignore
    # Verify reply text contains cleared groups
    assert any('Очищены флаги спама' in r for r in msg.replies), 'No unban output'
    # Ensure admin_global_unban structured JSON debug log present
    struct = [r for r in caplog.records if 'admin_global_unban' in r.message]
    assert struct, 'Missing admin_global_unban structured log'
    # Ensure user removed from spammers cache
    from app.database import groups_where_spammer
    remaining = groups_where_spammer(target_id)
    assert not remaining, 'Spam flags not fully cleared'
    # Seen flag should be set after global unban in at least one cleared group
    repo2 = get_user_state_repo()
    assert repo2.is_seen(target_id), 'Seen flag not set after global unban'