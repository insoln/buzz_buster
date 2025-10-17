from .logging_setup import logger, current_update_id, log_event, with_update_id
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


@with_update_id
async def handle_my_chat_members(update: Update, context: CallbackContext) -> None:
    # Обработка добавления бота в группу либо получения статуса админа
    # update_id set by decorator
    mc = getattr(update, 'my_chat_member', None)
    if mc is None:
        log_event("skip_no_my_chat_member")
        return
    chat_obj = getattr(mc, 'chat', None)
    if chat_obj is None:
        log_event("skip_my_chat_member_no_chat")
        return
    member = getattr(mc, 'new_chat_member', None)
    if member is None:
        log_event("skip_my_chat_member_no_new_member", chat=chat_obj)
        return
    log_event("my_chat_members_update", chat=chat_obj, user=getattr(member, 'user', None))
    chat_id = chat_obj.id
    from_user = getattr(mc, 'from_user', None)
    if getattr(member, 'user', None) and member.user.id == context.bot.id:
        # Сценарии изменения статуса бота
        if isinstance(member, ChatMemberAdministrator):
            if chat_obj.type == "channel":
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
                    log_event("channel_configured", chat=chat_obj, user=from_user)
                except mysql.connector.Error as err:
                    log_event("channel_config_error", chat=chat_obj, user=from_user, error=str(err))
                    raise SystemExit("Bot added to channel and database update failed.")
            else:
                log_event("bot_promoted_admin", chat=chat_obj, user=from_user)
                try:
                    await context.bot.send_message(chat_id=chat_id, text="I have been promoted to an administrator. I am ready to protect your group from spam!")
                except BadRequest as e:
                    if "not enough rights to send text messages" in str(e):
                        log_event("bot_promoted_no_send_rights", chat=chat_obj, user=from_user)
                    else:
                            raise
        elif isinstance(member, ChatMemberMember):
            log_event("bot_no_admin_rights", chat=chat_obj, user=from_user)
            await context.bot.send_message(chat_id=chat_id, text="I need administrator rights, I cannot protect your group from spam without them. Please promote me to an administrator.")
        elif isinstance(member, (ChatMemberLeft, ChatMemberBanned)):
            log_event("bot_removed", chat=chat_obj, user=from_user)
            group = next((g for g in configured_groups_cache if g["group_id"] == chat_id), None)
            if group:
                try:
                    conn = mysql.connector.connect(**DB_CONFIG)
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM `groups` WHERE group_id = %s", (chat_id,))
                    cursor.execute("DELETE FROM `group_settings` WHERE group_id = %s", (chat_id,))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    configured_groups_cache.remove(group)
                    log_event("group_removed_db", chat=chat_obj, user=from_user)
                except mysql.connector.Error as err:
                    log_event("group_remove_error", chat=chat_obj, user=from_user, error=str(err))
                    raise SystemExit("Bot removed from group and database update failed.")
                log_event("bot_removed_confirm", chat=chat_obj, user=from_user)
            else:
                log_event("bot_removed_not_configured", chat=chat_obj, user=from_user)
        else:
            log_event("bot_added_group", chat=chat_obj, user=from_user)
            try:
                chat_member = await context.bot.get_chat_member(chat_id, from_user.id if from_user else context.bot.id)
                if chat_member.status not in ["administrator", "creator"]:
                    log_event("bot_added_by_non_admin", chat=chat_obj, user=from_user)
                    await context.bot.send_message(chat_id=chat_id, text="Only administrators can add the bot to the group. I will leave now.")
                    await context.bot.leave_chat(chat_id)
                    return
            except BadRequest as e:
                log_event("check_member_status_error", chat=chat_obj, user=from_user, error=str(e))
            await context.bot.send_message(chat_id=chat_id, text="Hello! I am your antispam guard bot. Thank you for adding me to the group. Make me an administrator to enable my features.")


@with_update_id
async def handle_other_chat_members(update: Update, context: CallbackContext) -> None:
    """Новая логика обработки добавления/изменения участника группы."""
    # update_id set by decorator
    if not update.chat_member:
        log_event("skip_no_chat_member")
        return
    chat = update.effective_chat
    if chat is None:
        log_event("skip_no_chat")
        return
    member = update.chat_member.new_chat_member
    old_member = update.chat_member.old_chat_member
    if member is None:
        log_event("skip_no_new_chat_member")
        return

    # 1. Админ мог разбанить локального спамера (из BANNED -> MEMBER)
    repo = get_user_state_repo()
    prev_status = ''
    new_status = ''
    if old_member is not None:
        prev_status = str(getattr(old_member, 'status', '')).lower()
        new_status = str(getattr(member, 'status', '')).lower()
        # Treat 'kicked' (telegram lib may map to left) as banned-like for unban flow.
        if prev_status in ("banned", "restricted", "kicked") and new_status == "member":
            # Attempt to clear local/global spammer status.
            entry = repo.entry(member.user.id, chat.id)
            spammer_flag = False
            if entry:
                _, spammer_entry_flag = entry
                spammer_flag = bool(spammer_entry_flag) or (member.user.id in spammers_cache)
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
                    other_groups = [g for g in repo.groups_with_spam_flag(member.user.id) if g != chat.id]
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
                log_event("unban_clear_spammer", user_id=member.user.id, chat_id=chat.id, user=member.user, chat=chat, other_groups=other_groups)
                return

    # 2. Обычный join
    if getattr(member, 'status', None) == ChatMemberStatus.MEMBER:
        uid = member.user.id

        # a) Глобально известный спамер -> локальный флаг + бан
        if repo.is_spammer(uid):
            # Already globally flagged; no need to re-mark in DB here (avoids redundant write during tests)
            try:
                await context.bot.ban_chat_member(chat.id, uid)
            except Exception as e:
                log_event("ban_known_spammer_error", user=member.user, chat=chat, error=str(e))
            log_event("join_ban_known_spammer", user=member.user, chat=chat)
            return

        # b) Пользователь уже когда-то писал (seen в любой группе) -> создаём unseen запись (seen_message=FALSE), не добавляем в suspicious
        if repo.is_seen(uid):
            repo.mark_unseen(uid, chat.id)
            log_event("join_seen_elsewhere", user=member.user, chat=chat)
        else:
            # c) Совершенно новый глобально -> unseen + suspicious
            repo.mark_unseen(uid, chat.id)
            suspicious_users_cache.add(uid)
            log_event("join_new_suspicious", user=member.user, chat=chat)

        # d) CAS проверка
        try:
            is_cas_banned = await check_cas_ban(uid)
        except Exception as e:
            log_event("cas_check_error", user=member.user, chat=chat, error=str(e))
            is_cas_banned = False
        if is_cas_banned:
            repo.mark_spammer(uid, chat.id)
            try:
                await context.bot.ban_chat_member(chat.id, uid)
            except Exception:
                pass
            log_event("cas_ban", user=member.user, chat=chat)

    elif member.status == ChatMemberStatus.LEFT:
        log_event("user_left", user=member.user, chat=chat)
    else:
        log_event("chat_member_update", user=member.user, chat=chat, status=member.status)
