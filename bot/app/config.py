# config.py

import os

# Настройки бота
TELEGRAM_API_KEY = os.getenv("TELEGRAM_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
INSTRUCTIONS_LENGTH_LIMIT = int(os.getenv("INSTRUCTIONS_LENGTH_LIMIT", "1024"))
INSTRUCTIONS_DEFAULT_TEXT = os.getenv(
    "INSTRUCTIONS_DEFAULT_TEXT", "Любые спам-признаки."
)
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")
STATUSCHAT_TELEGRAM_ID = os.getenv("STATUSCHAT_TELEGRAM_ID")

# Настройка Sentry для мониторинга ошибок
SENTRY_DSN = os.getenv("SENTRY_DSN")
APP_VERSION = os.getenv("APP_VERSION", "unknown")
DEBUG = os.getenv("DEBUG", "")

# Настройка уровней логирования
FILE_LOG_LEVEL = os.getenv("FILE_LOG_LEVEL", "INFO").upper()
CONSOLE_LOG_LEVEL = os.getenv("CONSOLE_LOG_LEVEL", "INFO").upper()
TELEGRAM_LOG_LEVEL = os.getenv("TELEGRAM_LOG_LEVEL", "WARNING").upper()

# Настройка базы данных MySQL
DB_CONFIG = {
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "db"),
    "database": os.getenv("DB_NAME"),
}

# Extended spam detection configuration
EXTENDED_SPAM_DETECTION_ENABLED = os.getenv("EXTENDED_SPAM_DETECTION_ENABLED", "true").lower() == "true"
EXTENDED_PREMIUM_CHANNEL_CHECK_ENABLED = os.getenv("EXTENDED_PREMIUM_CHANNEL_CHECK_ENABLED", "false").lower() == "true"
EXTENDED_BIO_INVITE_CHECK_ENABLED = os.getenv("EXTENDED_BIO_INVITE_CHECK_ENABLED", "true").lower() == "true"  
EXTENDED_CHANNEL_MESSAGE_CHECK_ENABLED = os.getenv("EXTENDED_CHANNEL_MESSAGE_CHECK_ENABLED", "true").lower() == "true"
