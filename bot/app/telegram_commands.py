from .logging_setup import logger, current_update_id, with_update_id
from telegram import (
    Update,
)
from telegram.error import BadRequest
from telegram.ext import (
    CallbackContext,
)
from .formatting import display_chat, display_user
from .database import (
    is_group_configured,
    add_configured_group,
    get_user_state_repo,
    groups_where_spammer,
)
import mysql.connector
from .config import *

try:
    import sentry_sdk

    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False


@with_update_id
async def test_sentry_command(update: Update, context: CallbackContext) -> None:
    """Команда для тестирования Sentry интеграции (только для администраторов)."""
    # update_id set by decorator
    user = update.effective_user

    # Проверяем, что это администратор
    if not ADMIN_TELEGRAM_ID or str(user.id) != str(ADMIN_TELEGRAM_ID):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    if not SENTRY_AVAILABLE or not SENTRY_DSN:
        await update.message.reply_text("Sentry не настроен или недоступен.")
        return

    try:
        # Тестируем разные типы событий в Sentry
        await update.message.reply_text("Тестирую Sentry интеграцию...")

        # 1. Тест обычного сообщения
        sentry_sdk.capture_message("Test message from Telegram bot", level="info")

        # 2. Тест с дополнительным контекстом
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("test_type", "telegram_command")
            scope.set_user({"id": user.id, "username": user.username})
            scope.set_extra("command", "/test_sentry")
            sentry_sdk.capture_message("Test message with context", level="warning")

        # 3. Тест исключения (но не реального)
        try:
            # Это намеренная ошибка для тестирования
            division_by_zero = 1 / 0
        except ZeroDivisionError as e:
            sentry_sdk.capture_exception(e)

        await update.message.reply_text(
            "✅ Sentry тест завершен! Проверьте dashboard Sentry."
        )
        logger.info(f"Sentry test executed by admin {display_user(user)}")

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при тестировании Sentry: {e}")
        logger.exception("Error during Sentry test")


@with_update_id
async def start_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /start."""
    # update_id set by decorator
    chat = update.effective_chat
    user = update.effective_user
    logger.debug(
        f"Handling /start command from user {display_user(user)} in chat {display_chat(chat)}"
    )

    if chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug("Received /start in private chat.")
        return

    try:
        chat_member = await context.bot.get_chat_member(chat.id, user.id)
        user_status = chat_member.status
    except BadRequest as e:
        logger.exception(
            f"Failed to get chat member status for user {display_user(user)} in chat {display_chat(chat)}: {e}"
        )
        user_status = None

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        bot_status = bot_member.status
    except BadRequest as e:
        logger.exception(
            f"Failed to get bot's status in chat {display_chat(chat)}: {e}"
        )
        bot_status = None

    if bot_status not in ["administrator", "creator"]:
        await update.message.reply_text("Мне нужны права администратора в этой группе.")
        logger.debug(f"Bot is not an admin in group {display_chat(chat)}.")
        return

    if user_status not in ["administrator", "creator"]:
        await update.message.reply_text("Только администраторы могут настраивать бота.")
        logger.debug(
            f"User {display_user(user)} tried to configure group {display_chat(chat)} but they're not admin."
        )
        return

    if is_group_configured(chat.id):
        await update.message.reply_text(
            "Бот уже настроен для этой группы. Используйте /help, чтобы увидеть доступные команды."
        )
        logger.debug(
            f"User {display_user(user)} tried to configure group {display_chat(chat)}, but this group is already configured."
        )
        return

    # Настройка группы
    # Original helper expects 'update' object providing effective_chat/user, keep signature update first
    await add_configured_group(update)


@with_update_id
async def help_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /help."""
    # update_id set by decorator
    chat = update.effective_chat
    user = update.effective_user
    logger.debug(f"Handling /help command from user {display_user(user)} in chat {display_chat(chat)}")

    if chat.type == "private":
        await update.message.reply_text("Этот бот предназначен только для групп.")
        logger.debug(
            f"Received /help in private chat from user {display_user(user)} in chat {display_chat(chat)}"
        )
        return

    chat_id = update.effective_chat.id
        # Настройка группы: add_configured_group теперь принимает только объект update
        # (он содержит effective_chat / effective_user), параметр chat больше не нужен.
    if is_group_configured(chat_id):
        await update.message.reply_text(
            "Доступные команды:\n"
            "/start - Настроить бота\n"
            "/help - Показать это сообщение"
        )
        logger.debug(
            f"Help command received from user {display_user(user)} in configured group {display_chat(chat)}."
        )
    else:
        await update.message.reply_text(
            "Я не настроен для работы в этой группе. Используйте /start, чтобы настроить меня."
        )
        logger.debug(
            f"Help command received from user {display_user(user)} in unconfigured group {display_chat(chat)}."
        )

