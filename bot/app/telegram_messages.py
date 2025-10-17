from .logging_setup import logger, current_update_id, log_event
from .antispam import check_openai_spam

from telegram import (
    Update,
)

from telegram.ext import (
    CallbackContext,
)
from .formatting import display_chat, display_user
from .database import (
    is_group_configured,
    configured_groups_cache,
    get_user_entry,
    get_user_state_repo,
)
import mysql.connector
from .config import *

# Вспомогательная функция для проверки спама
async def process_spam(update: Update, context: CallbackContext, user, chat) -> bool:
    is_spam = False
    # Проверка пересланного сообщения
    msg = update.message
    if msg and msg.forward_origin:
        is_spam = True
    # Проверка через OpenAI
    if not is_spam:
        try:
            group_settings = next(
                (group["settings"] for group in configured_groups_cache if group["group_id"] == chat.id),
                {})
            instructions = group_settings.get("instructions", INSTRUCTIONS_DEFAULT_TEXT)
            logger.debug(f"Sending prompt to OpenAI for user {display_user(user)}.")
            if msg:
                is_spam = await check_openai_spam(msg.text or msg.caption, instructions)
        except Exception as e:
            logger.exception(f"Error querying OpenAI: {e}")
    return is_spam

async def handle_message(update: Update, context: CallbackContext) -> None:
    """Обработка входящих сообщений в настроенных группах."""
    current_update_id.set(update.update_id)  # type: ignore[arg-type]

    message = update.message
    chat = update.effective_chat
    user = update.effective_user

    if not message or chat is None or user is None:
        logger.debug("Update missing message/chat/user; skipping.")
        return

    log_event("message_receive", user_id=user.id, chat_id=chat.id, text=message.text or message.caption)

    if chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")  # type: ignore[attr-defined]
        logger.debug("Received message in private chat.")
        return

    if not is_group_configured(chat.id):
        log_event("skip_not_configured", chat_id=chat.id)
        return

    repo = get_user_state_repo()

    # 1. Сообщение от спамера глобально / локально
    if repo.is_spammer(user.id):
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
            try:
                await message.delete()
            except Exception:
                pass
        except Exception:
            pass
        log_event("ban_global_spammer", user_id=user.id, chat_id=chat.id)
        return

    # 2. Состояние в текущей группе
    entry = get_user_entry(user.id, chat.id)  # (seen, spammer) or None
    current_seen = entry[0] if entry else None
    current_spammer = entry[1] if entry else None

    # 3. Если пользователь в общем suspicious списке -> проверить
    if repo.is_suspicious(user.id):
        is_spam = await process_spam(update, context, user, chat)
        if is_spam:
            repo.mark_spammer(user.id, chat.id)
            try:
                await context.bot.ban_chat_member(chat.id, user.id)
                try:
                    await message.delete()
                except Exception:
                    pass
            except Exception:
                pass
            log_event("first_message_spam", user_id=user.id, chat_id=chat.id)
        else:
            repo.mark_seen(user.id, chat.id)
            log_event("first_message_ham", user_id=user.id, chat_id=chat.id)
        return

    # 4. Если уже виделся в этой группе -> не проверяем
    if current_seen:
        log_event("skip_seen", user_id=user.id, chat_id=chat.id)
        return

    # 5. Нет записи по группе
    if entry is None:
        # 5a. Есть опыт (seen) где-либо -> переносим доверие
        if repo.is_seen(user.id):
            repo.mark_seen(user.id, chat.id)
            log_event("inherit_trust", user_id=user.id, chat_id=chat.id)
            return
        # 5b. Совершенно новый -> создаём unseen (в репозитории он добавит в suspicious)
        repo.mark_unseen(user.id, chat.id)
        is_spam = await process_spam(update, context, user, chat)
        if is_spam:
            repo.mark_spammer(user.id, chat.id)
            try:
                await context.bot.ban_chat_member(chat.id, user.id)
                try:
                    await message.delete()
                except Exception:
                    pass
            except Exception:
                pass
            log_event("new_user_spam", user_id=user.id, chat_id=chat.id)
        else:
            repo.mark_seen(user.id, chat.id)
            log_event("new_user_ham", user_id=user.id, chat_id=chat.id)
        return

    # 6. Есть запись, но seen_message=False (редкий случай если потеря кэша)
    if entry and current_seen is False:
        if repo.is_seen(user.id):
            repo.mark_seen(user.id, chat.id)
            log_event("late_seen_upgrade", user_id=user.id, chat_id=chat.id)
            return
        # fallback: считаем подозрительным повторно (обновляем unseen метку для консистентности)
        repo.mark_unseen(user.id, chat.id)
        is_spam = await process_spam(update, context, user, chat)
        if is_spam:
            repo.mark_spammer(user.id, chat.id)
            try:
                await context.bot.ban_chat_member(chat.id, user.id)
                try:
                    await message.delete()
                except Exception:
                    pass
            except Exception:
                pass
            log_event("late_suspicious_spam", user_id=user.id, chat_id=chat.id)
        else:
            repo.mark_seen(user.id, chat.id)
            log_event("late_suspicious_ham", user_id=user.id, chat_id=chat.id)
        return

    log_event("unhandled_path", user_id=user.id, chat_id=chat.id)
