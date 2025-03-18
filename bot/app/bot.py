if __name__ == "__main__" and __package__ is None:
    from os import path
    import sys
    sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))
    __package__ = "workspace.app"

import asyncio
from app.telegram_messages import (
    handle_message
)
from .telegram_groupmembership import (
    handle_my_chat_members,
    handle_other_chat_members
)
from .telegram_commands import (
    help_command,
    start_command
)
from .logging_setup import logger
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


async def main():
    logger.info("Starting bot.")
    if not TELEGRAM_API_KEY:
        logger.critical(
            "TELEGRAM_API_KEY environment variable not set. Terminating app.")
        return

    # Проверка и создание таблиц
    check_and_create_tables()
    # Загрузка настроенных групп и кешей пользователей
    load_configured_groups()
    load_user_caches()

    # Инициализируем приложение
    application = Application.builder().token(TELEGRAM_API_KEY).build()

    # Проверка валидности ключа
    try:
        me = await application.bot.get_me()
        logger.debug(f"Telegram API key is valid. Bot {
                     display_user(me)} started")
    except Exception as e:
        logger.exception(f"Invalid TELEGRAM_API_KEY: {e}")
        return

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start_command), group=1)
    application.add_handler(CommandHandler("help", help_command), group=1)

    # Регистрация обработчиков сообщений
    application.add_handler(
        MessageHandler(
            (
                filters.TEXT |
                (filters.PHOTO & filters.Caption())
            ) & ~filters.COMMAND, handle_message), group=1
    )

    # Регистрируем обработчик изменения членства себя в группе
    application.add_handler(
        ChatMemberHandler(handle_my_chat_members,
                          ChatMemberHandler.MY_CHAT_MEMBER),
        group=2,
    )
    # Регистрируем обработчик изменения членства других в группе
    application.add_handler(
        ChatMemberHandler(handle_other_chat_members,
                          ChatMemberHandler.CHAT_MEMBER),
        group=2,
    )

    # Регистрируем обработчик всех входящих событий для дебага

    async def log_event(update: Update, context: CallbackContext) -> None:
        logger.debug(f"Received event: {update}")

    application.add_handler(MessageHandler(filters.ALL, log_event), group=0)

    # Запускаем бота
    await application.initialize()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    await application.start()

    try:
        # Run the bot until a termination signal is received
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit, asyncio.exceptions.CancelledError):
        logger.debug("Termination signal received. Shutting down...")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("Bot stopped.")

if __name__ == "__main__":
    asyncio.run(main())
