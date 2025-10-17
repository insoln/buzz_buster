# logging_setup.py

import logging
import logging.handlers
import logging.config
from .config import *
import asyncio
from telegram import Bot
from .logging_filters import current_update_id, UpdateIDFilter  # single source of truth
from contextvars import ContextVar


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
            # update_id уже добавляется через фильтр; усиливаем формат и добавляем действие если присвоено
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
            # Allow propagation so pytest caplog (attached to root) can capture records during tests.
            # Root has no handlers by default in our config, so duplicate emission will not occur.
            "propagate": True
        }
    }
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("telegram_bot")
# Ensure update_id injected even when caplog captures before handler filters
logger.addFilter(UpdateIDFilter())

def _safe_display_user(user):
    try:
        from .formatting import display_user
        return display_user(user)
    except Exception:
        return str(getattr(user, 'id', user))

def _safe_display_chat(chat):
    try:
        from .formatting import display_chat
        return display_chat(chat)
    except Exception:
        return str(getattr(chat, 'id', chat))

# Track whether an info-level event already emitted for current update
update_info_used = ContextVar('update_info_used', default=False)

# Actions considered "essential" classification/state-change events eligible for INFO level
ESSENTIAL_ACTIONS = {
    'ban_global_spammer', 'first_message_spam', 'first_message_ham',
    'new_user_spam', 'new_user_ham', 'late_suspicious_spam', 'late_suspicious_ham',
    'unban_clear_spammer', 'join_ban_known_spammer', 'cas_ban',
    'inherit_trust', 'late_seen_upgrade', 'admin_global_unban', 'admin_force_ban'
}

# Actions considered low-value (noise) will always be DEBUG (explicit list optional; fallback is debug anyway)
NOISY_ACTIONS = {
    'message_receive', 'skip_not_configured', 'skip_seen', 'skip_no_chat_member',
    'skip_no_chat', 'skip_no_new_chat_member', 'skip_no_my_chat_member',
    'skip_my_chat_member_no_chat', 'skip_my_chat_member_no_new_member',
    'my_chat_members_update', 'join_new_suspicious', 'join_seen_elsewhere',
    'bot_added_group', 'bot_no_admin_rights', 'bot_promoted_admin', 'bot_promoted_no_send_rights',
    'bot_removed', 'bot_removed_confirm', 'bot_removed_not_configured', 'channel_configured',
    'channel_config_error', 'group_removed_db', 'group_remove_error', 'bot_added_by_non_admin',
    'check_member_status_error', 'chat_member_update', 'user_left', 'unhandled_path'
}

def _human_summary(action: str, payload: dict) -> str:
    """Generate a concise human-readable summary for INFO/WARNING events."""
    user = payload.get('user_display') or f"user={payload.get('user_id')}"
    chat = payload.get('chat_display') or f"chat={payload.get('chat_id')}"
    if action in {'ban_global_spammer','join_ban_known_spammer','cas_ban'}:
        return f"Banned spammer {user} in {chat}."
    if action == 'admin_force_ban':
        ban_success = payload.get('ban_success')
        ban_error = payload.get('ban_error')
        if ban_success:
            return f"Admin forcibly marked & banned user={payload.get('target_user_id')} in chat={payload.get('target_group_id')}"
        if ban_error:
            return f"Admin forcibly marked user={payload.get('target_user_id')} SPAM in chat={payload.get('target_group_id')} (ban failed: {ban_error})"
        return f"Admin forcibly marked user={payload.get('target_user_id')} SPAM in chat={payload.get('target_group_id')}"
    if action in {'first_message_spam','new_user_spam','late_suspicious_spam'}:
        return f"Classified {user} as SPAM in {chat} (first message path)."
    if action in {'first_message_ham','new_user_ham','late_suspicious_ham','inherit_trust','late_seen_upgrade'}:
        return f"Trusted {user} in {chat} (first message HAM)."
    if action == 'unban_clear_spammer':
        other = payload.get('other_groups') or []
        if other:
            return f"Local unban for {user} in {chat}; still flagged in {other}."
        return f"Unban cleared global spam flag for {user}."
    if action == 'admin_global_unban':
        cleared = payload.get('cleared_groups', [])
        return f"Admin globally unbanned user={payload.get('target_user_id')} from groups {cleared or '[]'}."
    if action == 'channel_configured':
        return f"Channel {chat} configured."
    if action == 'channel_config_error':
        return f"Channel {chat} configuration error: {payload.get('error')}"
    if action == 'group_remove_error':
        return f"Group removal DB error for {chat}: {payload.get('error')}"
    if action == 'group_removed_db':
        return f"Group {chat} removed from DB."
    if 'error' in payload:
        return f"Action {action} error: {payload.get('error')} (user={user}, chat={chat})"
    return f"Action {action} user={user} chat={chat}"

