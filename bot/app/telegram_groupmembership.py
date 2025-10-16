from .logging_setup import logger, current_update_id
from .antispam import check_cas_ban

from telegram import (
    ChatMemberAdministrator,
    ChatMemberLeft,
    ChatMemberBanned,
    ChatMemberMember,
    Update,
)
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest
from telegram.ext import (
    CallbackContext,
)
from .formatting import display_chat, display_user
from .database import (
    configured_groups_cache,
    spammers_cache,
    is_user_spammer_in_group
)
import mysql.connector
from .config import *


async def handle_my_chat_members(update: Update, context: CallbackContext) -> None:
    # Обработка добавления бота в группу либо получения статуса админа
    current_update_id.set(update.update_id)
    logger.debug(
        f"Handling my group membership update in group {
            display_chat(update.my_chat_member.chat)}"
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
                    configured_groups_cache.append(
                        {"group_id": chat_id, "settings": {}})
                    logger.info(
                        f"Channel {display_chat(update.my_chat_member.chat)} added to configured groups cache and database by user {
                            display_user(update.my_chat_member.from_user)}."
                    )
                except mysql.connector.Error as err:
                    logger.error(
                        f"Database error while adding channel {display_chat(update.my_chat_member.chat)} by user {
                            display_user(update.my_chat_member.from_user)}: {err}"
                    )
                    raise SystemExit(
                        "Bot added to channel and database update failed.")
            else:
                # Бот добавлен в группу
                logger.debug(
                    f"Bot has been promoted to administrator in group {display_chat(
                        update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}."
                )
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="I have been promoted to an administrator. I am ready to protect your group from spam!",
                    )
                except BadRequest as e:
                    if "not enough rights to send text messages" in str(e):
                        logger.info(
                            f"Bot promoted to administrator in group {display_chat(
                                update.my_chat_member.chat)} but does not have the right to send messages."
                        )
                    else:
                        raise
        elif isinstance(member, ChatMemberMember):
            # Бот не имеет прав администратора
            logger.debug(
                f"Bot currently does not have admin rights in group {display_chat(
                    update.my_chat_member.chat)} as indicated by user {display_user(update.my_chat_member.from_user)}."
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text="I need administrator rights, I cannot protect your group from spam without them. Please promote me to an administrator.",
            )
        elif isinstance(member, ChatMemberLeft) or isinstance(member, ChatMemberBanned):
            # Бот был удален из группы
            logger.debug(
                f"Bot has been removed from group {display_chat(update.my_chat_member.chat)} by user {
                    display_user(update.my_chat_member.from_user)}."
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
                        "DELETE FROM `group_settings` WHERE group_id = %s", (
                            chat_id,)
                    )
                    conn.commit()
                    cursor.close()
                    conn.close()
                    configured_groups_cache.remove(group)
                    logger.info(
                        f"Group {chat_id} ({update.my_chat_member.chat.title}) removed from configured groups cache and database by user {
                            update.my_chat_member.from_user.id} ({update.my_chat_member.from_user.username})."
                    )
                except mysql.connector.Error as err:
                    logger.error(
                        f"Database error while removing group {display_chat(update.my_chat_member.chat)} by user {
                            display_user(update.my_chat_member.from_user)}: {err}"
                    )
                    raise SystemExit(
                        "Bot removed from group and database update failed."
                    )
                logger.info(
                    f"Bot has been removed from group {display_chat(update.my_chat_member.chat)} by user {
                        display_user(update.my_chat_member.from_user)}"
                )
            else:
                logger.debug(
                    f"Bot has been removed from group {display_chat(update.my_chat_member.chat)} by user {
                        display_user(update.my_chat_member.from_user)}, which was not in configured groups cache."
                )
        else:
            # Бот добавлен в группу
            logger.debug(
                f"Bot added to group {display_chat(update.my_chat_member.chat)} by user {
                    display_user(update.my_chat_member.from_user)}."
            )
            try:
                chat_member = await context.bot.get_chat_member(
                    chat_id, update.my_chat_member.from_user.id
                )

                if chat_member.status not in ["administrator", "creator"]:
                    logger.debug(
                        f"Non-admin user {display_user(update.my_chat_member.from_user)} tried to add the bot to group {
                            display_chat(update.my_chat_member.chat)}."
                    )
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="Only administrators can add the bot to the group. I will leave now.",
                    )
                    await context.bot.leave_chat(chat_id)
                    return
            except BadRequest as e:
                logger.error(
                    f"BadRequest error while checking chat member status in group {display_chat(
                        update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}: {e}"
                )

            await context.bot.send_message(
                chat_id=chat_id,
                text="Hello! I am your antispam guard bot. Thank you for adding me to the group. Make me an administrator to enable my features.",
            )


