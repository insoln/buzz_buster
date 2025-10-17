import logging
import pytest
from types import SimpleNamespace

from app.telegram_commands import diag_command
from app.database import get_user_state_repo

class DummyBot:
    async def ban_chat_member(self, *a, **kw):
        pass
    async def get_chat_member(self, *a, **kw):
        return SimpleNamespace(status="administrator")

class DummyMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []
    async def reply_text(self, txt):
        self.replies.append(txt)

@pytest.mark.asyncio
async def test_diag_command_output(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    admin_id = 999001
    monkeypatch.setenv('ADMIN_TELEGRAM_ID', str(admin_id))
    from app import config as cfg
    monkeypatch.setattr(cfg, 'ADMIN_TELEGRAM_ID', str(admin_id))
    import app.telegram_commands as tgcmds
    monkeypatch.setattr(tgcmds, 'ADMIN_TELEGRAM_ID', str(admin_id))

    target_user = 111222333
    target_group = -555666777
    msg = DummyMessage(f"/diag {target_user}@{target_group}")
    update = SimpleNamespace(message=msg, effective_chat=SimpleNamespace(id=1, type='private'), effective_user=SimpleNamespace(id=admin_id), update_id=432101)
    context = SimpleNamespace(bot=DummyBot())
    await diag_command(update, context)  # type: ignore
    assert msg.replies, 'No reply from /diag'
    out = "\n".join(msg.replies)
    # Basic fields presence
    for key in ["DB_CONNECT:", "ENTRY:", "IS_SPAMMER_IN_GROUP:", "GROUPS_SPAM:", "GLOBAL_CACHE_SPAM:", "DRY_SELECT:"]:
        assert key in out, f'Missing {key} in diag output'
    # Structured log admin_diag present
    assert any('admin_diag' in r.message for r in caplog.records), 'Missing admin_diag structured log'
