from .config import *
from .logging_setup import logger
import mysql.connector


# Глобальные переменные для кэширования данных
configured_groups_cache = []
# spammers_cache теперь хранит словарь: {user_id: set(group_ids_where_banned)}
spammers_cache = {}

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

def is_group_configured(group_id: int) -> bool:
    """Проверка наличия группы в кэше настроенных групп."""
    return any(group["group_id"] == group_id for group in configured_groups_cache)

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
    global spammers_cache
    spammers_cache = {}
    logger.debug("Loading user caches from the database.")
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Загрузка спамеров по группам
        cursor.execute(
            """
            SELECT user_id, group_id FROM user_entries 
            WHERE spammer = TRUE AND join_date >= NOW() - INTERVAL 30 DAY
        """
        )
        for user_id, group_id in cursor.fetchall():
            if user_id not in spammers_cache:
                spammers_cache[user_id] = set()
            spammers_cache[user_id].add(group_id)

    except mysql.connector.Error as err:
        logger.critical(f"Database error while loading user caches: {err}.")
        raise SystemExit("Database error.")
    finally:
        cursor.close()
        conn.close()

    logger.debug(
        f"User caches loaded. Spammers: {len(spammers_cache)} users across groups"
    )


def is_user_trusted(user_id: int) -> bool:
    """Проверка, является ли пользователь доверенным (имеет seen_message=TRUE в любой группе)."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) FROM user_entries 
            WHERE user_id = %s AND seen_message = TRUE
            """,
            (user_id,)
        )
        count = cursor.fetchone()[0]
        return count > 0
    except mysql.connector.Error as err:
        logger.exception(f"Database error checking if user {user_id} is trusted: {err}")
        return False
    finally:
        cursor.close()
        conn.close()


def is_user_spammer_anywhere(user_id: int) -> bool:
    """Проверка, является ли пользователь спамером в любой группе."""
    return user_id in spammers_cache and len(spammers_cache[user_id]) > 0


def is_user_spammer_in_group(user_id: int, group_id: int) -> bool:
    """Проверка, является ли пользователь спамером в конкретной группе."""
    return user_id in spammers_cache and group_id in spammers_cache[user_id]
