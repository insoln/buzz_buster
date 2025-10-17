import pytest
import types
from bot.app.send_safe import send_message_with_migration
from telegram.error import ChatMigrated

class DummyBot:
    def __init__(self, migrate_map):
        self._migrate_map = migrate_map  # {old_id: new_id}
        self.sent = []
    async def send_message(self, chat_id: int, text: str, **kwargs):
        # First call triggers migration if mapping exists and not yet migrated
        if chat_id in self._migrate_map and not any(s[0] == self._migrate_map[chat_id] for s in self.sent):
            raise ChatMigrated(self._migrate_map[chat_id])
        self.sent.append((chat_id, text))
        return types.SimpleNamespace(message_id=len(self.sent), chat_id=chat_id, text=text)

@pytest.mark.asyncio
async def test_wrapper_handles_chat_migrated():
    bot = DummyBot({123: -100999})
    msg = await send_message_with_migration(bot, 123, text="Hello")
    assert msg is not None
    # Ensure migrated id used
    assert bot.sent[0][0] == -100999
    assert bot.sent[0][1] == "Hello"

@pytest.mark.asyncio
async def test_wrapper_no_migration():
    bot = DummyBot({})
    msg = await send_message_with_migration(bot, 555, text="Ping")
    assert msg is not None
    assert bot.sent[0][0] == 555
