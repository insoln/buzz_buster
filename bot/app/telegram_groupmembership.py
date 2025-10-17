from .logging_setup import logger, current_update_id, log_event
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
    suspicious_users_cache,
    get_user_state_repo,
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
                        {"group_id": chat_id, "settings": {}}
                    )
                    logger.info(
                        f"Channel {display_chat(update.my_chat_member.chat)} added to configured groups cache and database by user {
                            display_user(update.my_chat_member.from_user)}."
                    )
                except mysql.connector.Error as err:
                    logger.error(
                        f"Database error while adding channel {display_chat(update.my_chat_member.chat)} by user {
                            display_user(update.my_chat_member.from_user)}: {err}"
                    )
                    raise SystemExit("Bot added to channel and database update failed.")
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
                        "DELETE FROM `group_settings` WHERE group_id = %s", (chat_id,)
                    )
                    conn.commit()
                    cursor.close()
                    conn.close()
                    configured_groups_cache.remove(group)
                    logger.info(
                        f"Group {display_chat(update.my_chat_member.chat)} removed from configured groups cache and database by user {display_user(update.my_chat_member.from_user)}"
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
                    f"Bot has been removed from group {display_chat(update.my_chat_member.chat)} by user {display_user(update.my_chat_member.from_user)}"
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
    """Новая логика обработки добавления/изменения участника группы."""
    current_update_id.set(update.update_id)
    if not update.chat_member:
        logger.debug("No chat_member field in update; skipping.")
        return
    chat = update.effective_chat
    if chat is None:
        logger.debug("No chat in update; skipping.")
        return
    member = update.chat_member.new_chat_member
    old_member = update.chat_member.old_chat_member
    if member is None:
        logger.debug("No new_chat_member; skipping.")
        return

    # 1. Админ мог разбанить локального спамера (из BANNED -> MEMBER)
    repo = get_user_state_repo()
    if old_member is not None:
        prev_status = str(getattr(old_member, "status", "")).lower()
        new_status = str(getattr(member, "status", "")).lower()
        if prev_status in ("banned", "restricted") and new_status == "member":
            # Attempt to clear local/global spammer status.
            entry = repo.entry(member.user.id, chat.id)
            spammer_flag = False
            if entry:
                _, spammer_entry_flag = entry
                spammer_flag = bool(spammer_entry_flag) or (
                    member.user.id in spammers_cache
                )
            else:
                # No DB entry (e.g., test / offline DB). Fall back to cache heuristic.
                spammer_flag = member.user.id in spammers_cache
            if spammer_flag:
                # Всегда пытаемся очистить локальный флаг и пересчитать остальные группы.
                other_groups = []
                if entry:
                    try:
                        repo.clear_spammer(member.user.id, chat.id)
                    except Exception:
                        pass
                # Пытаемся получить список других групп, где он ещё спамер
                try:
                    other_groups = [
                        g
                        for g in repo.groups_with_spam_flag(member.user.id)
                        if g != chat.id
                    ]
                except Exception:
                    # Если не удалось (например, нет БД), используем кэш как эвристику
                    other_groups = []
                if chat.id in other_groups:
                    other_groups.remove(chat.id)
                # Если больше нигде не числится, убираем из глобального кэша
                if not other_groups and member.user.id in spammers_cache:
                    spammers_cache.discard(member.user.id)
                msg = "Reputation in this group restored."
                if other_groups:
                    msg += f" Still flagged in groups: {', '.join(map(str, other_groups))}. Unban there to fully clear reputation."
                try:
                    await context.bot.send_message(chat.id, msg)
                except Exception:
                    pass
                log_event(
                    "unban_clear_spammer",
                    user_id=member.user.id,
                    chat_id=chat.id,
                    other_groups=other_groups,
                )
                return

    # 2. Обычный join
    if getattr(member, "status", None) == ChatMemberStatus.MEMBER:
        uid = member.user.id

        # a) Глобально известный спамер -> локальный флаг + бан
        if repo.is_spammer(uid):
            # Already globally flagged; no need to re-mark in DB here (avoids redundant write during tests)
            try:
                await context.bot.ban_chat_member(chat.id, uid)
            except Exception as e:
                logger.exception(
                    f"Failed to ban known spammer {display_user(member.user)} in {display_chat(chat)}: {e}"
                )
            log_event("join_ban_known_spammer", user_id=member.user.id, chat_id=chat.id)
            return

        # b) Пользователь уже когда-то писал (seen в любой группе) -> создаём unseen запись (seen_message=FALSE), не добавляем в suspicious
        if repo.is_seen(uid):
            repo.mark_unseen(uid, chat.id)
            log_event("join_seen_elsewhere", user_id=member.user.id, chat_id=chat.id)
        else:
            # c) Совершенно новый глобально -> unseen + suspicious
            repo.mark_unseen(uid, chat.id)
            suspicious_users_cache.add(uid)
            log_event("join_new_suspicious", user_id=member.user.id, chat_id=chat.id)

        # d) CAS проверка
        try:
            is_cas_banned = await check_cas_ban(uid)
        except Exception as e:
            logger.exception(f"CAS check failed for {uid}: {e}")
            is_cas_banned = False
        if is_cas_banned:
            repo.mark_spammer(uid, chat.id)
            try:
                await context.bot.ban_chat_member(chat.id, uid)
            except Exception:
                pass
            log_event("cas_ban", user_id=member.user.id, chat_id=chat.id)

    elif member.status == ChatMemberStatus.LEFT:
        log_event("user_left", user_id=member.user.id, chat_id=chat.id)
    else:
        log_event(
            "chat_member_update",
            user_id=member.user.id,
            chat_id=chat.id,
            status=member.status,
        )
