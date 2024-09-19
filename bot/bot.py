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
legitimate_users_cache = set()
suspicious_users_cache = set()
spammers_cache = set()


async def start_command(update: Update, context: CallbackContext) -> None:
    # Обработка команды /start
    logger.debug(f"Handling /start command from {update.message.chat_id}")
    if update.message.chat_id > 0:
        await update.message.reply_text("This bot is for group use only.")
        logger.debug(f"Private message /start received from {update.message.chat_id}")
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
            logger.debug(f"Bot is not an admin in group {chat_id}.")
        elif chat_member_status not in ["administrator", "creator"]:
            # Проверка на то, что вызвавший команду пользователь является администратором
            await update.message.reply_text(
                "Only administrators can configure the bot."
            )
            logger.debug(
                f"Non-admin user {user_id} tried to configure the bot in group {chat_id}."
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
            logger.debug(f"Group {chat_id} is already configured.")
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
                    logger.debug(f"Group {chat_id} already exists in groups table.")
                try:
                    cursor.execute(
                        "INSERT INTO `group_settings` (group_id, parameter, value) VALUES (%s, %s, %s)",
                        (chat_id, "instructions", instructions_default_text),
                    )
                except mysql.connector.IntegrityError:
                    logger.debug(
                        f"Instructions for group {chat_id} already exist in group_settings table."
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
                logger.info(f"Group {chat_id} has been configured.")
            except mysql.connector.Error as err:
                logger.error(f"Database error while configuring group {chat_id}: {err}")
                await context.bot.send_message(
                    chat_id=chat_id, text="Error configuring bot for this group."
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                raise SystemExit("Database error.")


async def help_command(update: Update, context: CallbackContext) -> None:
    # Обработка команды /help
    logger.debug(f"Handling /help command from {update.message.chat_id}")
    if update.message.chat_id > 0:
        # Отправка сообщения о том, что бот работает только в группах
        await context.bot.send_message(
            chat_id=chat_id,
            text="This bot is for group use only. Add me to a group and use /start to configure me.",
        )
        await context.bot.delete_message(
            chat_id=chat_id, message_id=update.message.message_id
        )
        logger.debug(f"Private message /help received from {update.message.chat_id}")
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
            logger.debug(f"Help command received from configured group {chat_id}")
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="I am not set up correctly to work in this group. Use /start to configure me.",
            )
            await context.bot.delete_message(
                chat_id=chat_id, message_id=update.message.message_id
            )
            logger.debug(f"Help command received from unconfigured group {chat_id}")


async def set_command(update: Update, context: CallbackContext) -> None:
    # Обработка команды /set
    logger.debug(f"Handling /set command from {update.message.chat_id}")
    if update.message.chat_id > 0:
        await update.message.reply_text("This bot is for group use only.")
        logger.debug(f"Private message /set received from {update.message.chat_id}")
    else:
        chat_id = update.message.chat_id
        user_id = update.message.from_user.id
        chat_member = await context.bot.get_chat_member(chat_id, user_id)

        if chat_member.status not in ["administrator", "creator"]:
            await update.message.reply_text(
                "Only administrators can configure the bot."
            )
            logger.debug(
                f"Non-admin user {user_id} tried to configure the bot in group {chat_id}."
            )
        elif not is_group_configured(chat_id):
            await update.message.reply_text(
                "I am not set up correctly to work in this group. Use /start to configure me."
            )
            logger.debug(f"Group {chat_id} is not configured.")
        else:
            if len(context.args) < 2:
                await context.bot.send_message(
                    chat_id=chat_id, text="Usage: /set <parameter> <value>"
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                logger.debug(
                    f"Invalid /set command usage by {user_id} in group {chat_id}"
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
                    f"Invalid parameter {parameter} used by {user_id} in group {chat_id}"
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
                    f"Value for {parameter} exceeds length limit by {user_id} in group {chat_id}"
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
                logger.info(f"Set {parameter} to {value} in group {chat_id}")
            except mysql.connector.Error as err:
                logger.error(
                    f"Database error while setting parameter {parameter} in group {chat_id}: {err}"
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
    logger.debug(f"Handling /get command from {update.message.chat_id}")
    if update.message.chat_id > 0:
        await update.message.reply_text("This bot is for group use only.")
        logger.debug(f"Private message /get received from {update.message.chat_id}")
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
                f"Non-admin user {user_id} tried to read bot settings in group {chat_id}."
            )
        elif not is_group_configured(chat_id):
            await context.bot.send_message(
                chat_id=chat_id,
                text="I am not set up correctly to work in this group. Use /start to configure me.",
            )
            await context.bot.delete_message(
                chat_id=chat_id, message_id=update.message.message_id
            )
            logger.debug(f"Group {chat_id} is not configured.")
        else:
            if len(context.args) != 1:
                await context.bot.send_message(
                    chat_id=chat_id, text="Usage: /get <parameter>"
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                logger.debug(
                    f"Invalid /get command usage by {user_id} in group {chat_id}"
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
                    f"Retrieved {parameter} for group {chat_id} from cache: {value}"
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id, text=f"Parameter {parameter} not found."
                )
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.message.message_id
                )
                logger.debug(
                    f"Parameter {parameter} not found for group {chat_id} in cache"
                )


def check_and_create_tables():
    # Проверка и создание таблиц MySQL
    logger.debug("Checking and creating tables if necessary.")
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
        logger.debug("Tables checked and created if necessary.")
    except mysql.connector.Error as err:
        logger.critical(f"Database error: {err}. Terminating app.")
        raise SystemExit("Database error.")


def load_configured_groups():
    # Загрузка списка настроенных групп и их параметров из базы данных
    logger.debug("Loading configured groups and their parameters from the database.")
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

        logger.debug(f"Configured groups loaded ({len(configured_groups_cache)})")
    except mysql.connector.Error as err:
        logger.critical(f"Database error: {err}. Terminating app.")
        raise SystemExit("Database error.")


def is_group_configured(group_id):
    # Проверка наличия группы в кэше настроенных групп
    logger.debug(f"Checking if group {group_id} is configured.")
    is_configured = any(
        group["group_id"] == group_id for group in configured_groups_cache
    )
    logger.debug(f"Group {group_id} configured: {is_configured}")
    return is_configured


async def handle_message(update: Update, context: CallbackContext) -> None:
    if update.message:
        chat_id = update.message.chat_id
    else:
        logger.error("Received update without message: %s", update)
        return
    user_id = update.message.from_user.id
    logger.debug(f"Handling message from chat {chat_id}")

    if chat_id > 0:
        await update.message.reply_text("This bot is for group use only.")
        logger.debug(f"Private message {update.message.text} received from {chat_id}")
    elif is_group_configured(chat_id):
        if user_id in spammers_cache:
            await context.bot.kick_chat_member(chat_id, user_id)
            await update.message.delete()
            logger.info(
                f"Banned spammer {user_id} from group {chat_id} and deleted their message"
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
                logger.debug(f"Sending prompt to OpenAI: {prompt}")
                response = openai.chat.completions.create(
                    model=model_name, messages=prompt, response_format=response_format
                )
                logger.debug(
                    f"Received OpenAI response: {response.choices[0].message.content}"
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
                        logger.error(f"Database error while updating spammer status for user {user_id}: {err}")
                    suspicious_users_cache.remove(user_id)
                    logger.info(
                        f"SPAM message from {user_id} ({update.message.from_user.username}) in group {chat_id} ({update.message.chat.title}), user will be banned in all groups"
                    )
                else:
                    legitimate_users_cache.add(user_id)
                    suspicious_users_cache.remove(user_id)
                    logger.info(f"HAM message from {user_id}: {update.message.text}")
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
                            f"Database error while updating user {user_id}: {err}"
                        )
            except Exception as e:
                logger.error(f"Error querying OpenAI: {e}")
                # await update.message.reply_text("Error processing the message.")
        elif user_id in legitimate_users_cache:
            logger.info(
                f"Message from legitimate user {user_id} in group {chat_id} ignored"
            )
        else:
            logger.info(
                f"Message from unknown user {user_id} in group {chat_id} ignored"
            )
    else:
        await update.message.reply_text(
            "I am not set up correctly to work in this group. Use /start to configure me."
        )
        logger.debug(f"Incoming message from unknown group {chat_id}")


async def handle_my_chat_members(update: Update, context: CallbackContext) -> None:
    # Обработка добавления бота в группу либо получения статуса админа
    logger.debug(f"Handling my chat member update: {update}")
    chat_id = update.my_chat_member.chat.id
    member = update.my_chat_member.new_chat_member
    if member.user.id == context.bot.id:
        if isinstance(member, ChatMemberAdministrator):
            # Бот получил права администратора
            logger.debug(
                f"Bot received admin rights in group {chat_id} ({update.my_chat_member.chat.title}) by {update.my_chat_member.from_user.id} ({update.my_chat_member.from_user.username})"
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text="I have been promoted to an administrator. I am ready to protect your group from spam! Use /start to configure me.",
            )
        elif isinstance(member, ChatMemberMember):
            # Бот потерял права администратора
            logger.debug(
                f"Bot lost admin rights in group {chat_id} ({update.my_chat_member.chat.title})"
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text="I need administrator rights, I cannot protect your group from spam without them. Please promote me to an administrator.",
            )
        elif isinstance(member, ChatMemberLeft):
            # Бот был удален из группы
            logger.debug(
                f"Bot removed from group {chat_id} ({update.my_chat_member.chat.title})"
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
                        f"Group {chat_id} removed from configured groups cache and database."
                    )
                except mysql.connector.Error as err:
                    logger.error(
                        f"Database error while removing group {chat_id}: {err}"
                    )
                    raise SystemExit(
                        "Bot removed from group and database update failed."
                    )
                logger.info(
                    f"Bot has been removed from group {update.my_chat_member.chat.id} ({update.my_chat_member.chat.title})"
                )
            else:
                logger.debug(
                    f"Bot has been removed from group {chat_id} ({update.my_chat_member.chat.title}), which was not in configured groups cache."
                )
        else:
            # Бот добавлен в группу
            logger.debug(
                f"Bot added to group {chat_id} ({update.my_chat_member.chat.title}) by {update.my_chat_member.from_user.id} ({update.my_chat_member.from_user.username})"
            )
            try:
                chat_member = await context.bot.get_chat_member(
                    chat_id, update.my_chat_member.from_user.id
                )

                if chat_member.status not in ["administrator", "creator"]:
                    logger.debug(
                        f"Non-admin user {update.my_chat_member.from_user.id} tried to add the bot to group {chat_id}."
                    )
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="Only administrators can add the bot to the group. I will leave now.",
                    )
                    await context.bot.leave_chat(chat_id)
                    return
            except BadRequest as e:
                logger.error(f"BadRequest error while checking chat member status: {e}")

            await context.bot.send_message(
                chat_id=chat_id,
                text="Hello! I am your antispam guard bot. Thank you for adding me to the group. Make me an administrator to enable my features.",
            )


async def handle_other_chat_members(update: Update, context: CallbackContext) -> None:
    # Обработка добавления новых участников в группу
    logger.debug(f"Handling other chat members in group {update.chat_member.chat.id}")
    chat_id = update.chat_member.chat.id
    member = update.chat_member.new_chat_member

    if isinstance(member, ChatMemberMember):
        user_id = member.user.id
        if user_id in spammers_cache:
            await context.bot.kick_chat_member(chat_id, user_id)
            logger.info(f"Banned spammer {user_id} from group {chat_id}")
        else:
            try:
                conn = mysql.connector.connect(**db_config)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO user_entries (user_id, group_id, join_date) VALUES (%s, %s, NOW()) ON DUPLICATE KEY UPDATE join_date=NOW()",
                    (user_id, chat_id),
                )
                conn.commit()
                cursor.close()
                conn.close()
                if (
                    user_id not in suspicious_users_cache
                    and user_id not in legitimate_users_cache
                ):
                    suspicious_users_cache.add(user_id)
                    logger.debug(
                        f"New user {user_id} added to suspicious users cache for joining to group {chat_id} ({update.chat_member.chat.title})"
                    )
                else:
                    logger.info(
                        f"New member {user_id} added to group {chat_id} ({update.chat_member.chat.title})"
                    )
            except mysql.connector.Error as err:
                logger.error(
                    f"Database error while adding new member {user_id} to group {chat_id}: {err}"
                )


def load_user_caches():
    logger.debug("Loading user caches from the database.")
    global legitimate_users_cache, suspicious_users_cache, spammers_cache
    legitimate_users_cache = set()
    suspicious_users_cache = set()
    spammers_cache = set()
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Загрузка спамеров
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

        # Загрузка легитимных пользователей
        cursor.execute(
            """
            SELECT user_id FROM user_entries 
            WHERE seen_message = TRUE AND spammer = FALSE
        """
        )
        legitimate_users_cache = {row[0] for row in cursor.fetchall()}

        cursor.close()
        conn.close()
        logger.debug("User caches loaded successfully.")
    except mysql.connector.Error as err:
        logger.critical(f"Database error: {err}. Terminating app.")
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
