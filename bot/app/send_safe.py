import logging
from telegram.error import ChatMigrated
from telegram import Bot
from .database import configured_groups_cache
import mysql.connector
from .config import DB_CONFIG

async def _persist_migrated_group(old_id: int, new_id: int) -> None:
    """Update DB and in-memory caches when a group migrates to supergroup (new chat id).
    Telegram migrates normal groups to supergroups and changes chat_id (adds -100 prefix).
    We need to keep data continuity by updating the stored group_id.
    """
    # Update in-memory cache entries
    # Local import to avoid side effects if logging config fails in isolated test context
    from .logging_setup import logger  # type: ignore
    for entry in configured_groups_cache:
        if entry.get("group_id") == old_id:
            entry["group_id"] = new_id
    # Update DB rows
    conn = None
    cur = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cur = conn.cursor()
        # groups table
        cur.execute("UPDATE `groups` SET group_id=%s WHERE group_id=%s", (new_id, old_id))
        # group_settings table
        cur.execute("UPDATE group_settings SET group_id=%s WHERE group_id=%s", (new_id, old_id))
        # user_entries table
        cur.execute("UPDATE user_entries SET group_id=%s WHERE group_id=%s", (new_id, old_id))
        conn.commit()
        logger.info(f"Persisted migration old_group_id={old_id} -> new_group_id={new_id} in database.")
    except mysql.connector.Error as e:  # type: ignore[name-defined]
        logger.exception(f"Failed to persist migrated group id {old_id}->{new_id}: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

async def send_message_with_migration(bot: Bot, chat_id: int, *args, **kwargs):
    """Wrapper around Bot.send_message handling ChatMigrated.
    If ChatMigrated is raised, persist change and retry once with new chat id.
    Returns the Message or None if it ultimately fails.
    """
    from .logging_setup import logger  # type: ignore
    try:
        return await bot.send_message(chat_id=chat_id, *args, **kwargs)
    except ChatMigrated as cm:  # type: ignore[attr-defined]
        # python-telegram-bot ChatMigrated provides .new_chat_id
        new_id = int(cm.new_chat_id)
        logger.warning(f"ChatMigrated detected for chat_id={chat_id} -> new_id={new_id}. Updating persistence and retrying send.")
        try:
            await _persist_migrated_group(chat_id, new_id)
        except Exception:
            # persistence errors already logged; proceed with retry anyway
            pass
        try:
            return await bot.send_message(chat_id=new_id, *args, **kwargs)
        except Exception as e:
            logger.error(f"Retry send after migration failed new_chat_id={new_id}: {e}")
            return None
    except Exception as e:
        # generic failure (possibly chat not found) -> log at info to avoid spam
        logger.info(f"send_message failure chat_id={chat_id}: {e}")
        return None