@with_update_id
async def user_command(update: Update, context: CallbackContext) -> None:
    """Команда /user <id>: только в личке с админом; показывает состояние пользователя."""
    user = update.effective_user
    chat = update.effective_chat
    if chat.type != 'private':
        await update.message.reply_text("Эта команда доступна только в личке.")
        logger.debug("/user invoked outside private chat")
        return
    if not ADMIN_TELEGRAM_ID or str(user.id) != str(ADMIN_TELEGRAM_ID):
        await update.message.reply_text("Только администратор может использовать эту команду.")
        logger.debug("/user invoked by non-admin in private chat")
        return
    args = (update.message.text or '').strip().split()
    if len(args) < 2:
        await update.message.reply_text("Использование: /user <telegram_id>")
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await update.message.reply_text("Неверный формат ID.")
        return
    repo = get_user_state_repo()
    is_spammer = repo.is_spammer(target_id)
    is_seen_any = repo.is_seen(target_id)
    is_suspicious = repo.is_suspicious(target_id)
    spam_groups = groups_where_spammer(target_id)
    status_lines = [
        f"User: {target_id}",
        f"Spammer: {'YES' if is_spammer else 'NO'}", 
        f"Seen anywhere: {'YES' if is_seen_any else 'NO'}",
        f"Suspicious: {'YES' if is_suspicious else 'NO'}",
        f"Spam groups: {', '.join(map(str, spam_groups)) if spam_groups else 'None'}"
    ]
    await update.message.reply_text("\n".join(status_lines))
    logger.debug(f"Admin inspected user {target_id} via /user command")

@with_update_id
async def unban_command(update: Update, context: CallbackContext) -> None:
    """Команда /unban <id>: глобальная очистка spam-флага (админ в личке)."""
    user = update.effective_user
    chat = update.effective_chat
    if chat.type != 'private':
        await update.message.reply_text("Эта команда доступна только в личке.")
        logger.debug("/unban invoked outside private chat")
        return
    if not ADMIN_TELEGRAM_ID or str(user.id) != str(ADMIN_TELEGRAM_ID):
        await update.message.reply_text("Только администратор может использовать эту команду.")
        logger.debug("/unban invoked by non-admin in private chat")
        return
    args = (update.message.text or '').strip().split()
    if len(args) < 2:
        await update.message.reply_text("Использование: /unban <telegram_id>")
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await update.message.reply_text("Неверный формат ID.")
        return
    repo = get_user_state_repo()
    spam_groups = groups_where_spammer(target_id)
    if not spam_groups:
        await update.message.reply_text("Пользователь не помечен как спамер.")
        logger.debug(f"/unban on non-spammer {target_id}")
        return
    cleared = []
    for gid in list(spam_groups):
        try:
            repo.clear_spammer(target_id, gid)
            cleared.append(gid)
        except Exception:
            logger.exception(f"Failed to clear spammer flag for user {target_id} in group {gid}")
    # After clearing, re-evaluate global spam cache
    remaining = groups_where_spammer(target_id)
    if not remaining:
        from .database import spammers_cache, not_spammers_cache
        if target_id in spammers_cache:
            spammers_cache.discard(target_id)
        not_spammers_cache.add(target_id)
    await update.message.reply_text(f"Очищены флаги спама в группах: {', '.join(map(str, cleared)) if cleared else 'None'}")
    from .logging_setup import log_event
    log_event('admin_global_unban', target_user_id=target_id, cleared_groups=cleared)
    logger.debug(f"/unban cleared spam flags for {target_id} in {cleared}")
