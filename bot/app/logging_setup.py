# logging_setup.py

import logging
import logging.handlers
import os
from .config import *
import asyncio
from telegram import Bot
from contextvars import ContextVar

current_update_id = ContextVar('current_update_id', default=None)

class UpdateIDFilter(logging.Filter):
    def filter(self, record):
        update_id = current_update_id.get()
        record.update_id = update_id if update_id is not None else '__main__'
        return True

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
console_formatter = logging.Formatter('%(update_id)s %(asctime)s - %(levelname)s (%(filename)s:%(lineno)d): %(message)s')
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
telegram_formatter = logging.Formatter("%(message)s")

# Логирование в файл
log_path = "/workspace/app/buzzbuster.log"
if not os.path.exists(os.path.dirname(log_path)):
    log_path = "/tmp/buzzbuster.log"

file_handler = logging.handlers.RotatingFileHandler(
    log_path, maxBytes=5 * 1024 * 1024, backupCount=2
)
file_handler.setLevel(getattr(logging, FILE_LOG_LEVEL, logging.INFO))
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)
logger.addFilter(UpdateIDFilter())


# Логирование в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(
    getattr(logging, CONSOLE_LOG_LEVEL, logging.INFO))
console_handler.setFormatter(console_formatter)
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
    telegram_handler.setFormatter(telegram_formatter)
    logger.addHandler(telegram_handler)
