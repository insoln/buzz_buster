# logging_setup.py

import logging
import logging.handlers
from .config import *
import asyncio
from telegram import Bot


class TelegramLogHandler(logging.Handler):
    """Класс для отправки логов в Telegram."""

    def __init__(self, bot_instance, chat_id):
        super().__init__()
        self.bot = bot_instance
        self.chat_id = int(chat_id)

    def emit(self, record):
        log_entry = self.format(record)
        try:
            asyncio.create_task(
                self.bot.send_message(chat_id=self.chat_id, text=log_entry)
            )
        except Exception as e:
            print(f"Failed to send log via Telegram: {e}")


# Настройка логирования
logger = logging.getLogger("telegram_bot")
logger.setLevel(logging.DEBUG)

# Форматтеры для логирования
log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
simple_formatter = logging.Formatter("%(message)s")

# Логирование в файл
file_handler = logging.handlers.RotatingFileHandler(
    "buzzbuster.log", maxBytes=5 * 1024 * 1024, backupCount=2
)
file_handler.setLevel(getattr(logging, FILE_LOG_LEVEL, logging.INFO))
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

# Логирование в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(
    getattr(logging, CONSOLE_LOG_LEVEL, logging.INFO))
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)


def getLoggingLevelByName(level: str) -> int:
    """Получение уровня логирования по имени."""
    return getattr(logging, level.upper(), logging.WARNING)


# Создаем экземпляр бота для отправки уведомлений
bot = Bot(token=TELEGRAM_API_KEY)

# Логирование в Telegram
if STATUSCHAT_TELEGRAM_ID:
    telegram_handler = TelegramLogHandler(bot, STATUSCHAT_TELEGRAM_ID)
    telegram_handler.setLevel(getLoggingLevelByName(TELEGRAM_LOG_LEVEL))
    telegram_handler.setFormatter(simple_formatter)
    logger.addHandler(telegram_handler)
