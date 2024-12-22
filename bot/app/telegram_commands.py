from .logging_setup import logger
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
    configured_groups_cache,
)
import mysql.connector
from .config import *


async def start_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /start."""
    logger.debug(
        f"Handling /start command from user {display_user(update.effective_user)} in chat {
            display_chat(update.effective_chat)}"
    )

    if update.effective_chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug("Received /start in private chat.")
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        user_status = chat_member.status
    except BadRequest as e:
        logger.exception(f"Failed to get chat member status for user {
                         user_id} in chat {chat_id}: {e}")
        user_status = None

    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        bot_status = bot_member.status
    except BadRequest as e:
        logger.exception(f"Failed to get bot's status in chat {chat_id}: {e}")
        bot_status = None

    if bot_status not in ["administrator", "creator"]:
        await update.message.reply_text("Мне нужны права администратора в этой группе.")
        logger.debug(f"Bot is not an admin in group {chat_id}.")
        return

    if user_status not in ["administrator", "creator"]:
        await update.message.reply_text("Только администраторы могут настраивать бота.")
        logger.debug(f"User {user_id} is not an admin.")
        return

    if is_group_configured(chat_id):
        await update.message.reply_text(
            "Бот уже настроен для этой группы. Используйте /help, чтобы увидеть доступные команды."
        )
        logger.debug(f"Group {chat_id} is already configured.")
        return

    # Настройка группы
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO `groups` (group_id) VALUES (%s)", (chat_id,))
        cursor.execute(
            "INSERT INTO `group_settings` (group_id, parameter, value) VALUES (%s, %s, %s)",
            (chat_id, "instructions", INSTRUCTIONS_DEFAULT_TEXT),
        )
        conn.commit()
    except mysql.connector.Error as err:
        logger.exception(f"Database error when configuring group {
                         chat_id}: {err}")
        await update.message.reply_text("Ошибка настройки бота для этой группы.")
        return
    finally:
        cursor.close()
        conn.close()

    # Обновление кэша настроенных групп
    configured_groups_cache.append(
        {"group_id": chat_id, "settings": {
            "instructions": INSTRUCTIONS_DEFAULT_TEXT}}
    )

    await update.message.reply_text(
        "Бот настроен для этой группы. Используйте /help, чтобы увидеть доступные команды."
    )
    logger.info(f"Group {chat_id} has been configured.")


async def help_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /help."""
    logger.debug(
        f"Handling /help command from user {display_user(update.effective_user)} in chat {
            display_chat(update.effective_chat)}"
    )

    if update.effective_chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug("Received /help in private chat.")
        return

    chat_id = update.effective_chat.id

    if is_group_configured(chat_id):
        await update.message.reply_text(
            "Доступные команды:\n"
            "/start - Настроить бота\n"
            "/help - Показать это сообщение\n"
            "/set <parameter> <value> - Установить параметр\n"
            "/get <parameter> - Получить значение параметра\n"
            "\n"
            "Доступные параметры:\n"
            "- instructions: Что ИИ должен считать спамом"
        )
        logger.debug(f"Help command received in configured group {chat_id}.")
    else:
        await update.message.reply_text(
            "Я не настроен для работы в этой группе. Используйте /start, чтобы настроить меня."
        )
        logger.debug(f"Help command received in unconfigured group {chat_id}.")


async def set_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /set."""
    logger.debug(
        f"Handling /set command from user {display_user(update.effective_user)} in chat {
            display_chat(update.effective_chat)}"
    )

    if update.effective_chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug("Received /set in private chat.")
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    chat_member = await context.bot.get_chat_member(chat_id, user_id)
    if chat_member.status not in ["administrator", "creator"]:
        await update.message.reply_text("Только администраторы могут настраивать бота.")
        logger.debug(f"User {user_id} is not an admin.")
        return

    if not is_group_configured(chat_id):
        await update.message.reply_text("Бот не настроен для этой группы. Используйте /start.")
        logger.debug(f"Group {chat_id} is not configured.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Использование: /set <parameter> <value>")
        logger.debug("Incorrect /set command usage.")
        return

    parameter = context.args[0]
    value = " ".join(context.args[1:])

    allowed_parameters = ["instructions"]

    if parameter not in allowed_parameters:
        await update.message.reply_text(f"Недопустимый параметр: {parameter}")
        logger.debug(f"Invalid parameter {parameter} used in /set.")
        return

    if parameter == "instructions" and len(value) > INSTRUCTIONS_LENGTH_LIMIT:
        await update.message.reply_text(
            f"Значение для {parameter} превышает лимит длины в {
                INSTRUCTIONS_LENGTH_LIMIT} символов."
        )
        logger.debug(f"Value for {parameter} exceeds length limit.")
        return

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO group_settings (group_id, parameter, value) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE value=%s",
            (chat_id, parameter, value, value),
        )
        conn.commit()
    except mysql.connector.Error as err:
        logger.exception(f"Database error when setting parameter {
                         parameter}: {err}")
        await update.message.reply_text("Ошибка установки параметра.")
        return
    finally:
        cursor.close()
        conn.close()

    # Обновление кэша настроенных групп
    for group in configured_groups_cache:
        if group["group_id"] == chat_id:
            group["settings"][parameter] = value
            break
    else:
        configured_groups_cache.append(
            {"group_id": chat_id, "settings": {parameter: value}}
        )

    await update.message.reply_text(f"Параметр {parameter} установлен в {value}.")
    logger.info(f"Parameter {parameter} set to {value} in group {chat_id}.")


async def get_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /get."""
    logger.debug(
        f"Handling /get command from user {display_user(update.effective_user)} in chat {
            display_chat(update.effective_chat)}"
    )

    if update.effective_chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug("Received /get in private chat.")
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    chat_member = await context.bot.get_chat_member(chat_id, user_id)
    if chat_member.status not in ["administrator", "creator"]:
        await update.message.reply_text("Только администраторы могут получать настройки бота.")
        logger.debug(f"User {user_id} is not an admin.")
        return

    if not is_group_configured(chat_id):
        await update.message.reply_text("Бот не настроен для этой группы. Используйте /start.")
        logger.debug(f"Group {chat_id} is not configured.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Использование: /get <parameter>")
        logger.debug("Incorrect /get command usage.")
        return

    parameter = context.args[0]

    for group in configured_groups_cache:
        if group["group_id"] == chat_id:
            value = group["settings"].get(parameter)
            if value:
                await update.message.reply_text(f"{parameter}: {value}")
                logger.debug(
                    f"Parameter {parameter} retrieved with value {value}.")
            else:
                await update.message.reply_text(f"Параметр {parameter} не найден.")
                logger.debug(f"Parameter {parameter} not found.")
            break
    else:
        await update.message.reply_text("Ошибка при получении параметра.")
        logger.debug(f"Group {chat_id} not found in cache.")