def log_event(action: str, **fields):
    """Структурированное логирование одного события в JSON.
    action: строковый тип события (ban, mark_spammer, first_message_seen, join, unban, cas_ban,...)
    Остальные именованные параметры сериализуются. Ошибки сериализации не роняют выполнение.
    """
    import json, time
    payload = {
        "ts": time.time(),
        "action": action,
    }
    # update_id из контекстной переменной если есть
    upd_id = current_update_id.get()
    if upd_id is not None:
        payload["update_id"] = upd_id
    # Добавляем пользовательские поля
    for k, v in fields.items():
        try:
            if k == 'user' or k == 'user_obj':
                payload['user_display'] = _safe_display_user(v)
                payload['user_id'] = getattr(v, 'id', v if isinstance(v, int) else None)
            elif k == 'chat' or k == 'chat_obj':
                payload['chat_display'] = _safe_display_chat(v)
                payload['chat_id'] = getattr(v, 'id', v if isinstance(v, int) else None)
            elif k == 'user_id':
                payload['user_id'] = v
            elif k == 'chat_id':
                payload['chat_id'] = v
            else:
                payload[k] = v
        except Exception:
            payload[k] = str(v)

    # Если есть user_id но нет user_display и нам передали объект user -> попытка реконструкции из полей
    if 'user_id' in payload and 'user_display' not in payload and 'user' in fields:
        payload['user_display'] = _safe_display_user(fields['user'])
    if 'chat_id' in payload and 'chat_display' not in payload and 'chat' in fields:
        payload['chat_display'] = _safe_display_chat(fields['chat'])
    # Determine log level
    level = logging.DEBUG
    info_already = update_info_used.get()
    # Elevate to INFO if essential and none emitted yet
    if (action in ESSENTIAL_ACTIONS) and not info_already:
        level = logging.INFO
        update_info_used.set(True)
    # Error actions escalate to WARNING if error field present
    if 'error' in payload and level < logging.WARNING:
        level = logging.WARNING
    record_text = None
    try:
        record_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except Exception:
        record_text = f"STRUCT_LOG_FALLBACK action={action} fields={fields}"
    # Always emit structured JSON at DEBUG for machine parsing
    logger.log(logging.DEBUG, record_text)
    # Emit human-readable summary at computed level if level >= INFO
    if level >= logging.INFO:
        try:
            summary = _human_summary(action, payload)
            logger.log(level, summary)
        except Exception:
            pass
    # If level is WARNING (due to error) and no summary produced, ensure a fallback human line
    elif level >= logging.WARNING:
        logger.log(level, f"{action} (user={payload.get('user_id')} chat={payload.get('chat_id')})")

from functools import wraps

def with_update_id(func):
    """Decorator ensuring current_update_id ContextVar is set for the duration of handler execution.
    Works for async handler signature (update, context) or any callable where first arg is Update-like.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Identify update object (first positional or keyword 'update')
        update_obj = None
        if args:
            update_obj = args[0]
        if update_obj is None and 'update' in kwargs:
            update_obj = kwargs['update']
        try:
            upd_id = getattr(update_obj, 'update_id', None)
            if upd_id is not None:
                current_update_id.set(upd_id)
                # Reset per-update info flag
                update_info_used.set(False)
        except Exception:
            pass
        return await func(*args, **kwargs)
    return wrapper

def log_user_event(action: str, user, **extra):
    return log_event(action, user=user, **extra)

def log_chat_event(action: str, chat, **extra):
    return log_event(action, chat=chat, **extra)

def getLoggingLevelByName(level: str) -> int:
    """Получение уровня логирования по имени."""
    return getattr(logging, level.upper(), logging.WARNING)

# Создаем экземпляр бота для отправки уведомлений (если токен задан)
bot = Bot(token=TELEGRAM_API_KEY) if TELEGRAM_API_KEY else None

# Логирование в Telegram
if STATUSCHAT_TELEGRAM_ID and bot is not None:
    telegram_handler = TelegramLogHandler(bot, STATUSCHAT_TELEGRAM_ID)
    telegram_handler.setLevel(getLoggingLevelByName(TELEGRAM_LOG_LEVEL))
    telegram_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(telegram_handler)
