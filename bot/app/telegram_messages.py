from .logging_setup import logger
from .antispam import check_openai_spam

from telegram import (
    Update,
)

from telegram.ext import (
    CallbackContext,
)
from .formatting import display_chat, display_user
from .database import (
    is_group_configured,
    configured_groups_cache,
    spammers_cache,
    suspicious_users_cache
)
import mysql.connector
from .config import *


async def handle_message(update: Update, context: CallbackContext) -> None:
    """Обработка входящих сообщений в настроенных группах."""
    
    if not update.message:
        logger.debug("Received update without message.")
        return

    chat = update.effective_chat
    user = update.effective_user

    logger.debug(
        f"Handling message from user {display_user(user)} in chat {
            display_chat(chat)} with text: {update.message.text or update.message.caption}."
    )

    if chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug("Received message in private chat.")
        return

    if not is_group_configured(chat.id):
        logger.debug(f"Group {chat.id} is not configured.")
        return

    if user.id in spammers_cache:
        await context.bot.ban_chat_member(chat.id, user.id)
        await update.message.delete()
        logger.info(
            f"Banned known spammer {display_user(user)} from group {
                display_chat(chat)}."
        )
        return

    if user.id in suspicious_users_cache:
        # Получаем настройки группы
        group_settings = next(
            (group["settings"]
             for group in configured_groups_cache if group["group_id"] == chat.id),
            {},
        )
        instructions = group_settings.get(
            "instructions", INSTRUCTIONS_DEFAULT_TEXT)
        try:
            logger.debug(f"Sending prompt to OpenAI for user {
                         display_user(user)}.")
            is_spam = await check_openai_spam(update.message.text or update.message.caption, instructions)
            if is_spam:
                logger.info(
                    f"User {display_user(
                        user)} is identified as spammer, it will be banned in all groups."
                )
                await context.bot.ban_chat_member(chat.id, user.id)
                await update.message.delete()
                spammers_cache.add(user.id)
                suspicious_users_cache.discard(user.id)

                # Обновление базы данных
                try:
                    conn = mysql.connector.connect(**DB_CONFIG)
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        UPDATE `user_entries` set spammer = TRUE where user_id=%s and group_id = %s
                        """,
                        (user.id, chat.id),
                    )
                    conn.commit()
                except mysql.connector.Error as err:
                    logger.exception(
                        f"Database error when updating spammer status: {err}")
                finally:
                    cursor.close()
                    conn.close()

                logger.info(
                    f"Banned spammer {display_user(user)} from group {
                        display_chat(chat)}."
                )
            else:
                suspicious_users_cache.discard(user.id)
                try:
                    conn = mysql.connector.connect(**DB_CONFIG)
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        UPDATE user_entries SET seen_message = TRUE, spammer = FALSE WHERE user_id = %s
                        """,
                        (user.id,),
                    )
                    conn.commit()
                except mysql.connector.Error as err:
                    logger.exception(
                        f"Database error when updating user entry: {err}")
                finally:
                    cursor.close()
                    conn.close()

                logger.info(
                    f"Message from user {display_user(user)} is not spam."
                )
        except Exception as e:
            logger.exception(
                f"Error querying OpenAI for message processing: {e}")
    else:
        logger.debug(f"User {display_user(user)} is not in suspicious users cache.")
