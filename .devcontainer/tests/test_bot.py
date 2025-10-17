from telegram.ext import Application
from app.config import TELEGRAM_API_KEY


def test_application_builds_without_network():
    token = TELEGRAM_API_KEY or "123456:ABC-DEF_fake"
    app = Application.builder().token(token).build()
    # Просто проверяем что bot создан и имеет ожидаемые базовые атрибуты
    assert app.bot is not None
    assert hasattr(app.bot, "token")