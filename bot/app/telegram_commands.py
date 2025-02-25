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
    configured_groups_cache,
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
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO `groups` (group_id) VALUES (%s) ON DUPLICATE KEY UPDATE group_id=group_id",
            (chat.id,)
        )
        cursor.execute(
            "INSERT INTO `group_settings` (group_id, parameter, value) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE value=%s",
            (chat.id, "instructions", INSTRUCTIONS_DEFAULT_TEXT, INSTRUCTIONS_DEFAULT_TEXT)
        )
        conn.commit()
    except mysql.connector.Error as err:
        logger.exception(f"Database error when configuring group {display_chat(chat)}: {err}")
        await update.message.reply_text("Ошибка настройки бота для этой группы.")
        return
    finally:
        cursor.close()
        conn.close()

    # Обновление кэша настроенных групп
    configured_groups_cache.append(
        {"group_id": chat.id, "settings": {
            "instructions": INSTRUCTIONS_DEFAULT_TEXT}}
    )

    await update.message.reply_text(
        "Бот настроен для этой группы. Используйте /help, чтобы увидеть доступные команды."
    )
    logger.info(f"User {display_user(user)} configured group {display_chat(chat)}.")


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
            "/help - Показать это сообщение\n"
            "/set <parameter> <value> - Установить параметр\n"
            "/get <parameter> - Получить значение параметра\n"
            "\n"
            "Доступные параметры:\n"
            "- instructions: Что ИИ должен считать спамом"
        )
        logger.debug(f"Help command received from user {display_user(user)} in configured group {display_chat(chat)}.")
    else:
        await update.message.reply_text(
            "Я не настроен для работы в этой группе. Используйте /start, чтобы настроить меня."
        )
        logger.debug(f"Help command received from user {display_user(user)} in unconfigured group {display_chat(chat)}.")


async def set_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /set."""
    current_update_id.set(update.update_id)
    chat = update.effective_chat
    user = update.effective_user

    logger.debug(
        f"Handling /set command from user {display_user(user)} in chat {display_chat(chat)}"
    )

    if chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug(f"Received /set in private chat from user {display_user(user)}.")
        return

    chat_member = await context.bot.get_chat_member(chat.id, user.id)
    if chat_member.status not in ["administrator", "creator"]:
        await update.message.reply_text("Только администраторы могут настраивать бота.")
        logger.debug(f"User {display_user(user)} tried to change parameters in group {display_chat(chat)}, but is not an admin.")
        return

    if not is_group_configured(chat.id):
        await update.message.reply_text("Бот не настроен для этой группы. Используйте /start.")
        logger.debug(f"User {display_user(user)} tried to change parameters in group {display_chat(chat)}, but group is not configured.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Использование: /set <parameter> <value>")
        logger.debug(f"User {display_user(user)} tried to change parameters in group {display_chat(chat)}, but /set command format was incorrect.")
        return

    parameter = context.args[0]
    value = " ".join(context.args[1:])

    allowed_parameters = ["instructions"]

    if parameter not in allowed_parameters:
        await update.message.reply_text(f"Недопустимый параметр: {parameter}")
        logger.debug(f"User {display_user(user)} tried to change parameters in group {display_chat(chat)}, but /set parameter {parameter} was incorrect.")
        return

    if parameter == "instructions" and len(value) > INSTRUCTIONS_LENGTH_LIMIT:
        await update.message.reply_text(
            f"Значение для {parameter} превышает лимит длины в {
                INSTRUCTIONS_LENGTH_LIMIT} символов."
        )
        logger.debug(f"User {display_user(user)} tried to change parameters in group {display_chat(chat)}, but /set parameter {parameter} was too long.")
        return

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO group_settings (group_id, parameter, value) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE value=%s",
            (chat.id, parameter, value, value),
        )
        conn.commit()
    except mysql.connector.Error as err:
        logger.exception(f"User {display_user(user)} tried to change parameters in group {display_chat(chat)}, but database error has occured when setting parameter {parameter}: {err}")
        await update.message.reply_text("Ошибка установки параметра.")
        return
    finally:
        cursor.close()
        conn.close()

    # Обновление кэша настроенных групп
    for group in configured_groups_cache:
        if group["group_id"] == chat.id:
            group["settings"][parameter] = value
            break
    else:
        configured_groups_cache.append(
            {"group_id": chat.id, "settings": {parameter: value}}
        )

    await update.message.reply_text(f"Параметр {parameter} установлен в {value}.")
    logger.info(f"User {display_user(user)} in group {display_chat(chat)} changed parameter {parameter} to {value}")


async def get_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /get."""
    current_update_id.set(update.update_id)
    chat = update.effective_chat
    user = update.effective_user
    logger.debug(
        f"Handling /get command from user {display_user(user)} in chat {display_chat(chat)}"
    )

    if chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug(f"Received /get in private chat from user {display_user(user)} in chat {display_chat(chat)}.")
        return

    chat_id = chat.id

    chat_member = await context.bot.get_chat_member(chat.id, user.id)
    if chat_member.status not in ["administrator", "creator"]:
        await update.message.reply_text("Только администраторы могут получать настройки бота.")
        logger.debug(f"User {display_user(user)} tried to get settings in group {display_chat(chat)}, but is not an admin.")
        return

    if not is_group_configured(chat_id):
        await update.message.reply_text("Бот не настроен для этой группы. Используйте /start.")
        logger.debug(f"Get command received from user {display_user(user)} in unconfigured group {display_chat(chat)}.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Использование: /get <parameter>")
        logger.debug(f"User {display_user(user)} in group {display_chat(chat)} used incorrect /get command usage.")
        return

    parameter = context.args[0]

    for group in configured_groups_cache:
        if group["group_id"] == chat_id:
            value = group["settings"].get(parameter)
            if value:
                await update.message.reply_text(f"{parameter}: {value}")
                logger.debug(
                    f"User {display_user(user)} in group {display_chat(chat)} retrieved parameter {parameter} with value {value}."
                )
            else:
                await update.message.reply_text(f"Параметр {parameter} не найден.")
                logger.debug(f"Parameter {parameter} not found in group {display_chat(chat)} for user {display_user(user)}.")
            break
    else:
        await update.message.reply_text("Ошибка при получении параметра.")
        logger.debug(f"Group {display_chat(chat)} not found in cache when requested by user {display_user(user)}.")
