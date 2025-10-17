# logging_setup.py

import logging
import logging.handlers
import logging.config
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

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {
            "format": "%(update_id)s %(asctime)s - %(levelname)s (%(filename)s:%(lineno)d): %(message)s"
        },
        "file": {
            "format": "%(asctime)s - %(levelname)s - %(message)s"
        },
        "telegram": {
            "format": "%(message)s"
        },
    },
    "filters": {
        "update_id_filter": {
            "()": "app.logging_filters.UpdateIDFilter"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": CONSOLE_LOG_LEVEL,
            "formatter": "console",
            "filters": ["update_id_filter"]
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": FILE_LOG_LEVEL,
            "formatter": "file",
            "filename": "/workspace/app/buzzbuster.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 2,
            "filters": ["update_id_filter"]
        },
        # Логирование в Telegram можно оставить как есть
    },
    "loggers": {
        "telegram_bot": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False
        }
    }
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("telegram_bot")

def log_event(action: str, **fields):
    """Структурированное логирование одного события в JSON.
    action: строковый тип события (ban, mark_spammer, first_message_seen, join, unban, cas_ban,...)
    Остальные именованные параметры сериализуются. Ошибки сериализации не роняют выполнение.
    """
    import json
    import time
    payload = {
        "ts": time.time(),
        "action": action,
    }
    # update_id из контекстной переменной если есть
    try:
        upd_id = current_update_id.get()
        if upd_id is not None:
            payload["update_id"] = upd_id
    except Exception:
        pass
    # Добавляем пользовательские поля
    for k, v in fields.items():
        # Пробуем привести к простому виду
        try:
            if hasattr(v, 'id') and not isinstance(v, (int, str)):
                # Telegram objects -> id
                payload[k] = getattr(v, 'id', str(v))
            else:
                payload[k] = v
        except Exception:
            payload[k] = str(v)
    try:
        logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    except Exception:
        logger.info(f"STRUCT_LOG_FALLBACK action={action} fields={fields}")

def getLoggingLevelByName(level: str) -> int:
    """Получение уровня логирования по имени."""
    return getattr(logging, level.upper(), logging.WARNING)

# Создаем экземпляр бота для отправки уведомлений (если токен задан)
bot = Bot(token=TELEGRAM_API_KEY) if TELEGRAM_API_KEY and TELEGRAM_API_KEY.strip() else None

# Логирование в Telegram
if STATUSCHAT_TELEGRAM_ID and bot is not None:
    telegram_handler = TelegramLogHandler(bot, STATUSCHAT_TELEGRAM_ID)
    telegram_handler.setLevel(getLoggingLevelByName(TELEGRAM_LOG_LEVEL))
    telegram_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(telegram_handler)
