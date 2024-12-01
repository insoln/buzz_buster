import asyncio
import atexit
import json
import logging
import os
from logging.handlers import RotatingFileHandler

import aiohttp
import mysql.connector
from mysql.connector import errorcode
import openai
from telegram import (
    Bot,
    Chat,
    ChatMember,
    ChatMemberAdministrator,
    ChatMemberLeft,
    ChatMemberBanned,
    ChatMemberMember,
    Update,
    User,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackContext,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

# Загрузка переменных окружения и настройка констант
TELEGRAM_API_KEY = os.getenv("TELEGRAM_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
INSTRUCTIONS_LENGTH_LIMIT = int(os.getenv("INSTRUCTIONS_LENGTH_LIMIT", "1024"))
INSTRUCTIONS_DEFAULT_TEXT = os.getenv(
    "INSTRUCTIONS_DEFAULT_TEXT", "Любые спам-признаки."
)
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")
STATUSCHAT_TELEGRAM_ID = os.getenv("STATUSCHAT_TELEGRAM_ID")

# Настройка уровней логирования
FILE_LOG_LEVEL = os.getenv("FILE_LOG_LEVEL", "INFO").upper()
CONSOLE_LOG_LEVEL = os.getenv("CONSOLE_LOG_LEVEL", "INFO").upper()
TELEGRAM_LOG_LEVEL = os.getenv("TELEGRAM_LOG_LEVEL", "WARNING").upper()

# Настройка OpenAI
openai.api_key = OPENAI_API_KEY

# Настройка базы данных MySQL
DB_CONFIG = {
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "db"),
    "database": os.getenv("DB_NAME"),
}

# Создаем экземпляр бота для отправки уведомлений
bot = Bot(token=TELEGRAM_API_KEY)

# Настройка логирования
logger = logging.getLogger("telegram_bot")
logger.setLevel(logging.DEBUG)

# Форматтеры для логирования
log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
simple_formatter = logging.Formatter("%(message)s")

# Логирование в файл
file_handler = RotatingFileHandler(
    "app/buzzbuster.log", maxBytes=5 * 1024 * 1024, backupCount=2
)
file_handler.setLevel(getattr(logging, FILE_LOG_LEVEL, logging.INFO))
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

# Логирование в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(getattr(logging, CONSOLE_LOG_LEVEL, logging.INFO))
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)


class TelegramLogHandler(logging.Handler):
    """Класс для отправки логов в Telegram."""

    def __init__(self, bot_instance: Bot, chat_id: int):
        super().__init__()
        self.bot = bot_instance
        self.chat_id = int(chat_id)

    def emit(self, record):
        log_entry = self.format(record)
        try:
            asyncio.create_task(self.bot.send_message(chat_id=self.chat_id, text=log_entry))
        except Exception as e:
            print(f"Failed to send log via Telegram: {e}")


# Логирование в Telegram
if STATUSCHAT_TELEGRAM_ID:
    telegram_handler = TelegramLogHandler(bot, STATUSCHAT_TELEGRAM_ID)
    telegram_handler.setLevel(getattr(logging, TELEGRAM_LOG_LEVEL, logging.WARNING))
    telegram_handler.setFormatter(simple_formatter)
    logger.addHandler(telegram_handler)

# Глобальные переменные для кэширования данных
configured_groups_cache = []
suspicious_users_cache = set()
spammers_cache = set()


def display_user(user: User) -> str:
    """Отображение информации о пользователе в виде строки."""
    result = f"#{user.id} {user.first_name or ''} {user.last_name or ''}".strip()
    if user.username:
        result = f"{result} (@{user.username})".strip()
    return result


def display_chat(chat: Chat) -> str:
    """Отображение информации о чате в виде строки."""
    result = f"#{chat.id} {chat.title or ''}".strip()
    if chat.username:
        result = f"{result} (@{chat.username})".strip()
    return result


def is_group_configured(group_id: int) -> bool:
    """Проверка наличия группы в кэше настроенных групп."""
    return any(group["group_id"] == group_id for group in configured_groups_cache)


