import pytest
from types import SimpleNamespace
from typing import Any, cast
from app.telegram_messages import handle_message
from app import database

class DummyBot:
    def __init__(self):
        self.banned = []
    async def ban_chat_member(self, chat_id, user_id):
        self.banned.append((chat_id, user_id))

class DummyMessage:
    def __init__(self, text=None, caption=None):
        self.text = text
        self.caption = caption
        self.deleted = False
        # Симулируем forward из канала
        self.forward_origin = SimpleNamespace(type='channel')
        self.is_automatic_forward = True
    async def delete(self):
        self.deleted = True
    async def reply_text(self, txt):
        pass

class DummyUpdate(SimpleNamespace):
    pass

class DummyContext(SimpleNamespace):
    pass

@pytest.mark.asyncio
async def test_skip_channel_autoforward(monkeypatch):
    # User 777000 (служебный) публикует автофорвард из канала -> НЕ баним, не классифицируем как спам
    bot = DummyBot()
    user = SimpleNamespace(id=777000, first_name='Telegram', last_name='', username='Telegram')
    chat = SimpleNamespace(id=999, type='supergroup', title='Discussion', username='discussion_group')
    msg = DummyMessage(text='Автофорвард из канала')
    update = DummyUpdate(message=msg, effective_chat=chat, effective_user=user, update_id=777)
    ctx = DummyContext(bot=bot)

    # Убеждаемся что группа настроена (иначе обработчик сразу выйдет)
    database.configured_groups_cache.append({'group_id': chat.id, 'settings': {'instructions': 'test'}})

    # Репозиторий состояния: пользователь не спамер заранее
    repo = database.get_user_state_repo()
    repo.is_spammer = lambda uid: False  # type: ignore
    repo.is_seen = lambda uid: False  # type: ignore

    await handle_message(cast(Any, update), cast(Any, ctx))

    # Проверяем что пользователь НЕ забанен и не помечен как спамер, но помечен как seen
    assert bot.banned == []
    assert user.id not in database.spammers_cache
    assert user.id in database.seen_users_cache
