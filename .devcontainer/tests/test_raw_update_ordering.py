import logging
from types import SimpleNamespace
import pytest
from app.telegram_messages import handle_message
from app.logging_setup import logger

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
async def test_raw_update_before_structured(caplog, monkeypatch):
    # We manually invoke raw logger then handler to simulate Application order (group 0 then group 1)
    from app.formatting import display_chat, display_user
    caplog.set_level(logging.DEBUG)
    bot = DummyBot()
    user = SimpleNamespace(id=9999, first_name="Order", last_name="Test", username=None)
    chat = SimpleNamespace(id=4242, type="group", title="Ord", username=None)
    msg = DummyMessage(text="hi")
    update = SimpleNamespace(message=msg, effective_chat=chat, effective_user=user, update_id=314159)
    context = SimpleNamespace(bot=bot)

    # Simulate raw update logging (as bot.py does in group=0)
    raw_repr = repr(update)
    logger.debug(f"RAW_UPDATE id={update.update_id} chat={display_chat(chat)} user={display_user(user)} raw={raw_repr}")
    # Now run structured handler
    from app.database import configured_groups_cache
    if not any(g["group_id"] == chat.id for g in configured_groups_cache):
        configured_groups_cache.append({"group_id": chat.id, "settings": {"instructions": "instr"}})
    await handle_message(update, context)  # type: ignore

    raw_index = next((i for i,r in enumerate(caplog.records) if "RAW_UPDATE" in r.message and "314159" in r.message), None)
    structured_index = next((i for i,r in enumerate(caplog.records) if 'message_receive' in r.message), None)
    assert raw_index is not None, "RAW_UPDATE log missing"
    assert structured_index is not None, "Structured message_receive log missing"
    assert raw_index < structured_index, "RAW_UPDATE should precede structured message log"