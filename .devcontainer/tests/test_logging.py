import json
from types import SimpleNamespace
import pytest
from app.logging_setup import log_event, current_update_id, logger
from app.telegram_messages import handle_message

class DummyBot:
    async def ban_chat_member(self, chat_id, user_id):
        pass
    async def send_message(self, chat_id, text):
        pass
    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status="administrator")

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

@pytest.mark.asyncio
async def test_log_event_injects_display(caplog):
    caplog.set_level("DEBUG")
    user = SimpleNamespace(id=111, first_name="Test", last_name="User", username="tuser")
    chat = SimpleNamespace(id=222, title="Group", type="group", username="group")
    current_update_id.set(999)  # type: ignore[arg-type]
    log_event("unit_test", user=user, chat=chat, extra_field=42)
    # Find JSON log
    record = next((r for r in caplog.records if 'unit_test' in r.message and 'user_display' in r.message), None)
    assert record is not None, "Structured log with user_display not found"
    data = json.loads(record.message)
    assert data["update_id"] == 999
    assert "user_display" in data and "chat_display" in data
    assert data["extra_field"] == 42

@pytest.mark.asyncio
async def test_handle_message_sets_update_id_and_logs(caplog, monkeypatch):
    from app.database import get_user_state_repo, configured_groups_cache
    caplog.set_level("DEBUG")
    # Ensure group configured
    gid = 333
    if not any(g["group_id"] == gid for g in configured_groups_cache):
        configured_groups_cache.append({"group_id": gid, "settings": {"instructions": "instr"}})
    repo = get_user_state_repo()
    # Force not seen/spammer
    monkeypatch.setattr(repo, "is_spammer", lambda uid: False)
    monkeypatch.setattr(repo, "is_seen", lambda uid: False)
    # Dummy update/context
    bot = DummyBot()
    user = SimpleNamespace(id=444, first_name="A", last_name="B", username=None)
    chat = SimpleNamespace(id=gid, type="group", title="G", username=None)
    msg = DummyMessage(text="hello world")
    update = SimpleNamespace(message=msg, effective_chat=chat, effective_user=user, update_id=777)
    context = SimpleNamespace(bot=bot)
    await handle_message(update, context)  # type: ignore
    # Check a structured event log present
    record = next((r for r in caplog.records if 'message_receive' in r.message), None)
    assert record is not None
    data = json.loads(record.message)
    assert data["update_id"] == 777
    assert data["user_id"] == 444
    assert "user_display" in data and "chat_display" in data
