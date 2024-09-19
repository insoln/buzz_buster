import os
import atexit
import logging
from logging.handlers import RotatingFileHandler
import mysql.connector
from mysql.connector import errorcode
from telegram import Update, Bot
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackContext,
    MessageHandler,
    filters,
    ChatMemberHandler,
)
from openai import OpenAI
import json
import asyncio
from telegram import ChatMemberAdministrator, ChatMemberMember, ChatMemberLeft
import aiohttp

# Загрузка переменных окружения
telegram_api_key = os.getenv("TELEGRAM_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")
model_name = os.getenv("MODEL_NAME")
instructions_length_limit = os.getenv("INSTRUCTIONS_LENGTH_LIMIT")
instructions_default_text = os.getenv("INSTRUCTIONS_DEFAULT_TEXT")
admin_telegram_id = os.getenv("ADMIN_TELEGRAM_ID")
statuschat_telegram_id = os.getenv("STATUSCHAT_TELEGRAM_ID")

# Уровни логирования из переменных окружения
file_log_level = os.getenv("FILE_LOG_LEVEL", "INFO")
console_log_level = os.getenv("CONSOLE_LOG_LEVEL", "INFO")
telegram_log_level = os.getenv("TELEGRAM_LOG_LEVEL", "WARNING")

# Настройка OpenAI
openai = OpenAI(api_key=openai_api_key)

# Настройка базы данных MySQL
db_config = {
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": "db",
    "database": os.getenv("DB_NAME"),
}

# Создаем экземпляр бота для отправки уведомлений
bot = Bot(token=telegram_api_key)

# Настройка логирования
log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

# Логирование в файл
file_handler = RotatingFileHandler(
    "logs/bot.log", maxBytes=5 * 1024 * 1024, backupCount=2
)
file_handler.setLevel(getattr(logging, file_log_level.upper(), logging.INFO))
file_handler.setFormatter(log_formatter)

# Логирование в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(getattr(logging, console_log_level.upper(), logging.INFO))
console_handler.setFormatter(log_formatter)

# Простой форматтер для Telegram
simple_formatter = logging.Formatter("%(message)s")


# Логирование в Telegram (для уровня WARNING и выше)
class TelegramHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        if statuschat_telegram_id:
            try:
                asyncio.run(self.send_message_async(log_entry))
            except RuntimeError as e:
                if "This event loop is already running" in str(e):
                    loop = asyncio.get_event_loop()
                    loop.create_task(self.send_message_async(log_entry))
                else:
                    logger.removeHandler(telegram_handler)
                    logger.error(f"Error sending log message to Telegram: {e}")
                    logger.addHandler(telegram_handler)

    async def send_message_async(self, log_entry):
        await bot.send_message(chat_id=statuschat_telegram_id, text=log_entry)


telegram_handler = TelegramHandler()
telegram_handler.setLevel(getattr(logging, telegram_log_level.upper(), logging.WARNING))
telegram_handler.setFormatter(simple_formatter)

# Настройка основного логгера
logger = logging.getLogger("telegram_bot")
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
logger.addHandler(telegram_handler)

# Глобальная переменная для кэширования списка настроенных групп
configured_groups_cache = []

# Глобальные переменные для кэширования пользователей
suspicious_users_cache = set()
spammers_cache = set()

def display_user(user):
    # Отображение информации о пользователе в виде строки
    result = f"#{user.id} {user.first_name or ''} {user.last_name or ''}".strip()
    if user.username:
        result = f"{result} (@{user.username})".strip()
    return result

def display_chat(chat):
    # Отображение информации о чате в виде строки
    result = f"#{chat.id} {chat.title or ''}".strip()
    if chat.username:
        result = f"{result} (@{chat.username})".strip()
    return result

