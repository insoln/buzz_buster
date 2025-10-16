from .logging_setup import logger,current_update_id
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
    is_user_trusted,
    is_user_spammer_anywhere,
    is_user_spammer_in_group
)
import mysql.connector
from .config import *


async def handle_message(update: Update, context: CallbackContext) -> None:
    """Обработка входящих сообщений в настроенных группах."""
    current_update_id.set(update.update_id)

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

    # Проверка: если пользователь уже спамер в любой группе - банить в текущей группе
    if is_user_spammer_anywhere(user.id):
        if not is_user_spammer_in_group(user.id, chat.id):
            # Банить и пометить как спамера в этой группе
            await context.bot.ban_chat_member(chat.id, user.id)
            await update.message.delete()
            
            # Добавить в кеш спамеров для этой группы
            if user.id not in spammers_cache:
                spammers_cache[user.id] = set()
            spammers_cache[user.id].add(chat.id)
            
            # Обновить базу данных
            try:
                conn = mysql.connector.connect(**DB_CONFIG)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO user_entries (user_id, group_id, join_date, spammer)
                    VALUES (%s, %s, NOW(), TRUE)
                    ON DUPLICATE KEY UPDATE spammer = TRUE
                    """,
                    (user.id, chat.id),
                )
                conn.commit()
            except mysql.connector.Error as err:
                logger.exception(f"Database error when marking user as spammer: {err}")
            finally:
                cursor.close()
                conn.close()
            
            logger.info(
                f"Banned cross-group spammer {display_user(user)} from group {display_chat(chat)}."
            )
        else:
            # Уже спамер в этой группе, просто удалить сообщение
            await update.message.delete()
            logger.info(
                f"Deleted message from known spammer {display_user(user)} in group {display_chat(chat)}."
            )
        return

    # Проверка: если пользователь доверенный (seen_message=TRUE в любой группе) - пропустить проверку
    if is_user_trusted(user.id):
        logger.debug(f"User {display_user(user)} is trusted, skipping spam check.")
        
        # Обновить seen_message для этой группы, если еще не установлено
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_entries (user_id, group_id, join_date, seen_message)
                VALUES (%s, %s, NOW(), TRUE)
                ON DUPLICATE KEY UPDATE seen_message = TRUE
                """,
                (user.id, chat.id),
            )
            conn.commit()
        except mysql.connector.Error as err:
            logger.exception(f"Database error when updating seen_message: {err}")
        finally:
            cursor.close()
            conn.close()
        return

    # Пользователь не доверенный - проводить проверку на спам
    is_spam = False
    
    # Проверка на форвард
    if update.message.forward_origin:
        is_spam = True     
    
    # Проверка через OpenAI
    if not is_spam:
        try:
            group_settings = next(
                (group["settings"]
                for group in configured_groups_cache if group["group_id"] == chat.id),
                {},
            )        
            instructions = group_settings.get("instructions", INSTRUCTIONS_DEFAULT_TEXT)
            logger.debug(f"Sending prompt to OpenAI for user {display_user(user)}.")
            is_spam = await check_openai_spam(update.message.text or update.message.caption, instructions)
        except Exception as e:
            logger.exception(f"Error querying OpenAI for message processing: {e}")                

    try:
        if is_spam:
            logger.info(
                f"Message from {display_user(user)} is identified as spam, user will be banned in this group."
            )
            await context.bot.ban_chat_member(chat.id, user.id)
            await update.message.delete()
            
            # Добавить в кеш спамеров для этой группы
            if user.id not in spammers_cache:
                spammers_cache[user.id] = set()
            spammers_cache[user.id].add(chat.id)

            # Обновление базы данных
            try:
                conn = mysql.connector.connect(**DB_CONFIG)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO user_entries (user_id, group_id, join_date, spammer)
                    VALUES (%s, %s, NOW(), TRUE)
                    ON DUPLICATE KEY UPDATE spammer = TRUE
                    """,
                    (user.id, chat.id),
                )
                conn.commit()
            except mysql.connector.Error as err:
                logger.exception(f"Database error when updating spammer status: {err}")
            finally:
                cursor.close()
                conn.close()

            logger.info(f"Banned spammer {display_user(user)} from group {display_chat(chat)}.")
        else:
            # Сообщение не спам - пометить пользователя как доверенного
            try:
                conn = mysql.connector.connect(**DB_CONFIG)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO user_entries (user_id, group_id, join_date, seen_message)
                    VALUES (%s, %s, NOW(), TRUE)
                    ON DUPLICATE KEY UPDATE seen_message = TRUE
                    """,
                    (user.id, chat.id),
                )
                conn.commit()
            except mysql.connector.Error as err:
                logger.exception(f"Database error when updating user entry: {err}")
            finally:
                cursor.close()
                conn.close()

            logger.info(f"Message from user {display_user(user)} is not spam. User is now trusted.")
    except Exception as e:
        logger.exception(f"Error processing message from user {display_user(user)}: {e}")
    else:
        logger.debug(f"User {display_user(user)} message processed normally.")