async def start_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /start."""
    logger.debug(
        f"Handling /start command from user {display_user(update.effective_user)} in chat {display_chat(update.effective_chat)}"
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
        logger.exception(f"Failed to get chat member status for user {user_id} in chat {chat_id}: {e}")
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
        cursor.execute("INSERT INTO `groups` (group_id) VALUES (%s)", (chat_id,))
        cursor.execute(
            "INSERT INTO `group_settings` (group_id, parameter, value) VALUES (%s, %s, %s)",
            (chat_id, "instructions", INSTRUCTIONS_DEFAULT_TEXT),
        )
        conn.commit()
    except mysql.connector.Error as err:
        logger.exception(f"Database error when configuring group {chat_id}: {err}")
        await update.message.reply_text("Ошибка настройки бота для этой группы.")
        return
    finally:
        cursor.close()
        conn.close()

    # Обновление кэша настроенных групп
    configured_groups_cache.append(
        {"group_id": chat_id, "settings": {"instructions": INSTRUCTIONS_DEFAULT_TEXT}}
    )

    await update.message.reply_text(
        "Бот настроен для этой группы. Используйте /help, чтобы увидеть доступные команды."
    )
    logger.info(f"Group {chat_id} has been configured.")


async def help_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /help."""
    logger.debug(
        f"Handling /help command from user {display_user(update.effective_user)} in chat {display_chat(update.effective_chat)}"
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
        f"Handling /set command from user {display_user(update.effective_user)} in chat {display_chat(update.effective_chat)}"
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
            f"Значение для {parameter} превышает лимит длины в {INSTRUCTIONS_LENGTH_LIMIT} символов."
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
        logger.exception(f"Database error when setting parameter {parameter}: {err}")
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
        f"Handling /get command from user {display_user(update.effective_user)} in chat {display_chat(update.effective_chat)}"
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
                logger.debug(f"Parameter {parameter} retrieved with value {value}.")
            else:
                await update.message.reply_text(f"Параметр {parameter} не найден.")
                logger.debug(f"Parameter {parameter} not found.")
            break
    else:
        await update.message.reply_text("Ошибка при получении параметра.")
        logger.debug(f"Group {chat_id} not found in cache.")


def check_and_create_tables():
    """Проверка и создание необходимых таблиц в базе данных."""
    logger.debug("Checking and creating necessary tables in the database.")
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
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
    except mysql.connector.Error as err:
        logger.critical(f"Database error while checking and creating tables: {err}.")
        raise SystemExit("Database error.")
    finally:
        cursor.close()
        conn.close()
    logger.debug("Tables checked and created if necessary.")


def load_configured_groups():
    """Загрузка настроенных групп из базы данных."""
    global configured_groups_cache
    configured_groups_cache = []
    logger.debug("Loading configured groups from the database.")

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT g.group_id, s.parameter, s.value 
            FROM `groups` g 
            LEFT JOIN group_settings s ON g.group_id = s.group_id
        """
        )

        group_dict = {}
        for row in cursor.fetchall():
            group_id = row["group_id"]
            parameter = row["parameter"]
            value = row["value"]
            if group_id not in group_dict:
                group_dict[group_id] = {"group_id": group_id, "settings": {}}
            if parameter and value:
                group_dict[group_id]["settings"][parameter] = value

        configured_groups_cache = list(group_dict.values())

    except mysql.connector.Error as err:
        logger.critical(f"Database error while loading configured groups: {err}.")
        raise SystemExit("Database error.")
    finally:
        cursor.close()
        conn.close()

    logger.debug(f"Loaded {len(configured_groups_cache)} configured groups.")


def load_user_caches():
    """Загрузка кешей пользователей из базы данных."""
    global suspicious_users_cache, spammers_cache
    suspicious_users_cache = set()
    spammers_cache = set()
    logger.debug("Loading user caches from the database.")
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
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
    except mysql.connector.Error as err:
        logger.critical(f"Database error while loading user caches: {err}.")
        raise SystemExit("Database error.")
    finally:
        cursor.close()
        conn.close()

    logger.debug(
        f"User caches loaded. Suspicious users: {len(suspicious_users_cache)}, Spammers: {len(spammers_cache)}"
    )


async def handle_message(update: Update, context: CallbackContext) -> None:
    """Обработка входящих сообщений в настроенных группах."""
    if not update.message:
        logger.debug("Received update without message.")
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    logger.debug(
        f"Handling message from user {display_user(user)} in chat {display_chat(update.effective_chat)} with text: {update.message.text}"
    )

    if update.effective_chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug("Received message in private chat.")
        return

    if not is_group_configured(chat_id):
        logger.debug(f"Group {chat_id} is not configured.")
        return

    user_id = user.id

    if user_id in spammers_cache:
        await context.bot.ban_chat_member(chat_id, user_id)
        await update.message.delete()
        logger.info(
            f"Banned known spammer {display_user(user)} from group {display_chat(update.effective_chat)}."
        )
        return

    if user_id in suspicious_users_cache:
        # Получаем настройки группы
        group_settings = next(
            (group["settings"] for group in configured_groups_cache if group["group_id"] == chat_id),
            {},
        )
        instructions = group_settings.get("instructions", INSTRUCTIONS_DEFAULT_TEXT)

        # Создаем промпт для OpenAI
        prompt = [
            {
                "role": "system",
                "content": f"Является ли спамом сообщение от пользователя? Важные признаки спам-сообщений: {instructions}",
            },
            {"role": "user", "content": f"{update.message.text}"},
            {"role": "assistant", "content": "Ответьте в формате JSON: {'result': true} если это спам, {'result': false} если это не спам."},
        ]

        try:
            logger.debug(f"Sending prompt to OpenAI for user {display_user(user)}.")

            response = await openai.ChatCompletion.acreate(
                model=MODEL_NAME,
                messages=prompt,
                temperature=0.0,  # Используем нулевую температуру для детерминированности
            )

            assistant_reply = response["choices"][0]["message"]["content"]
            logger.debug(f"Received OpenAI response: {assistant_reply}")

            # Парсинг ответа
            try:
                result = json.loads(assistant_reply)
                is_spam = result.get("result", False)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse OpenAI response: {e}")
                is_spam = False

            if is_spam:
                await context.bot.ban_chat_member(chat_id, user_id)
                await update.message.delete()
                spammers_cache.add(user_id)
                suspicious_users_cache.discard(user_id)

                # Обновление базы данных
                try:
                    conn = mysql.connector.connect(**DB_CONFIG)
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
                except mysql.connector.Error as err:
                    logger.exception(f"Database error when updating spammer status: {err}")
                finally:
                    cursor.close()
                    conn.close()

                logger.info(
                    f"Banned spammer {display_user(user)} from group {display_chat(update.effective_chat)}."
                )
            else:
                suspicious_users_cache.discard(user_id)
                try:
                    conn = mysql.connector.connect(**DB_CONFIG)
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        UPDATE user_entries SET seen_message = TRUE, spammer = FALSE WHERE user_id = %s
                        """,
                        (user_id,),
                    )
                    conn.commit()
                except mysql.connector.Error as err:
                    logger.exception(f"Database error when updating user entry: {err}")
                finally:
                    cursor.close()
                    conn.close()

                logger.info(
                    f"Message from user {display_user(user)} is not spam."
                )
        except Exception as e:
            logger.exception(f"Error querying OpenAI for message processing: {e}")
    else:
        logger.debug(f"User {display_user(user)} is not in suspicious users cache.")


