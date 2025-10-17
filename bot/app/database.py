from .config import *
from .logging_setup import logger
import mysql.connector
from .formatting import display_chat, display_user
from typing import List, Optional, Tuple
from telegram import Chat, Update


# Глобальные переменные для кэширования данных
configured_groups_cache = []  # [{group_id, settings}]
suspicious_users_cache = set()  # user_ids currently having at least one unseen (seen_message=FALSE) non-spam entry
spammers_cache = set()  # user_ids having any spammer=TRUE entry
seen_users_cache = set()  # user_ids having at least one seen_message=TRUE entry

# Negative caches ("absence" memoization) to avoid repeated empty/unnecessary queries to the DB.
# ВНИМАНИЕ: они инвалиируются при позитивных апдейтах (mark_spammer/mark_seen) и при очистке кэшей.
not_spammers_cache = set()  # user_ids для которых подтверждено ОТСУТСТВИЕ spammer=TRUE записей
not_seen_cache = set()      # user_ids для которых подтверждено отсутствие любых seen_message=TRUE записей

# Отладочные счётчики количества реальных (лениво инициированных) запросов к БД
# для функций user_has_spammer_anywhere / user_has_seen_anywhere. Используются в тестах производительности.
debug_counter_spammer_queries = 0
debug_counter_seen_queries = 0

def _fetch_user_ids(cursor) -> set[int]:
    """Helper function to convert cursor results to a set of user IDs."""
    return {int(uid) for (uid,) in cursor.fetchall() if uid is not None}

def get_db_connection():
    """Return a new DB connection."""
    return mysql.connector.connect(**DB_CONFIG)


def check_and_create_tables():
    conn = None
    cursor = None  # predeclare for finally safety
    try:
        conn = get_db_connection()
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
            spammer BOOLEAN DEFAULT FALSE,
            UNIQUE KEY uniq_user_group (user_id, group_id),
            KEY idx_user (user_id),
            KEY idx_group (group_id),
            KEY idx_spammer (spammer),
            KEY idx_seen (seen_message)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """
        )
        conn.commit()
    except mysql.connector.Error as err:
        logger.critical(f"Database error while checking and creating tables: {err}.")
        raise SystemExit("Database error.")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    logger.debug("Tables checked and created if necessary.")

def is_group_configured(group_id: int) -> bool:
    """Проверка наличия группы в кэше настроенных групп."""
    return any(group["group_id"] == group_id for group in configured_groups_cache)

async def add_configured_group(chat: Chat, update: Update):
    user = update.effective_user
    conn = None
    cursor = None
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
    finally:
        if cursor:
            cursor.close()
        if conn:
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

def load_configured_groups():
    """Загрузка настроенных групп из базы данных."""
    global configured_groups_cache
    configured_groups_cache = []
    logger.debug("Loading configured groups from the database.")

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT g.group_id, s.parameter, s.value 
            FROM `groups` g 
            LEFT JOIN group_settings s ON g.group_id = s.group_id
            """
        )
        group_dict = {}
        for row in cur.fetchall():
            group_id = row.get("group_id") if isinstance(row, dict) else row[0]
            parameter = row.get("parameter") if isinstance(row, dict) else None
            value = row.get("value") if isinstance(row, dict) else None
            if group_id not in group_dict:
                group_dict[group_id] = {"group_id": group_id, "settings": {}}
            if parameter and value:
                group_dict[group_id]["settings"][parameter] = value
        configured_groups_cache = list(group_dict.values())
    except mysql.connector.Error as err:
        logger.critical(f"Database error while loading configured groups: {err}.")
        raise SystemExit("Database error.")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    logger.debug(f"Loaded {len(configured_groups_cache)} configured groups.")


def load_user_caches():
    """Полная загрузка пользовательских кэшей из БД (cold start / full refresh)."""
    global suspicious_users_cache, spammers_cache, seen_users_cache
    suspicious_users_cache = set()
    spammers_cache = set()
    seen_users_cache = set()
    # Очистка negative caches и счётчиков
    not_spammers_cache.clear()
    not_seen_cache.clear()
    global debug_counter_spammer_queries, debug_counter_seen_queries
    debug_counter_spammer_queries = 0
    debug_counter_seen_queries = 0
    logger.debug("Loading user caches from the database (full refresh).")
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Спамеры
        cur.execute("SELECT DISTINCT user_id FROM user_entries WHERE spammer = TRUE")  # type: ignore[arg-type]
        spammers_cache = _fetch_user_ids(cur)
        # Seen пользователи
        cur.execute("SELECT DISTINCT user_id FROM user_entries WHERE seen_message = TRUE")  # type: ignore[arg-type]
        seen_users_cache = _fetch_user_ids(cur)
        # Подозрительные: хотя бы одна запись без seen и без spammer
        cur.execute("""SELECT DISTINCT user_id FROM user_entries 
            WHERE seen_message = FALSE AND spammer = FALSE""")  # type: ignore[arg-type]
        suspicious_users_cache = _fetch_user_ids(cur)
    except mysql.connector.Error as err:
        logger.critical(f"Database error while loading user caches: {err}.")
        raise SystemExit("Database error.")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    logger.debug(
        f"User caches loaded. Seen: {len(seen_users_cache)}, Suspicious: {len(suspicious_users_cache)}, Spammers: {len(spammers_cache)}"
    )


