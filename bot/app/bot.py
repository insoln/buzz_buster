if __name__ == "__main__" and __package__ is None:
    from os import path
    import sys

    sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))
    __package__ = "workspace.app"

import asyncio
import logging
import os

try:
    import sentry_sdk  # type: ignore

    SENTRYSdkAvailable = True
except ImportError:
    sentry_sdk = None  # type: ignore
    SENTRYSdkAvailable = False
from app.telegram_messages import handle_message
from .telegram_groupmembership import handle_my_chat_members, handle_other_chat_members
from .telegram_commands import help_command, start_command, test_sentry_command, user_command, unban_command, ban_command, diag_command
from .logging_setup import logger, with_update_id
from .formatting import display_chat, display_user
from .database import (
    check_and_create_tables,
    load_configured_groups,
    load_user_caches,
)
from telegram import (
    Update,
)

from telegram.ext import (
    Application,
    CallbackContext,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from .config import *


def _debug_mode() -> bool:
    val = os.getenv("DEBUG", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


# Initialize Sentry for error monitoring (only if dependency & DSN present)
if SENTRY_DSN and SENTRYSdkAvailable:
    try:
        from sentry_sdk.integrations.logging import LoggingIntegration  # type: ignore
        from sentry_sdk.integrations.asyncio import AsyncioIntegration  # type: ignore

        sentry_logging = LoggingIntegration(
            level=logging.INFO, event_level=logging.ERROR
        )

        sentry_sdk.init(  # type: ignore
            dsn=SENTRY_DSN,
            send_default_pii=True,
            traces_sample_rate=0.1,
            profiles_sample_rate=0.01,  # lower profiling overhead
            integrations=[sentry_logging, AsyncioIntegration()],
            environment="development" if _debug_mode() else "production",
            release=os.getenv("APP_VERSION", "unknown"),
        )
        logger.info("Sentry initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Sentry: {e}")
elif SENTRY_DSN and not SENTRYSdkAvailable:
    logger.warning(
        "Sentry DSN provided but sentry-sdk not installed; monitoring disabled"
    )
else:
    logger.info("Sentry DSN not set; monitoring disabled")


def capture_exception_with_context(exc, extra_context=None):
    """Capture exception with additional context for Sentry if available."""
    if not (SENTRY_DSN and SENTRYSdkAvailable and sentry_sdk):  # type: ignore
        return
    try:
        with sentry_sdk.push_scope() as scope:  # type: ignore
            if extra_context:
                for key, value in extra_context.items():
                    scope.set_extra(key, value)
            sentry_sdk.capture_exception(exc)  # type: ignore
    except Exception:
        # Never let telemetry crash business logic
        pass


async def main():
    logger.info("Starting bot.")
    if not TELEGRAM_API_KEY:
        logger.critical(
            "TELEGRAM_API_KEY environment variable not set. Terminating app."
        )
        return

    # Проверка и создание таблиц
    try:
        check_and_create_tables()
        # Загрузка настроенных групп и кешей пользователей
        load_configured_groups()
        load_user_caches()
    except Exception as e:
        logger.exception("Failed to initialize database or load caches")
        capture_exception_with_context(e, {"component": "database_initialization"})
        return

    # Инициализируем приложение
    application = Application.builder().token(TELEGRAM_API_KEY).build()

    # Проверка валидности ключа
    try:
        me = await application.bot.get_me()
        logger.debug(f"Telegram API key is valid. Bot {display_user(me)} started")
        # Добавляем информацию о боте в Sentry context
        if SENTRY_DSN and SENTRYSdkAvailable and sentry_sdk:  # type: ignore
            try:
                sentry_sdk.set_user({"id": me.id, "username": me.username})  # type: ignore
                sentry_sdk.set_tag("bot_username", me.username)  # type: ignore
            except Exception:
                pass
    except Exception as e:
        logger.exception(f"Invalid TELEGRAM_API_KEY: {e}")
        capture_exception_with_context(e, {"component": "telegram_bot_initialization"})
        return

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start_command), group=1)
    application.add_handler(CommandHandler("help", help_command), group=1)
    application.add_handler(CommandHandler("test_sentry", test_sentry_command), group=1)
    application.add_handler(CommandHandler("user", user_command), group=1)
    application.add_handler(CommandHandler("unban", unban_command), group=1)
    application.add_handler(CommandHandler("ban", ban_command), group=1)
    application.add_handler(CommandHandler("diag", diag_command), group=1)

    # Регистрация обработчиков сообщений
    application.add_handler(
        MessageHandler(
            (filters.TEXT | (filters.PHOTO & filters.Caption())) & ~filters.COMMAND,
            handle_message,
        ),
        group=1,
    )

    # Регистрируем обработчик изменения членства себя в группе
    application.add_handler(
        ChatMemberHandler(handle_my_chat_members, ChatMemberHandler.MY_CHAT_MEMBER),
        group=2,
    )
    # Регистрируем обработчик изменения членства других в группе
    application.add_handler(
        ChatMemberHandler(handle_other_chat_members, ChatMemberHandler.CHAT_MEMBER),
        group=2,
    )

    # Регистрируем обработчик всех входящих событий для дебага

    @with_update_id
    async def raw_update_logger(update: Update, context: CallbackContext) -> None:
        """Логируем ПОЛНЫЙ сырой апдейт в плейнтексте до любой обработки.
        Используем repr + безопасный доступ к chat/user для дополнительных строк.
        """
        try:
            update_id = getattr(update, 'update_id', 'n/a')
            # raw repr / dict form
            raw_repr = repr(update)
            chat = getattr(update, 'effective_chat', None)
            user = getattr(update, 'effective_user', None)
            chat_display = display_chat(chat) if chat else '<no-chat>'
            user_display = display_user(user) if user else '<no-user>'
            logger.debug(f"RAW_UPDATE id={update_id} chat={chat_display} user={user_display} raw={raw_repr}")
        except Exception as e:
            logger.debug(f"RAW_UPDATE logging failed: {e}")

    # group=0 -> выполняется самым ранним, до других обработчиков
    application.add_handler(MessageHandler(filters.ALL, raw_update_logger), group=0)

    # Запускаем бота
    try:
        await application.initialize()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)  # type: ignore[attr-defined]
        await application.start()
        logger.info("Bot started successfully and polling for updates")
        # Optional startup notification to admin/status chat, safely wrapped
        target_chats = []
        if ADMIN_TELEGRAM_ID:
            try:
                target_chats.append(int(ADMIN_TELEGRAM_ID))
            except Exception:
                logger.warning(f"Invalid ADMIN_TELEGRAM_ID value: {ADMIN_TELEGRAM_ID}")
        if STATUSCHAT_TELEGRAM_ID:
            try:
                target_chats.append(int(STATUSCHAT_TELEGRAM_ID))
            except Exception:
                logger.warning(f"Invalid STATUSCHAT_TELEGRAM_ID value: {STATUSCHAT_TELEGRAM_ID}")
        for chat_id in target_chats:
            try:
                await application.bot.send_message(chat_id=chat_id, text="Bot startup OK")
            except Exception as e:
                # Avoid noisy stack traces for typical missing chat errors
                logger.info(f"Startup notification skipped for chat {chat_id}: {e}")

        try:
            # Run the bot until a termination signal is received
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit, asyncio.exceptions.CancelledError):
            logger.debug("Termination signal received. Shutting down...")
        finally:
            await application.updater.stop()  # type: ignore[attr-defined]
            await application.stop()
            await application.shutdown()
            logger.info("Bot stopped.")
    except Exception as e:
        logger.exception("Unexpected error during bot operation")
        capture_exception_with_context(e, {"component": "bot_main_loop"})
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.exception("Critical error in main function")
        capture_exception_with_context(e, {"component": "top_level"})
    finally:
        # Flush Sentry if available
        if SENTRY_DSN and SENTRYSdkAvailable and sentry_sdk:  # type: ignore
            try:
                sentry_sdk.flush()  # type: ignore
            except Exception:
                pass