async def check_cas_ban(user_id: int) -> bool:
    """Проверка пользователя по базе CAS (Combot Anti-Spam)."""
    url = f"https://api.cas.chat/check?user_id={user_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                return data.get("ok", False)
    except Exception as e:
        logger.exception(f"Error checking CAS ban for user {user_id}: {e}")
        return False


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
            
            if update.my_chat_member.chat.type == "channel":
                # Бот добавлен в канал
                try:
                    conn = mysql.connector.connect(**DB_CONFIG)
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO `groups` (group_id) VALUES (%s) ON DUPLICATE KEY UPDATE group_id = %s",
                        (chat_id, chat_id),
                    )
                    conn.commit()
                    cursor.close()
                    conn.close()
                    configured_groups_cache.append({"group_id": chat_id, "settings": {}})
                    logger.info(
                        f"Channel {display_chat(update.my_chat_member.chat)} added to configured groups cache and database by user {display_user(update.my_chat_member.from_user)})."
                    )
                except mysql.connector.Error as err:
                    logger.error(
                        f"Database error while adding channel {display_chat(update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}: {err}"
                    )
                    raise SystemExit("Bot added to channel and database update failed.")
            else:
                # Бот добавлен в группу
                logger.debug(
                    f"Bot has been promoted to administrator in group {display_chat(update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}."
                )
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="I have been promoted to an administrator. I am ready to protect your group from spam! Use /start to configure me.",
                    )
                except BadRequest as e:
                    if "not enough rights to send text messages" in str(e):
                        logger.info(
                            f"Bot promoted to administrator in group {display_chat(update.my_chat_member.chat)} but does not have the right to send messages."
                        )
                    else:
                        raise
        elif isinstance(member, ChatMemberMember):
            # Бот не имеет прав администратора
            logger.debug(
                f"Bot currently does not have admin rights in group {display_chat(update.my_chat_member.chat)} as indicated by user {display_user(update.my_chat_member.from_user)}."
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text="I need administrator rights, I cannot protect your group from spam without them. Please promote me to an administrator.",
            )
        elif isinstance(member, ChatMemberLeft) or  isinstance(member, ChatMemberBanned):
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
                    conn = mysql.connector.connect(**DB_CONFIG)
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