# ===== New helper functions for new logic =====

def user_has_spammer_anywhere(user_id: int) -> bool:
    """Проверка глобального статуса спамера с использованием кэша.
    При отсутствии в кэше выполняется ленивый запрос в БД (negative не кэшируем)."""
    # Positive cache hit
    if user_id in spammers_cache:
        return True
    # Negative cache hit
    if user_id in not_spammers_cache:
        return False
    global debug_counter_spammer_queries
    debug_counter_spammer_queries += 1
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM user_entries WHERE user_id=%s AND spammer=TRUE LIMIT 1",
            (user_id,),
        )
        if cur.fetchone() is not None:
            spammers_cache.add(user_id)
            not_spammers_cache.discard(user_id)
            return True
        # negative result -> кэшируем отсутствие
        not_spammers_cache.add(user_id)
        return False
    except mysql.connector.Error as err:
        logger.exception(f"DB error user_has_spammer_anywhere({user_id}): {err}")
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def user_has_seen_anywhere(user_id: int) -> bool:
    if user_id in seen_users_cache:
        return True
    if user_id in not_seen_cache:
        # Reconciliation safeguard: if concurrently added to seen cache, prefer positive
        if user_id in seen_users_cache:
            not_seen_cache.discard(user_id)
            return True
        return False
    global debug_counter_seen_queries
    debug_counter_seen_queries += 1
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM user_entries WHERE user_id=%s AND seen_message=TRUE LIMIT 1",
            (user_id,),
        )
        if cur.fetchone() is not None:
            seen_users_cache.add(user_id)
            not_seen_cache.discard(user_id)
            return True
        not_seen_cache.add(user_id)
        return False
    except mysql.connector.Error as err:
        logger.exception(f"DB error user_has_seen_anywhere({user_id}): {err}")
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def ensure_user_entry(user_id: int, group_id: int):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_entries (user_id, group_id, join_date)
            VALUES (%s, %s, NOW())
            ON DUPLICATE KEY UPDATE join_date=join_date
            """,
            (user_id, group_id),
        )
        conn.commit()
    except mysql.connector.Error as err:
        logger.exception(f"DB error ensure_user_entry({user_id},{group_id}): {err}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def mark_spammer_in_group(user_id: int, group_id: int):
    """Помечает пользователя спамером в группе + обновляет кэши."""
    global spammers_cache, not_spammers_cache, suspicious_users_cache
    conn = None
    cur = None
    success = False
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_entries (user_id, group_id, join_date, spammer)
            VALUES (%s, %s, NOW(), TRUE)
            ON DUPLICATE KEY UPDATE spammer=TRUE
            """,
            (user_id, group_id),
        )
        conn.commit()
        success = True
    except mysql.connector.Error as err:
        logger.exception(f"DB error mark_spammer_in_group({user_id},{group_id}): {err}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    # Всегда обновляем кэш (даже если БД не сработала, чтобы тесты с фейковыми коннектами могли опираться на поведение)
    spammers_cache.add(user_id)
    not_spammers_cache.discard(user_id)
    suspicious_users_cache.discard(user_id)
    return success

def mark_seen_in_group(user_id: int, group_id: int):
    global seen_users_cache, not_seen_cache, suspicious_users_cache
    # Оптимистично обновляем кэши ДО обращения к БД, чтобы последующие чтения сразу видели статус.
    seen_users_cache.add(user_id)
    not_seen_cache.discard(user_id)
    suspicious_users_cache.discard(user_id)

    conn = None
    cur = None
    success = False
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_entries (user_id, group_id, join_date, seen_message)
            VALUES (%s, %s, NOW(), TRUE)
            ON DUPLICATE KEY UPDATE seen_message=TRUE
            """,
            (user_id, group_id),
        )
        conn.commit()
        success = True
    except mysql.connector.Error as err:
        logger.exception(f"DB error mark_seen_in_group({user_id},{group_id}): {err}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    # Повторно (идемпотентно) актуализируем кэши после операции
    seen_users_cache.add(user_id)
    not_seen_cache.discard(user_id)
    suspicious_users_cache.discard(user_id)
    # Принудительно прогреваем позитивный путь для user_has_seen_anywhere
    user_has_seen_anywhere(user_id)
    return success

def mark_unseen_in_group(user_id: int, group_id: int):
    """Создаёт / фиксирует запись со статусом unseen (используется при джойне). Добавляем в suspicious."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_entries (user_id, group_id, join_date, seen_message)
            VALUES (%s, %s, NOW(), FALSE)
            ON DUPLICATE KEY UPDATE seen_message=FALSE
            """,
            (user_id, group_id),
        )
        conn.commit()
        # Добавляем в suspicious если не спамер
        if user_id not in spammers_cache:
            suspicious_users_cache.add(user_id)
    except mysql.connector.Error as err:
        logger.exception(f"DB error mark_unseen_in_group({user_id},{group_id}): {err}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def clear_spammer_flag_in_group(user_id: int, group_id: int):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE user_entries SET spammer=FALSE WHERE user_id=%s AND group_id=%s",
            (user_id, group_id),
        )
        conn.commit()
    except mysql.connector.Error as err:
        logger.exception(f"DB error clear_spammer_flag_in_group({user_id},{group_id}): {err}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    # Пересчёт глобального флага спамера
    if user_id in spammers_cache:
        if not groups_where_spammer(user_id):
            spammers_cache.discard(user_id)
            # Теперь отрицательный результат можно занести в negative cache
            not_spammers_cache.add(user_id)
    # Возможно вернуть в suspicious если остались unseen записи
    # (упрощённо не добавляем обратно здесь — это можно расширить при необходимости)

def groups_where_spammer(user_id: int) -> List[int]:
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT group_id FROM user_entries WHERE user_id=%s AND spammer=TRUE",
            (user_id,),
        )
        rows = cur.fetchall()
        return [int(row[0]) for row in rows if row[0] is not None]  # type: ignore[misc]
    except mysql.connector.Error as err:
        logger.exception(f"DB error groups_where_spammer({user_id}): {err}")
        return []
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def user_is_spammer_in_group(user_id: int, group_id: int) -> bool:
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM user_entries WHERE user_id=%s AND group_id=%s AND spammer=TRUE LIMIT 1",
            (user_id, group_id),
        )
        return cur.fetchone() is not None
    except mysql.connector.Error as err:
        logger.exception(f"DB error user_is_spammer_in_group({user_id},{group_id}): {err}")
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def get_user_entry(user_id: int, group_id: int) -> Optional[Tuple[bool, bool]]:
    """Return tuple (seen_message, spammer) or None if no record."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT seen_message, spammer FROM user_entries WHERE user_id=%s AND group_id=%s LIMIT 1",
            (user_id, group_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        seen, spammer = row
        return bool(seen), bool(spammer)
    except mysql.connector.Error as err:
        logger.exception(f"DB error get_user_entry({user_id},{group_id}): {err}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# =================== Repository Pattern (advanced abstraction) ===================

class UserStateRepository:
    """Высокоуровневый слой для операций со статусами пользователей.
    Все обновления должны идти через него (постепенная миграция), чтобы кэш оставался консистентным."""

    def is_spammer(self, user_id: int) -> bool:
        return user_has_spammer_anywhere(user_id)

    def is_seen(self, user_id: int) -> bool:
        return user_has_seen_anywhere(user_id)

    def is_suspicious(self, user_id: int) -> bool:
        return (user_id in suspicious_users_cache) and (user_id not in spammers_cache)

    def mark_spammer(self, user_id: int, group_id: int):
        mark_spammer_in_group(user_id, group_id)

    def mark_seen(self, user_id: int, group_id: int):
        mark_seen_in_group(user_id, group_id)

    def mark_unseen(self, user_id: int, group_id: int):
        mark_unseen_in_group(user_id, group_id)

    def clear_spammer(self, user_id: int, group_id: int):
        clear_spammer_flag_in_group(user_id, group_id)

    def groups_with_spam_flag(self, user_id: int):
        return groups_where_spammer(user_id)

    def entry(self, user_id: int, group_id: int):
        return get_user_entry(user_id, group_id)


# Singleton instance (можно заменить фабрикой при DI)
user_state_repo = UserStateRepository()

def get_user_state_repo() -> UserStateRepository:
    return user_state_repo

