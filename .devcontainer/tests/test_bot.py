from telegram.ext import Application
from app.config import TELEGRAM_API_KEY

def test_bot_get_me():
    app = Application.builder().token(TELEGRAM_API_KEY).build()
    me = app.bot.get_me()
    assert me is not None