async def handle_other_chat_members(update: Update, context: CallbackContext) -> None:
    """Обработка добавления новых участников в группу."""
    chat_id = update.effective_chat.id
    user = update.my_chat_member.new_chat_member.user

    # Проверяем, снова ли пользователь вошёл в группу
    if isinstance(update.my_chat_member.new_chat_member, ChatMemberMember):
        logger.debug(
            f"User {display_user(user)} joined the group {display_chat(update.effective_chat)}."
        )
        user_id = user.id

        if user_id in spammers_cache:
            await context.bot.ban_chat_member(chat_id, user_id)
            logger.info(
                f"Automatically banned known spammer {display_user(user)} from group {chat_id}."
            )
            return

        suspicious_users_cache.add(user_id)

        # Проверка на CAS бан
        is_cas_banned = await check_cas_ban(user_id)
        if is_cas_banned:
            await context.bot.ban_chat_member(chat_id, user_id)
            spammers_cache.add(user_id)
            logger.info(
                f"User {display_user(user)} is CAS banned and was removed from group {chat_id}."
            )
        else:
            # Запись в базу данных
            try:
                conn = mysql.connector.connect(**DB_CONFIG)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO user_entries (user_id, group_id, join_date)
                    VALUES (%s, %s, NOW())
                    ON DUPLICATE KEY UPDATE join_date=NOW()
                    """,
                    (user_id, chat_id),
                )
                conn.commit()
            except mysql.connector.Error as err:
                logger.exception(f"Database error when adding new user {user_id}: {err}")
            finally:
                cursor.close()
                conn.close()
    else:
        logger.debug(
            f"Received chat_member update for user {display_user(user)} in chat {chat_id}."
        )


async def main():
    logger.info("Starting bot.")
    if not TELEGRAM_API_KEY:
        logger.critical("TELEGRAM_API_KEY environment variable not set. Terminating app.")
        return

    # Проверка валидности ключа
    try:
        me = await bot.get_me()
        logger.debug(f"Telegram API key is valid. Bot {display_user(me)} started")
    except Exception as e:
        logger.exception(f"Invalid TELEGRAM_API_KEY: {e}")
        return

    # Проверка и создание таблиц
    check_and_create_tables()
    # Загрузка настроенных групп и кешей пользователей
    load_configured_groups()
    load_user_caches()

    # Инициализируем приложение
    application = Application.builder().token(TELEGRAM_API_KEY).build()

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start_command), group=1)
    application.add_handler(CommandHandler("help", help_command), group=1)
    application.add_handler(CommandHandler("set", set_command), group=1)
    application.add_handler(CommandHandler("get", get_command), group=1)

    # Регистрация обработчиков сообщений
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message), group=1
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
    async def log_event(update: Update, context: CallbackContext) -> None:
        logger.debug(f"Received event: {update}")
        if update.my_chat_member:
            logger.debug(f"my_chat_member event: {update.my_chat_member}")
        if update.chat_member:
            logger.debug(f"chat_member event: {update.chat_member}")

    application.add_handler(MessageHandler(filters.ALL, log_event), group=3)

    # Запускаем бота
    await application.initialize()
    await application.updater.start_polling()
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
