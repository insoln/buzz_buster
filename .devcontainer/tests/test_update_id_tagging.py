import json
import logging
from types import SimpleNamespace
import pytest

from app.logging_setup import logger
from app.telegram_messages import handle_message
from app.telegram_commands import start_command
from app.telegram_groupmembership import handle_other_chat_members
from app.database import configured_groups_cache, spammers_cache


class DummyBot:
    def __init__(self):
        self.banned = []
        self.messages = []
        # Simulate bot id needed in start_command
        self.id = 999000
    async def ban_chat_member(self, chat_id, user_id):
        self.banned.append((chat_id, user_id))
    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))
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
async def test_update_id_tagging_message_flow(caplog):
    caplog.set_level(logging.DEBUG)
    bot = DummyBot()
    user = SimpleNamespace(id=101, first_name="Msg", last_name="Flow", username=None)
    chat = SimpleNamespace(id=202, type="group", title="GroupA", username=None)
    configured_groups_cache.append({"group_id": chat.id, "settings": {"instructions": "instr"}})
    msg = DummyMessage(text="hello")
    update_id = 55501
    update = SimpleNamespace(message=msg, effective_chat=chat, effective_user=user, update_id=update_id)
    context = SimpleNamespace(bot=bot)
    await handle_message(update, context)  # type: ignore
    # All records produced during this flow should have update_id attribute == update_id
    # Filter records containing the update_id in formatted output (console formatter prefixes it)
    related = [r for r in caplog.records if getattr(r, 'update_id', None) == update_id]
    assert related, "No logs captured for message flow"
    assert any('message_receive' in r.message for r in related), "Missing structured message_receive log with update_id"


@pytest.mark.asyncio
async def test_update_id_tagging_command_flow(caplog):
    caplog.set_level(logging.DEBUG)
    bot = DummyBot()
    # Simulate /start command in configured group by admin-like user
    user = SimpleNamespace(id=303, first_name="Cmd", last_name="Flow", username="cmdflow")
    chat = SimpleNamespace(id=404, type="group", title="GroupB", username=None)
    configured_groups_cache.append({"group_id": chat.id, "settings": {"instructions": "instr"}})
    msg = DummyMessage(text="/start")
    update_id = 55502
    update = SimpleNamespace(message=msg, effective_chat=chat, effective_user=user, update_id=update_id)
    context = SimpleNamespace(bot=bot)
    # Patch ADMIN_TELEGRAM_ID to allow start logic to proceed (if needed)
    from app import config as app_config
    app_config.ADMIN_TELEGRAM_ID = str(user.id)
    await start_command(update, context)  # type: ignore
    related = [r for r in caplog.records if getattr(r, 'update_id', None) == update_id]
    assert related, "No logs captured for command flow"
    assert any("/start" in r.message or "Handling /start" in r.message for r in related), "Missing /start handling log"


@pytest.mark.asyncio
async def test_update_id_tagging_membership_unban_flow(caplog):
    caplog.set_level(logging.DEBUG)
    bot = DummyBot()
    chat = SimpleNamespace(id=505, type="group", title="GroupC", username=None)
    configured_groups_cache.append({"group_id": chat.id, "settings": {"instructions": "instr"}})
    user = SimpleNamespace(id=606, first_name="Unban", last_name="Flow", username=None)
    # Mark as spammer globally
    spammers_cache.add(user.id)
    old_member = SimpleNamespace(user=user, status="kicked")
    new_member = SimpleNamespace(user=user, status="member")
    update_id = 55503
    update = SimpleNamespace(chat_member=SimpleNamespace(new_chat_member=new_member, old_chat_member=old_member), effective_chat=chat, update_id=update_id)
    context = SimpleNamespace(bot=bot)
    await handle_other_chat_members(update, context)  # type: ignore
    related = [r for r in caplog.records if getattr(r, 'update_id', None) == update_id]
    assert related, "No logs captured for membership flow"
    assert any('unban_clear_spammer' in r.message for r in related), "Missing unban_clear_spammer structured log"