from .logging_setup import logger, current_update_id
from telegram import (
    Update,
)
from telegram.error import BadRequest
from telegram.ext import (
    CallbackContext,
)
from .formatting import display_chat, display_user
from .database import (
    is_group_configured,
    add_configured_group,
)
import mysql.connector
from .config import *


async def start_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /start."""
    current_update_id.set(update.update_id)
    chat = update.effective_chat
    user = update.effective_user
    logger.debug(
        f"Handling /start command from user {display_user(user)} in chat {display_chat(chat)}"
    )

    if chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug("Received /start in private chat.")
        return

    try:
        chat_member = await context.bot.get_chat_member(chat.id, user.id)
        user_status = chat_member.status
    except BadRequest as e:
        logger.exception(f"Failed to get chat member status for user {display_user(user)} in chat {display_chat(chat)}: {e}")
        user_status = None

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        bot_status = bot_member.status
    except BadRequest as e:
        logger.exception(f"Failed to get bot's status in chat {display_chat(chat)}: {e}")
        bot_status = None

    if bot_status not in ["administrator", "creator"]:
        await update.message.reply_text("Мне нужны права администратора в этой группе.")
        logger.debug(f"Bot is not an admin in group {display_chat(chat)}.")
        return

    if user_status not in ["administrator", "creator"]:
        await update.message.reply_text("Только администраторы могут настраивать бота.")
        logger.debug(f"User {display_user(user)} tried to configure group {display_chat(chat)} but they're not admin.")
        return

    if is_group_configured(chat.id):
        await update.message.reply_text(
            "Бот уже настроен для этой группы. Используйте /help, чтобы увидеть доступные команды."
        )
        logger.debug(f"User {display_user(user)} tried to configure group {display_chat(chat)}, but this group is already configured.")
        return

    # Настройка группы
    await add_configured_group(chat, update)


async def help_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /help."""
    current_update_id.set(update.update_id)
    chat = update.effective_chat
    user = update.effective_user
    logger.debug(
        f"Handling /help command from user {display_user(user)} in chat {
            display_chat(chat)}"
    )

    if chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug(f"Received /help in private chat from user {display_user(user)} in chat {display_chat(chat)}")
        return

    chat_id = update.effective_chat.id

    if is_group_configured(chat_id):
        await update.message.reply_text(
            "Доступные команды:\n"
            "/start - Настроить бота\n"
            "/help - Показать это сообщение"
        )
        logger.debug(f"Help command received from user {display_user(user)} in configured group {display_chat(chat)}.")
    else:
        await update.message.reply_text(
            "Я не настроен для работы в этой группе. Используйте /start, чтобы настроить меня."
        )
        logger.debug(f"Help command received from user {display_user(user)} in unconfigured group {display_chat(chat)}.")