async def handle_other_chat_members(update: Update, context: CallbackContext) -> None:
    """Обработка добавления новых участников в группу."""
    current_update_id.set(update.update_id)
    chat = update.effective_chat
    member = update.chat_member.new_chat_member

    # Проверяем, снова ли пользователь вошёл в группу
    if member.status == ChatMemberStatus.MEMBER:
        # Проверка: если пользователь спамер в этой группе - банить
        if is_user_spammer_in_group(member.user.id, chat.id):
            await context.bot.ban_chat_member(chat.id, member.user.id)
            logger.info(
                f"Automatically banned known spammer {
                    display_user(member.user)} from group {display_chat(chat)}."
            )
            return

        logger.debug(f"User {display_user(member.user)} joined group {display_chat(chat)}.")

        # Проверка на CAS бан
        is_cas_banned = await check_cas_ban(member.user.id)
        if is_cas_banned:
            await context.bot.ban_chat_member(chat.id, member.user.id)
            
            # Добавить в кеш спамеров для этой группы
            if member.user.id not in spammers_cache:
                spammers_cache[member.user.id] = set()
            spammers_cache[member.user.id].add(chat.id)
            
            logger.info(
                f"User {display_user(member.user)} is CAS banned and was removed from group {display_chat(chat)}.")
                
            # Записать в базу данных как спамера
            try:
                conn = mysql.connector.connect(**DB_CONFIG)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO user_entries (user_id, group_id, join_date, spammer)
                    VALUES (%s, %s, NOW(), TRUE)
                    ON DUPLICATE KEY UPDATE spammer = TRUE
                    """,
                    (member.user.id, chat.id),
                )
                conn.commit()
            except mysql.connector.Error as err:
                logger.exception(f"Database error when adding CAS banned user {display_user(member.user)}: {err}")
            finally:
                cursor.close()
                conn.close()
        else:
            # Обычное присоединение - создать запись в базе, но не как спамера
            try:
                conn = mysql.connector.connect(**DB_CONFIG)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO user_entries (user_id, group_id, join_date)
                    VALUES (%s, %s, NOW())
                    ON DUPLICATE KEY UPDATE join_date=NOW()
                    """,
                    (member.user.id, chat.id),
                )
                conn.commit()
            except mysql.connector.Error as err:
                logger.exception(f"Database error when adding new user {display_user(member.user)}: {err}")
            finally:
                cursor.close()
                conn.close()
    elif member.status == ChatMemberStatus.LEFT:
        logger.debug(
            f"User {display_user(member.user)} left the group {
                display_chat(chat)}."
        )
    else:
        # Проверяем разбан пользователя (изменение статуса с banned на member)
        old_member = update.chat_member.old_chat_member
        if (old_member.status == ChatMemberStatus.BANNED and 
            member.status == ChatMemberStatus.MEMBER):
            # Пользователь был разбанен админом - снимаем флаг спамера в этой группе
            if is_user_spammer_in_group(member.user.id, chat.id):
                # Удалить из кеша спамеров для этой группы
                if member.user.id in spammers_cache:
                    spammers_cache[member.user.id].discard(chat.id)
                    if len(spammers_cache[member.user.id]) == 0:
                        del spammers_cache[member.user.id]
                
                # Обновить базу данных
                try:
                    conn = mysql.connector.connect(**DB_CONFIG)
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        UPDATE user_entries SET spammer = FALSE WHERE user_id = %s AND group_id = %s
                        """,
                        (member.user.id, chat.id),
                    )
                    conn.commit()
                    logger.info(
                        f"User {display_user(member.user)} was unbanned by admin in group {display_chat(chat)}. Removed spammer flag for this group."
                    )
                except mysql.connector.Error as err:
                    logger.exception(f"Database error when removing spammer flag: {err}")
                finally:
                    cursor.close()
                    conn.close()
        
        logger.debug(
            f"Received chat_member update for user {display_user(member.user)} in chat {
                display_chat(chat)}."
        )