async def start_command(update: Update, context: CallbackContext) -> None:
    # Обработка команды /start
    logger.debug(
        f"Handling /start command from user {display_user(update.message.from_user)} in chat {display_chat(update.message.chat)}"
    )
    if update.message.chat_id > 0:
        await update.message.reply_text("This bot is for group use only.")
        logger.debug(
            f"Private message /start received from user {display_user(update.message.from_user)} in chat {display_chat(update.message.chat)}"
        )
    else:
        chat_id = update.message.chat_id
        user_id = update.message.from_user.id
        try:
            chat_member_status = (
                await context.bot.get_chat_member(chat_id, user_id)
            ).status
        except BadRequest as e:
            chat_member_status = None
        try:
            bot_member_status = (
                await context.bot.get_chat_member(chat_id, context.bot.id)
            ).status
        except BadRequest as e:
            bot_member_status = None

        if not bot_member_status in ["administrator", "creator"]:
            # Проверка на то, что бот является администратором
            await update.message.reply_text(
                "I need to be an administrator in this group to be configured."
            )
            logger.debug(f"Bot is not an admin in group {chat_id} ({update.message.chat.title}). User {user_id} ({update.message.from_user.username}) tried to configure the bot.")
        elif chat_member_status not in ["administrator", "creator"]:
            # Проверка на то, что вызвавший команду пользователь является администратором
            await update.message.reply_text(
                "Only administrators can configure the bot."
            )
            logger.debug(
                f"Non-admin user {display_user(update.message.from_user)} tried to configure the bot in group {display_chat(update.message.chat)}."
            )

        elif is_group_configured(chat_id):
            # Проверка на то, что группа уже настроена
            await context.bot.send_message(
                chat_id=chat_id,
                text="Bot is already configured for this group. Use /help to see available commands.",
            )
            await context.bot.delete_message(
                chat_id=chat_id, message_id=update.message.message_id
            )
            logger.debug(f"User {display_user(update.message.from_user)} attempted to configure group {display_chat(update.message.chat)}, but it is already configured.")
        else:
            # Настройка бота для группы
            try:
                conn = mysql.connector.connect(**db_config)
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "INSERT INTO `groups` (group_id) VALUES (%s)", (chat_id,)
                    )
                except mysql.connector.IntegrityError:
                    logger.debug(f"Group {chat_id} ({update.message.chat.title}) already exists in groups table, attempted by user {user_id} ({update.message.from_user.username}).")
                try:
                    cursor.execute(
                        "INSERT INTO `group_settings` (group_id, parameter, value) VALUES (%s, %s, %s)",
                        (chat_id, "instructions", instructions_default_text),
                    )
                except mysql.connector.IntegrityError:
                    logger.debug(
                        f"Instructions for group {display_chat(update.message.chat)} already exist in group_settings table, attempted by user {display_user(update.message.from_user)}."
                    )
                conn.commit()
                cursor.close()
                conn.close()
                configured_groups_cache.append(
                    {
                        "group_id": chat_id,
                        "settings": {"instructions": instructions_default_text},
                    }
                )
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Bot has been configured for this group. Use /help to see available commands.",
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                logger.info(f"Group {display_chat(update.message.chat)} has been configured by user {display_user(update.message.from_user)}.")
            except mysql.connector.Error as err:
                logger.error(f"Database error while configuring group {display_chat(update.message.chat)} by user {display_user(update.message.from_user)}: {err}")
                await context.bot.send_message(
                    chat_id=chat_id, text="Error configuring bot for this group."
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                raise SystemExit("Database error.")


async def help_command(update: Update, context: CallbackContext) -> None:
    # Обработка команды /help
    logger.debug(
        f"Handling /help command from user {display_user(update.message.from_user)} in chat {display_chat(update.message.chat)}"
    )
    if update.message.chat_id > 0:
        # Отправка сообщения о том, что бот работает только в группах
        await context.bot.send_message(
            chat_id=chat_id,
            text="This bot is for group use only. Add me to a group and use /start to configure me.",
        )
        await context.bot.delete_message(
            chat_id=chat_id, message_id=update.message.message_id
        )
        logger.debug(
            f"Private message /help received from user {display_user(update.message.from_user)}"
        )
    else:
        # Отправка сообщения со списком доступных команд
        chat_id = update.message.chat_id
        if is_group_configured(chat_id):
            await context.bot.send_message(
                chat_id=chat_id,
                text="""Available commands:
                /start - Configure the bot
                /help - Show this help message
                /set <parameter> <value> - Set a parameter
                /get <parameter> - Get a parameter
                
                Available parameters:
                - instructions: what AI should consider spam""",
            )
            await context.bot.delete_message(
                chat_id=chat_id, message_id=update.message.message_id
            )
            logger.debug(f"Help command received from configured group {display_chat(update.message.chat)} by user {display_user(update.message.from_user)}")
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="I am not set up correctly to work in this group. Use /start to configure me.",
            )
            await context.bot.delete_message(
                chat_id=chat_id, message_id=update.message.message_id
            )
            logger.debug(
                f"Help command received from unconfigured group {display_chat(update.message.chat)} by user {display_user(update.message.from_user)}"
            )


