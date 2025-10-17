from types import SimpleNamespace
from app.formatting import display_chat, display_user
from app.logging_setup import logger
import logging

class ChatObj(SimpleNamespace):
    pass

class UserObj(SimpleNamespace):
    pass

def test_raw_update_logger_direct(caplog):
    caplog.set_level(logging.DEBUG, logger="telegram_bot")
    chat = ChatObj(id=555, title="R", type="group", username="rgrp")
    user = UserObj(id=666, first_name="U", last_name="X", username="ux")
    update = SimpleNamespace(update_id=888, effective_chat=chat, effective_user=user)
    raw_repr = repr(update)
    chat_display = display_chat(chat)
    user_display = display_user(user)
    logger.debug(f"RAW_UPDATE id={update.update_id} chat={chat_display} user={user_display} raw={raw_repr}")
    assert any("RAW_UPDATE" in r.message and "id=888" in r.message for r in caplog.records)