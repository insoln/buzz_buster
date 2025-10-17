import logging
from types import SimpleNamespace
import pytest

from app.telegram_messages import handle_message
from app.telegram_groupmembership import handle_other_chat_members
from app.logging_setup import ESSENTIAL_ACTIONS
from app.database import configured_groups_cache, spammers_cache

class DummyBot:
    def __init__(self):
        self.banned = []
    async def ban_chat_member(self, chat_id, user_id):
        self.banned.append((chat_id, user_id))
    async def send_message(self, chat_id, text):
        pass
    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status="administrator")

class DummyMessage:
    def __init__(self, text=None, forwarded=False):
        self.text = text
        self.caption = None
        self.forward_origin = SimpleNamespace() if forwarded else None
        self.deleted = False
    async def delete(self):
        self.deleted = True
    async def reply_text(self, txt):
        pass

@pytest.mark.asyncio
async def test_first_message_spam_info_and_human(caplog):
    caplog.set_level(logging.DEBUG)
    bot = DummyBot()
    user = SimpleNamespace(id=1001, first_name="S", last_name="P", username=None)
    chat = SimpleNamespace(id=2001, type="group", title="G", username=None)
    configured_groups_cache.append({"group_id": chat.id, "settings": {"instructions": "instr"}})
    msg = DummyMessage(text="spam here", forwarded=True)  # forwarded triggers spam classification
    update = SimpleNamespace(message=msg, effective_chat=chat, effective_user=user, update_id=90001)
    context = SimpleNamespace(bot=bot)
    await handle_message(update, context)  # type: ignore
    # Find first_message_spam structured JSON line
    # Accept any of the spam classification structured actions (path variations)
    spam_struct = [
        r for r in caplog.records
        if any(x in r.message for x in ('first_message_spam', 'new_user_spam', 'late_suspicious_spam'))
    ]
    assert spam_struct, "Missing spam structured JSON log"
    info_human = [r for r in caplog.records if r.levelno == logging.INFO and 'SPAM' in r.message]
    assert info_human, "Missing human INFO summary containing SPAM"

@pytest.mark.asyncio
async def test_first_message_ham_info_and_single(caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    bot = DummyBot()
    user = SimpleNamespace(id=1002, first_name="H", last_name="M", username=None)
    chat = SimpleNamespace(id=2002, type="group", title="G2", username=None)
    configured_groups_cache.append({"group_id": chat.id, "settings": {"instructions": "instr"}})
    msg = DummyMessage(text="hello normal")
    update = SimpleNamespace(message=msg, effective_chat=chat, effective_user=user, update_id=90002)
    context = SimpleNamespace(bot=bot)
    # Force suspicious path
    from app.database import get_user_state_repo
    repo = get_user_state_repo()
    monkeypatch.setattr(repo, 'is_spammer', lambda uid: False)
    monkeypatch.setattr(repo, 'is_suspicious', lambda uid: True)
    monkeypatch.setattr(repo, 'mark_spammer', lambda u,g: None)
    monkeypatch.setattr(repo, 'mark_seen', lambda u,g: None)
    monkeypatch.setattr(repo, 'mark_unseen', lambda u,g: None)
    # Avoid OpenAI check by monkeypatch process_spam to return False
    from app import telegram_messages as tm
    async def fake_process(update, ctx, usr, cht):
        return False
    monkeypatch.setattr(tm, 'process_spam', fake_process)
    await handle_message(update, context)  # type: ignore
    ham_struct = [r for r in caplog.records if 'first_message_ham' in r.message]
    assert ham_struct, "Missing first_message_ham structured log"
    human = [r for r in caplog.records if r.levelno == logging.INFO and 'Trusted' in r.message]
    assert human, "Missing human INFO summary for ham"
    # Ensure only one INFO summary
    assert len([r for r in caplog.records if r.levelno == logging.INFO]) <= 3  # structured + summary, maybe other essential

@pytest.mark.asyncio
async def test_unban_clear_spammer_info(caplog):
    caplog.set_level(logging.DEBUG)
    bot = DummyBot()
    chat = SimpleNamespace(id=3003, type="group", title="G3", username=None)
    configured_groups_cache.append({"group_id": chat.id, "settings": {"instructions": "instr"}})
    user = SimpleNamespace(id=4004, first_name="U", last_name="B", username=None)
    spammers_cache.add(user.id)
    old_member = SimpleNamespace(user=user, status="kicked")
    new_member = SimpleNamespace(user=user, status="member")
    update = SimpleNamespace(chat_member=SimpleNamespace(new_chat_member=new_member, old_chat_member=old_member), effective_chat=chat, update_id=90003)
    context = SimpleNamespace(bot=bot)
    await handle_other_chat_members(update, context)  # type: ignore
    unban_struct = [r for r in caplog.records if 'unban_clear_spammer' in r.message]
    assert unban_struct, "Missing unban_clear_spammer structured log"
    human = [r for r in caplog.records if r.levelno == logging.INFO and 'Unban' in r.message]
    assert human, "Missing human INFO summary for unban"