async def set_command(update: Update, context: CallbackContext) -> None:
    # Обработка команды /set
    logger.debug(
        f"Handling /set command from user {display_user(update.message.from_user)} in chat {display_chat(update.message.chat)}"
    )
    if update.message.chat_id > 0:
        await update.message.reply_text("This bot is for group use only.")
        logger.debug(
            f"Private message /set received from user {display_user(update.message.from_user)}"
        )
    else:
        chat_id = update.message.chat_id
        user_id = update.message.from_user.id
        chat_member = await context.bot.get_chat_member(chat_id, user_id)

        if chat_member.status not in ["administrator", "creator"]:
            await update.message.reply_text(
                "Only administrators can configure the bot."
            )
            logger.debug(
                f"Non-admin user {display_user(update.message.from_user)} tried to configure the bot in group {display_chat(update.message.chat)}."
            )
        elif not is_group_configured(chat_id):
            await update.message.reply_text(
                "I am not set up correctly to work in this group. Use /start to configure me."
            )
            logger.debug(f"User {display_user(update.message.from_user)} tried to set a parameter, but group {display_chat(update.message.chat)} is not configured.")
        else:
            if len(context.args) < 2:
                await context.bot.send_message(
                    chat_id=chat_id, text="Usage: /set <parameter> <value>"
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                logger.debug(
                    f"Invalid /set command usage by user {display_user(update.message.from_user)} in group {display_chat(update.message.chat)}. Expected format: /set <parameter> <value>"
                )
                return

            parameter = context.args[0]
            value = " ".join(context.args[1:])

            allowed_parameters = ["instructions"]
            if parameter not in allowed_parameters:
                await context.bot.send_message(
                    chat_id=chat_id, text=f"Invalid parameter: {parameter}"
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                logger.debug(
                    f"User {display_user(update.message.from_user)} in group {display_chat(update.message.chat)} attempted to set an invalid parameter: {parameter}"
                )
                return

            if parameter == "instructions" and len(value) > int(
                instructions_length_limit
            ):
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"The value for {parameter} exceeds the length limit of {instructions_length_limit} characters.",
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                logger.debug(
                    f"User {display_user(update.message.from_user)} in group {display_chat(update.message.chat)} attempted to set {parameter} to a value exceeding the length limit of {instructions_length_limit} characters."
                )
                return

            try:
                conn = mysql.connector.connect(**db_config)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO group_settings (group_id, parameter, value) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE value=%s",
                    (chat_id, parameter, value, value),
                )
                conn.commit()
                cursor.close()
                conn.close()

                # Update the cache
                group = next(
                    (
                        group
                        for group in configured_groups_cache
                        if group["group_id"] == chat_id
                    ),
                    None,
                )
                if group:
                    group["settings"][parameter] = value
                else:
                    configured_groups_cache.append(
                        {"group_id": chat_id, "settings": {parameter: value}}
                    )

                await context.bot.send_message(
                    chat_id=chat_id, text=f"Successfully set {parameter} to {value}"
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                logger.info(f"User {display_user(update.message.from_user)} set parameter '{parameter}' to '{value}' in group {display_chat(update.message.chat)}")
            except mysql.connector.Error as err:
                logger.error(
                    f"Database error while setting parameter '{parameter}' to '{value}' in group {display_chat(update.message.chat)} by user {display_user(update.message.from_user)}: {err}"
                )
                await context.bot.send_message(
                    chat_id=chat_id, text="Error setting parameter."
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                raise SystemExit("Database error.")


async def get_command(update: Update, context: CallbackContext) -> None:
    # Обработка команды /get
    if update.message.chat_id > 0:
        await update.message.reply_text("This bot is for group use only.")
        logger.debug(
            f"Private message /get received from user {display_user(update.message.from_user)}"
        )
    else:
        chat_id = update.message.chat_id
        user_id = update.message.from_user.id
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        if chat_member.status not in ["administrator", "creator"]:
            await context.bot.send_message(
                chat_id=chat_id, text="Only administrators can configure the bot."
            )
            await context.bot.delete_message(
                chat_id=chat_id, message_id=update.message.message_id
            )
            logger.debug(
                f"Non-admin user {display_user(update.message.from_user)} tried to read bot settings in group {display_chat(update.message.chat)}."
            )
        elif not is_group_configured(chat_id):
            await context.bot.send_message(
                chat_id=chat_id,
                text="I am not set up correctly to work in this group. Use /start to configure me.",
            )
            await context.bot.delete_message(
                chat_id=chat_id, message_id=update.message.message_id
            )
            logger.debug(
                f"Group {display_chat(update.message.chat)} is not configured. User {display_user(update.message.from_user)} tried to get parameter {context.args[0]}."
            )
        else:
            if len(context.args) != 1:
                await context.bot.send_message(
                    chat_id=chat_id, text="Usage: /get <parameter>"
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                logger.debug(
                    f"Invalid /get command usage by user {display_user(update.message.from_user)} in group {display_chat(update.message.chat)}. Expected format: /get <parameter>"
                )
                return

            parameter = context.args[0]

            group = next(
                (
                    group
                    for group in configured_groups_cache
                    if group["group_id"] == chat_id
                ),
                None,
            )
            if group and parameter in group["settings"]:
                value = group["settings"][parameter]
                await context.bot.send_message(
                    chat_id=chat_id, text=f"{parameter}: {value}"
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                logger.debug(
                    f"Retrieved parameter '{parameter}' with value '{value}' for group {display_chat(update.message.chat)} from cache, requested by user {display_user(update.message.from_user)}"
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id, text=f"Parameter {parameter} not found."
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                logger.debug(
                    f"Parameter '{parameter}' not found for group {display_chat(update.message.chat)} in cache, requested by user {display_user(update.message.from_user)}"
                )


def check_and_create_tables():
    # Проверка и создание таблиц MySQL
    logger.debug("Checking and creating necessary tables in the database for group and user settings.")
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS `groups` (
            id INT AUTO_INCREMENT PRIMARY KEY,
            group_id BIGINT NOT NULL UNIQUE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS group_settings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            group_id BIGINT NOT NULL,
            parameter VARCHAR(255) NOT NULL,
            value TEXT,
            UNIQUE KEY unique_group_parameter (group_id, parameter)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_entries (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT NOT NULL,
            group_id BIGINT NOT NULL,
            join_date DATETIME NOT NULL,
            seen_message BOOLEAN DEFAULT FALSE,
            spammer BOOLEAN DEFAULT FALSE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """
        )
        conn.commit()
        cursor.close()
        conn.close()
        logger.debug("Checked and created necessary tables in the database for group and user settings if they did not already exist.")
    except mysql.connector.Error as err:
        logger.critical(f"Database error while checking and creating tables: {err}. Terminating application.")
        raise SystemExit("Database error.")


def load_configured_groups():
    # Загрузка списка настроенных групп и их параметров из базы данных
    logger.debug("Loading configured groups and their parameters from the database, including group IDs and their respective settings.")
    global configured_groups_cache
    configured_groups_cache = []
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Загрузка настроенных групп и их параметров
        cursor.execute(
            """
            SELECT g.group_id, s.parameter, s.value 
            FROM `groups` g 
            LEFT JOIN group_settings s ON g.group_id = s.group_id
        """
        )

        group_dict = {}
        for group_id, parameter, value in cursor.fetchall():
            if group_id not in group_dict:
                group_dict[group_id] = {"group_id": group_id, "settings": {}}
            if parameter and value:
                group_dict[group_id]["settings"][parameter] = value

        configured_groups_cache = list(group_dict.values())

        cursor.close()
        conn.close()

        logger.debug(f"Loaded {len(configured_groups_cache)} configured groups from the database.")
    except mysql.connector.Error as err:
        logger.critical(f"Database error while loading configured groups and their parameters: {err}. Terminating application.")
        raise SystemExit("Database error.")


def is_group_configured(group_id):
    # Проверка наличия группы в кэше настроенных групп
    group = next((group for group in configured_groups_cache if group["group_id"] == group_id), None)
    group_name = group['settings'].get('group_name', 'Unknown Group') if group else 'Unknown Group'
    is_configured = group is not None
    return is_configured


async def handle_message(update: Update, context: CallbackContext) -> None:
    if update.message:
        chat_id = update.message.chat_id
    else:
        logger.debug("Received update without message")
        return
    user_id = update.message.from_user.id
    logger.debug(
        f"Handling message from user {display_user(update.message.from_user)} in chat {display_chat(update.message.chat)} with text: {update.message.text}"
    )

    if chat_id > 0:
        await update.message.reply_text("This bot is for group use only.")
        logger.debug(
            f"Private message received from user {display_user(update.message.from_user)}"
        )
    elif is_group_configured(chat_id):
        if user_id in spammers_cache:
            await context.bot.kick_chat_member(chat_id, user_id)
            await update.message.delete()
            logger.info(
                f"Banned spammer {display_user(update.message.from_user)} from group {display_chat(update.message.chat)} and deleted their message: {update.message.text}"
            )
            return

        elif user_id in suspicious_users_cache:
            # Process the message with OpenAI
            group = next(
                (
                    group
                    for group in configured_groups_cache
                    if group["group_id"] == chat_id
                ),
                None,
            )

            prompt = [
                {
                    "role": "system",
                    "content": f"Является ли спамом сообщение от пользователя? Важные признаки спам-сообщений: {group['settings'].get('instructions', instructions_default_text)}",
                },
                {
                    "role": "user",
                    "content": f"Текст сообщения от пользователя: {update.message.text}",
                },
            ]

            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "boolean",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"result": {"type": "boolean"}},
                        "required": ["result"],
                        "additionalProperties": False,
                    },
                },
            }

            try:
                logger.debug(
                    f"Sending prompt to OpenAI for user {display_user(update.message.from_user)} in group {display_chat(update.message.chat)}: {prompt}"
                )
                response = openai.chat.completions.create(
                    model=model_name, messages=prompt, response_format=response_format
                )
                logger.debug(
                    f"Received OpenAI response for message from user {display_user(update.message.from_user)} in group {display_chat(update.message.chat)}: {response.choices[0].message.content}"
                )

                is_spam = json.loads(response.choices[0].message.content)["result"]

                if is_spam:
                    await context.bot.ban_chat_member(chat_id, user_id)
                    await update.message.delete()
                    spammers_cache.add(user_id)
                    try:
                        conn = mysql.connector.connect(**db_config)
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            INSERT INTO `user_entries` (user_id, group_id, join_date, seen_message, spammer)
                            VALUES (%s, %s, NOW(), TRUE, TRUE)
                            ON DUPLICATE KEY UPDATE spammer = TRUE, group_id = %s
                            """,
                            (user_id, chat_id, chat_id),
                        )
                        conn.commit()
                        cursor.close()
                        conn.close()
                    except mysql.connector.Error as err:
                        logger.error(
                            f"Database error while updating spammer status for user {display_user(update.message.from_user)} in group {display_chat(update.message.chat)}: {err}"
                        )
                    suspicious_users_cache.remove(user_id)
                    logger.info(
                        f"Detected SPAM message from user {display_user(update.message.from_user)} in group {display_chat(update.message.chat)}. The user will be banned in all groups."
                    )
                else:
                    suspicious_users_cache.remove(user_id)
                    logger.info(
                        f"Message from user {display_user(update.message.from_user)} in group {display_chat(update.message.chat)} was classified as legitimate."
                    )
                    try:
                        conn = mysql.connector.connect(**db_config)
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE user_entries SET seen_message = TRUE, spammer = FALSE WHERE user_id = %s",
                            (user_id,),
                        )
                        conn.commit()
                        cursor.close()
                        conn.close()
                    except mysql.connector.Error as err:
                        logger.error(
                            f"Database error while updating user {display_user(update.message.from_user)} in group {display_chat(update.message.chat)}: {err}"
                        )
            except Exception as e:
                logger.error(
                    f"Error querying OpenAI for message from user {display_user(update.message.from_user)} in group {display_chat(update.message.chat)}: {e}"
                )
                # await update.message.reply_text("Error processing the message.")
        else:
            logger.debug(
                f"Message from user {display_user(update.message.from_user)} in group {display_chat(update.message.chat)} ignored as the user is not in the suspicious users cache."
            )
    else:
        await update.message.reply_text(
            "I am not set up correctly to work in this group. Use /start to configure me."
        )
        logger.debug(
            f"Message ignored from unconfigured group {display_chat(update.message.chat)} by user {display_user(update.message.from_user)}."
        )


async def handle_my_chat_members(update: Update, context: CallbackContext) -> None:
    # Обработка добавления бота в группу либо получения статуса админа
    logger.debug(
        f"Handling my group membership update in group {display_chat(update.my_chat_member.chat)}"
    )
    chat_id = update.my_chat_member.chat.id
    member = update.my_chat_member.new_chat_member
    if member.user.id == context.bot.id:
        if isinstance(member, ChatMemberAdministrator):
            # Бот получил права администратора
            logger.debug(
                f"Bot has been promoted to administrator in group {display_chat(update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}."
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text="I have been promoted to an administrator. I am ready to protect your group from spam! Use /start to configure me.",
            )
        elif isinstance(member, ChatMemberMember):
            # Бот потерял права администратора
            logger.debug(
                f"Bot lost admin rights in group {display_chat(update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}."
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text="I need administrator rights, I cannot protect your group from spam without them. Please promote me to an administrator.",
            )
        elif isinstance(member, ChatMemberLeft):
            # Бот был удален из группы
            logger.debug(
                f"Bot has been removed from group {display_chat(update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}."
            )
            group = next(
                (
                    group
                    for group in configured_groups_cache
                    if group["group_id"] == chat_id
                ),
                None,
            )
            if group:
                try:
                    conn = mysql.connector.connect(**db_config)
                    cursor = conn.cursor()
                    cursor.execute(
                        "DELETE FROM `groups` WHERE group_id = %s", (chat_id,)
                    )
                    cursor.execute(
                        "DELETE FROM `group_settings` WHERE group_id = %s", (chat_id,)
                    )
                    conn.commit()
                    cursor.close()
                    conn.close()
                    configured_groups_cache.remove(group)
                    logger.info(
                        f"Group {chat_id} ({update.my_chat_member.chat.title}) removed from configured groups cache and database by user {update.my_chat_member.from_user.id} ({update.my_chat_member.from_user.username})."
                    )
                except mysql.connector.Error as err:
                    logger.error(
                        f"Database error while removing group {display_chat(update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}: {err}"
                    )
                    raise SystemExit(
                        "Bot removed from group and database update failed."
                    )
                logger.info(
                    f"Bot has been removed from group {display_chat(update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}"
                )
            else:
                logger.debug(
                    f"Bot has been removed from group {display_chat(update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}, which was not in configured groups cache."
                )
        else:
            # Бот добавлен в группу
            logger.debug(
                f"Bot added to group {display_chat(update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}."
            )
            try:
                chat_member = await context.bot.get_chat_member(
                    chat_id, update.my_chat_member.from_user.id
                )

                if chat_member.status not in ["administrator", "creator"]:
                    logger.debug(
                        f"Non-admin user {display_user(update.my_chat_member.from_user)} tried to add the bot to group {display_chat(update.my_chat_member.chat)}."
                    )
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="Only administrators can add the bot to the group. I will leave now.",
                    )
                    await context.bot.leave_chat(chat_id)
                    return
            except BadRequest as e:
                logger.error(
                    f"BadRequest error while checking chat member status in group {display_chat(update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}: {e}"
                )

            await context.bot.send_message(
                chat_id=chat_id,
                text="Hello! I am your antispam guard bot. Thank you for adding me to the group. Make me an administrator to enable my features.",
            )

async def check_cas_ban(user_id) -> bool:
    # Проверка пользователя на наличие бана в Combot Anti-Spam System
    url = f"https://api.cas.chat/check?user_id={user_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("ok", False)
            return False

async def handle_other_chat_members(update: Update, context: CallbackContext) -> None:
    # Обработка добавления новых участников в группу
    event_type = type(update.chat_member.new_chat_member).__name__
    target_user = update.chat_member.new_chat_member.user
    logger.debug(
        f"Handling membership event '{event_type}' in group {display_chat(update.chat_member.chat)} for user {display_user(update.chat_member.from_user)} targeting user {display_user(target_user)}"
    )
    chat_id = update.chat_member.chat.id
    member = update.chat_member.new_chat_member

    if isinstance(member, ChatMemberMember):
        # Новый участник присоединился к группе
        user_id = member.user.id
        if user_id in spammers_cache:
            # известный спамер
            await context.bot.kick_chat_member(chat_id, user_id)
            logger.info(
                f"Banned spammer {display_user(member.user)} from group {display_chat(update.chat_member.chat)}"
            )
        else:
            # записываем подозрительным
            try:
                # указываем, что видели юзера в именно этой группе
                conn = mysql.connector.connect(**db_config)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO user_entries (user_id, group_id, join_date) VALUES (%s, %s, NOW()) ON DUPLICATE KEY UPDATE join_date=NOW()",
                    (user_id, chat_id),
                )
                conn.commit()
                cursor.close()
                conn.close()
                
                # добавляем в кэш
                suspicious_users_cache.add(user_id)
                logger.debug(
                    f"User {display_user(member.user)} added to suspicious users cache for joining chat {display_chat(update.chat_member.chat)}"
                )
            except mysql.connector.Error as err:
                logger.error(
                    f"Database error while adding new member {display_user(member.user)} to group {display_chat(update.chat_member.chat)}: {err}"
                )
                
            # проверяем на бан в CAS
            is_cas_banned = await check_cas_ban(user_id)
            if is_cas_banned:
                spammers_cache.add(user_id)
                await context.bot.kick_chat_member(chat_id, user_id)
                try:
                    conn = mysql.connector.connect(**db_config)
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE user_entries SET spammer = TRUE WHERE user_id = %s",
                        (user_id,),
                    )
                    conn.commit()
                    cursor.close()
                    conn.close()
                    logger.info(
                        f"User {display_user(member.user)} is banned by CAS and has been banned from group {display_chat(update.chat_member.chat)}"
                    )
                except mysql.connector.Error as err:
                    logger.error(
                        f"Database error while updating CAS banned user {display_user(member.user)} in group {display_chat(update.chat_member.chat)}: {err}"
                    )


def load_user_caches():
    logger.debug("Loading user caches from the database.")
    global suspicious_users_cache, spammers_cache
    suspicious_users_cache = set()
    spammers_cache = set()
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Загрузка спамеров за последние 30 дней (больше незачем, телега такого спамера сама забанит)
        cursor.execute(
            """
            SELECT user_id FROM user_entries 
            WHERE spammer = TRUE AND join_date >= NOW() - INTERVAL 30 DAY
        """
        )
        spammers_cache = {row[0] for row in cursor.fetchall()}

        # Загрузка подозрительных пользователей
        cursor.execute(
            """
            SELECT user_id FROM user_entries 
            WHERE seen_message = FALSE
        """
        )
        suspicious_users_cache = {row[0] for row in cursor.fetchall()}

        cursor.close()
        conn.close()
        logger.debug(
            f"User caches loaded successfully. Suspicious users: {len(suspicious_users_cache)}, Spammers: {len(spammers_cache)}"
        )
    except mysql.connector.Error as err:
        logger.critical(f"Database error while loading user caches: {err}. Terminating application.")
        raise SystemExit("Database error.")


def main():
    logger.debug("Starting bot.")
    # Проверка наличия нужного ключа
    if not telegram_api_key:
        logger.critical(
            "TELEGRAM_API_KEY environment variable not set. Terminating app."
        )
        raise SystemExit("TELEGRAM_API_KEY environment variable not set")

    # Проверка валидности ключа
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bot.get_me())
        logger.debug("Telegram API key is valid.")
    except Exception as e:
        # Temporarily disable Telegram logging
        logger.removeHandler(telegram_handler)
        logger.critical(f"Invalid TELEGRAM_API_KEY? {e}")
        raise SystemExit("Invalid TELEGRAM_API_KEY")

    # Проверка и создание таблиц
    check_and_create_tables()

    # Загрузка списка разрешенных групп
    load_configured_groups()

    # Загрузка кэшей пользователей
    load_user_caches()

    # Создание и запуск диспетчера
    dispatcher = Application.builder().token(telegram_api_key).build()
    # Регистрируем обработчик команд
    dispatcher.add_handler(CommandHandler("start", start_command), group=1)
    dispatcher.add_handler(CommandHandler("help", help_command), group=1)
    dispatcher.add_handler(CommandHandler("set", set_command), group=1)
    dispatcher.add_handler(CommandHandler("get", get_command), group=1)
    # Регистрируем обработчик текстовых сообщений
    dispatcher.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message), group=1
    )
    # Регистрируем обработчик изменения членства себя в группе
    dispatcher.add_handler(
        ChatMemberHandler(handle_my_chat_members, ChatMemberHandler.MY_CHAT_MEMBER),
        group=2,
    )
    # Регистрируем обработчик изменения членства других в группе
    dispatcher.add_handler(
        ChatMemberHandler(handle_other_chat_members, ChatMemberHandler.CHAT_MEMBER),
        group=2,
    )

    # Регистрируем обработчик всех входящих событий для дебага
    async def log_event(update: Update, context: CallbackContext) -> None:
        logger.debug(f"Received event: {update}")

    dispatcher.add_handler(MessageHandler(filters.ALL, log_event), group=0)

    # Регистрация функции завершения работы
    atexit.register(lambda: logger.warning("Bot is shutting down."))

    # Запускаем бота
    try:
        dispatcher.run_polling(allowed_updates=Update.ALL_TYPES)
        logger.warning("Bot started.")
        # dispatcher.idle()
    except RuntimeError as e:
        # при graceful shutdown происходит какая-то фигня, но я недостаточно понимаю Asyncio, чтобы понять, что именно
        if "Event loop is closed" in str(e):
            logger.error("Event loop is closed. Attempting to restart the event loop.")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            dispatcher.run_polling(allowed_updates=Update.ALL_TYPES)
        else:
            logger.error(f"RuntimeError in bot polling: {e}")
            raise SystemExit("Bot polling failed. Shutting down.")
    except Exception as e:
        logger.error(f"Error in bot polling: {e}")
        raise SystemExit("Bot polling failed. Shutting down.")


if __name__ == "__main__":
    main()
