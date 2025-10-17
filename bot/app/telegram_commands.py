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
    user = getattr(update, 'effective_user', None)
    message = getattr(update, 'message', None)
    if user is None or message is None:
        return

    # Проверяем, что это администратор
    if not ADMIN_TELEGRAM_ID or str(user.id) != str(ADMIN_TELEGRAM_ID):
        try:
            await message.reply_text("Эта команда доступна только администратору.")
        except Exception:
            pass
        return

    if not SENTRY_AVAILABLE or not SENTRY_DSN:
        try:
            await message.reply_text("Sentry не настроен или недоступен.")
        except Exception:
            pass
        return

    if SENTRY_AVAILABLE and SENTRY_DSN:
        # Local alias for static analyzers (guaranteed import success under SENTRY_AVAILABLE)
        from sentry_sdk import capture_message as _capture_message, push_scope as _push_scope, capture_exception as _capture_exception
        try:
            try:
                await message.reply_text("Тестирую Sentry интеграцию...")
            except Exception:
                pass
            _capture_message("Test message from Telegram bot", level="info")
            with _push_scope() as scope:
                scope.set_tag("test_type", "telegram_command")
                scope.set_user({"id": user.id, "username": getattr(user, 'username', None)})
                scope.set_extra("command", "/test_sentry")
                _capture_message("Test message with context", level="warning")
            try:
                _ = 1 / 0  # intentional
            except ZeroDivisionError as e:
                _capture_exception(e)
            try:
                await message.reply_text("✅ Sentry тест завершен! Проверьте dashboard Sentry.")
            except Exception:
                pass
            logger.info(f"Sentry test executed by admin {display_user(user)}")
        except Exception as e:
            try:
                await message.reply_text(f"❌ Ошибка при тестировании Sentry: {e}")
            except Exception:
                pass
            logger.exception("Error during Sentry test")
    else:
        try:
            await message.reply_text("Sentry не настроен или недоступен.")
        except Exception:
            pass


@with_update_id
async def start_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /start."""
    # update_id set by decorator
    chat = getattr(update, 'effective_chat', None)
    user = getattr(update, 'effective_user', None)
    message = getattr(update, 'message', None)
    if chat is None or user is None or message is None:
        # Nothing to do if essentials missing
        return
    logger.debug(
        f"Handling /start command from user {display_user(user)} in chat {display_chat(chat)}"
    )

    if getattr(chat, 'type', None) == "private":
        # Если пользователь глобально помечен спамером – показать персональный отчёт
        from .database import groups_where_spammer
        from .logging_setup import log_event
        repo = get_user_state_repo()
        spam_groups = groups_where_spammer(user.id)
        if spam_groups:
            # Дудос-защита: детальную информацию (админы + инвайт) показываем только для первой группы.
            # Остальные группы перечисляем текстово без запросов get_chat_administrators / create_chat_invite_link.
            # TODO(future): кэшировать админов и инвайты.
            first_gid = spam_groups[0]
            title_first = str(first_gid)
            invite_first = None
            admins_first = []
            try:
                chat_obj = await context.bot.get_chat(first_gid)
                if getattr(chat_obj, 'title', None):
                    title_first = chat_obj.title
                # Первой группе делаем попытку ограниченного инвайта
                try:
                    invite_payload = await context.bot.create_chat_invite_link(first_gid, member_limit=1)
                    invite_first = getattr(invite_payload, 'invite_link', None)
                except Exception:
                    try:
                        invite_first = await context.bot.export_chat_invite_link(first_gid)
                    except Exception:
                        invite_first = None
                try:
                    admins = await context.bot.get_chat_administrators(first_gid)
                    for adm in admins:
                        u = getattr(adm, 'user', None)
                        if not u:
                            continue
                        # Фильтруем ботов
                        if getattr(u, 'is_bot', False):
                            continue
                        # Проверяем право на разбан (restrict/ban members) или создатель
                        can_restrict = False
                        try:
                            can_restrict = bool(getattr(adm, 'can_restrict_members', False)) or getattr(adm, 'status', '') == 'creator'
                        except Exception:
                            can_restrict = False
                        if not can_restrict:
                            continue
                        uname = f"@{u.username}" if getattr(u, 'username', None) else f"id:{u.id}"
                        admins_first.append(uname)
                except Exception:
                    pass
            except Exception:
                title_first = f"{first_gid} (не удалось получить информацию)"
            admins_part = ", ".join(admins_first) if admins_first else "(нет админов с правом разбана)"
            if invite_first:
                first_line = f"• <a href=\"{invite_first}\">{title_first}</a> — админы: {admins_part}"
            else:
                first_line = f"• {title_first} — админы: {admins_part} (нет ссылки)"
            remaining_count = len(spam_groups) - 1
            if remaining_count > 0:
                others_line = f"Ещё групп со статусом спамера: {remaining_count}. (детали скрыты для защиты от перегрузки)"
            else:
                others_line = "Больше групп со статусом спамера нет."
            lines = [
                "Вы помечены как спамер.",
                first_line,
                others_line,
                "",
                "Свяжитесь с администраторами первой группы (и остальных, если нужно) и попросите снять метку. После удаления статуса во всех группах репутация будет полностью восстановлена."
            ]
            msg_html = "\n".join(lines)
            try:
                await message.reply_text(msg_html, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                # Фолбэк без HTML
                try:
                    await message.reply_text("\n".join([l.replace('<', '').replace('>', '') for l in lines]))
                except Exception:
                    pass
            log_event('private_spam_summary', user_id=user.id, spam_groups=spam_groups, groups_count=len(spam_groups), first_group_id=first_gid)
            return
        else:
            try:
                await message.reply_text("Вы не помечены как спамер. Этот бот предназначен для работы в группах.")
            except Exception:
                pass
            logger.debug("Received /start in private chat (clean user).")
            return

    try:
        chat_member = await context.bot.get_chat_member(chat.id, user.id)
        user_status = getattr(chat_member, 'status', None)
    except Exception as e:
        logger.exception(f"Failed to get chat member status for user {display_user(user)} in chat {display_chat(chat)}: {e}")
        user_status = None
    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        bot_status = getattr(bot_member, 'status', None)
    except Exception as e:
        logger.exception(f"Failed to get bot's status in chat {display_chat(chat)}: {e}")
        bot_status = None
    if bot_status not in ["administrator", "creator"]:
        try:
            await message.reply_text("Мне нужны права администратора в этой группе.")
        except Exception:
            pass
        logger.debug(f"Bot is not an admin in group {display_chat(chat)}.")
        return
    if user_status not in ["administrator", "creator"]:
        try:
            await message.reply_text("Только администраторы могут настраивать бота.")
        except Exception:
            pass
        logger.debug(f"User {display_user(user)} tried to configure group {display_chat(chat)} but they're not admin.")
        return
    if is_group_configured(chat.id):
        try:
            await message.reply_text("Бот уже настроен для этой группы. Используйте /help, чтобы увидеть доступные команды.")
        except Exception:
            pass
        logger.debug(f"User {display_user(user)} tried to configure group {display_chat(chat)}, but this group is already configured.")
        return
    await add_configured_group(update)


@with_update_id
async def help_command(update: Update, context: CallbackContext) -> None:
    """Обработка команды /help."""
    # update_id set by decorator
    chat = getattr(update, 'effective_chat', None)
    user = getattr(update, 'effective_user', None)
    message = getattr(update, 'message', None)
    if chat is None or user is None or message is None:
        return
    logger.debug(f"Handling /help command from user {display_user(user)} in chat {display_chat(chat)}")

    if getattr(chat, 'type', None) == "private":
        try:
            await message.reply_text("Этот бот предназначен только для групп.")
        except Exception:
            pass
        logger.debug(
            f"Received /help in private chat from user {display_user(user)} in chat {display_chat(chat)}"
        )
        return

    chat_id = getattr(update, 'effective_chat', None)
    chat_id = getattr(chat_id, 'id', None)
    if chat_id is None:
        return

    if is_group_configured(chat_id):
        try:
            await message.reply_text(
                "Доступные команды:\n"
                "/start - Настроить бота\n"
                "/help - Показать это сообщение"
            )
        except Exception:
            pass
        logger.debug(
            f"Help command received from user {display_user(user)} in configured group {display_chat(chat)}."
        )
    else:
        try:
            await message.reply_text(
                "Я не настроен для работы в этой группе. Используйте /start, чтобы настроить меня."
            )
        except Exception:
            pass
        logger.debug(
            f"Help command received from user {display_user(user)} in unconfigured group {display_chat(chat)}."
        )

@with_update_id
async def user_command(update: Update, context: CallbackContext) -> None:
    """Команда /user <id>: только в личке с админом; показывает состояние пользователя."""
    user = getattr(update, 'effective_user', None)
    chat = getattr(update, 'effective_chat', None)
    message = getattr(update, 'message', None)
    if user is None or chat is None or message is None:
        return
    if getattr(chat, 'type', None) != 'private':
        try:
            await message.reply_text("Эта команда доступна только в личке.")
        except Exception:
            pass
        logger.debug("/user invoked outside private chat")
        return
    if not ADMIN_TELEGRAM_ID or str(getattr(user, 'id', '')) != str(ADMIN_TELEGRAM_ID):
        try:
            await message.reply_text("Только администратор может использовать эту команду.")
        except Exception:
            pass
        logger.debug("/user invoked by non-admin in private chat")
        return
    args = (getattr(message, 'text', '') or '').strip().split()
    if len(args) < 2:
        try:
            await message.reply_text("Использование: /user <telegram_id>")
        except Exception:
            pass
        return
    try:
        target_id = int(args[1])
    except ValueError:
        try:
            await message.reply_text("Неверный формат ID.")
        except Exception:
            pass
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
    try:
        await message.reply_text("\n".join(status_lines))
    except Exception:
        pass
    logger.debug(f"Admin inspected user {target_id} via /user command")

@with_update_id
async def unban_command(update: Update, context: CallbackContext) -> None:
    """Команда /unban <id>: глобальная очистка spam-флага (админ в личке)."""
    user = getattr(update, 'effective_user', None)
    chat = getattr(update, 'effective_chat', None)
    message = getattr(update, 'message', None)
    if user is None or chat is None or message is None:
        return
    if getattr(chat, 'type', None) != 'private':
        try:
            await message.reply_text("Эта команда доступна только в личке.")
        except Exception:
            pass
        logger.debug("/unban invoked outside private chat")
        return
    if not ADMIN_TELEGRAM_ID or str(getattr(user, 'id', '')) != str(ADMIN_TELEGRAM_ID):
        try:
            await message.reply_text("Только администратор может использовать эту команду.")
        except Exception:
            pass
        logger.debug("/unban invoked by non-admin in private chat")
        return
    args = (getattr(message, 'text', '') or '').strip().split()
    if len(args) < 2:
        try:
            await message.reply_text("Использование: /unban <telegram_id>")
        except Exception:
            pass
        return
    try:
        target_id = int(args[1])
    except ValueError:
        try:
            await message.reply_text("Неверный формат ID.")
        except Exception:
            pass
        return
    repo = get_user_state_repo()
    spam_groups = groups_where_spammer(target_id)
    if not spam_groups:
        try:
            await message.reply_text("Пользователь не помечен как спамер.")
        except Exception:
            pass
        logger.debug(f"/unban on non-spammer {target_id}")
        return
    cleared = []
    for gid in list(spam_groups):
        try:
            repo.clear_spammer(target_id, gid)
            # Mark user as seen in each group we cleared spam flag for (восстановление доверия)
            try:
                repo.mark_seen(target_id, gid)
            except Exception:
                pass
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
    try:
        await message.reply_text(f"Очищены флаги спама в группах: {', '.join(map(str, cleared)) if cleared else 'None'}")
    except Exception:
        pass
    from .logging_setup import log_event
    log_event('admin_global_unban', target_user_id=target_id, cleared_groups=cleared)
    logger.debug(f"/unban cleared spam flags for {target_id} in {cleared}")

@with_update_id
async def ban_command(update: Update, context: CallbackContext) -> None:
    """Команда /ban <user_id>@<group_id>: локально пометить пользователя спамером в указанной группе (админ в личке)."""
    admin = getattr(update, 'effective_user', None)
    chat = getattr(update, 'effective_chat', None)
    message = getattr(update, 'message', None)
    if message is None or chat is None or admin is None:
        return
    # Only in private chat
    if getattr(chat, 'type', None) != 'private':
        try:
            await message.reply_text("Эта команда доступна только в личке.")
        except Exception as e:
            logger.error(f"Failed to send reply in /ban (outside private chat): {e}", exc_info=True)
        logger.debug("/ban invoked outside private chat")
        return
    # Admin check
    if not ADMIN_TELEGRAM_ID or str(getattr(admin, 'id', '')) != str(ADMIN_TELEGRAM_ID):
        try:
            await message.reply_text("Только администратор может использовать эту команду.")
        except Exception:
            pass
        logger.debug("/ban invoked by non-admin")
        return
    parts = (getattr(message, 'text', '') or '').strip().split()
    if len(parts) < 2:
        try:
            await message.reply_text("Использование: /ban <user_id>@<group_id>")
        except Exception:
            pass
        return
    token = parts[1]
    if '@' not in token:
        try:
            await message.reply_text("Формат: /ban <user_id>@<group_id>")
        except Exception:
            pass
        return
    user_part, group_part = token.split('@', 1)
    try:
        target_user_id = int(user_part)
        target_group_id = int(group_part)
    except ValueError:
        try:
            await message.reply_text("user_id и group_id должны быть числами.")
        except Exception:
            pass
        return
    # Validate group is configured
    if not is_group_configured(target_group_id):
        try:
            await message.reply_text(
                "Эта группа не настроена или неизвестна. Сначала выполните /start в нужной группе."
            )
        except Exception:
            pass
        logger.debug(f"/ban refused for group {target_group_id}: group not configured")
        return
    from .database import get_user_state_repo
    repo = get_user_state_repo()
    # Пометить как спамера и unseen->spam с доверительным обновлением кэша
    try:
        db_success = bool(repo.mark_spammer(target_user_id, target_group_id))
        # Сразу удалим из suspicious если был
        from .database import suspicious_users_cache
        suspicious_users_cache.discard(target_user_id)
        ban_success = False
        ban_error = None
        # Пытаемся выполнить фактический бан пользователя в указанной группе
        try:
            await context.bot.ban_chat_member(target_group_id, target_user_id)
            ban_success = True
        except Exception as be:
            # Telegram мог вернуть ошибку (нет прав / бот не админ этой группы)
            ban_error = str(be)
        status_bits = []
        status_bits.append("DB=OK" if db_success else "DB=FAIL")
        if ban_success:
            status_bits.append("TG_BAN=OK")
        else:
            status_bits.append("TG_BAN=FAIL")
        try:
            await message.reply_text(
                f"Пользователь {target_user_id} помечен как спамер в группе {target_group_id}. "
                + ("Забанен." if ban_success else "(не удалось забанить)")
                + " [" + ", ".join(status_bits) + "]"
            )
        except Exception:
            pass
        from .logging_setup import log_event
        log_event(
            'admin_force_ban',
            target_user_id=target_user_id,
            target_group_id=target_group_id,
            ban_success=ban_success,
            ban_error=ban_error if ban_error else None,
            db_write_success=db_success,
        )
        logger.debug(
            f"/ban marked user={target_user_id} spammer in group={target_group_id} ban_success={ban_success} ban_error={ban_error}"
        )
    except Exception as e:
        try:
            await message.reply_text(f"Ошибка: {e}")
        except Exception:
            pass
        logger.exception("/ban command failure")


@with_update_id
async def diag_command(update: Update, context: CallbackContext) -> None:
    """Админ-команда /diag <user_id>@<group_id>: диагностика БД и кэшей.

    Выводит строки:
      DB_CONNECT: OK/FAIL
      ENTRY: (seen, spammer) | None | ERROR:...
      IS_SPAMMER_IN_GROUP: bool
      GROUPS_SPAM: [...]
      GLOBAL_CACHE_SPAM / SEEN_ANY / SUSPICIOUS: YES/NO
      DRY_SELECT: OK/FAIL:err
    Также пишет structured лог admin_diag.
    """
    user = getattr(update, 'effective_user', None)
    chat = getattr(update, 'effective_chat', None)
    message = getattr(update, 'message', None)
    if chat is None or user is None or message is None:
        return
    if getattr(chat, 'type', None) != 'private':
        return
    if not ADMIN_TELEGRAM_ID or str(user.id) != str(ADMIN_TELEGRAM_ID):
        return
    parts = (getattr(message, 'text', '') or '').strip().split()
    if len(parts) < 2 or '@' not in parts[1]:
        await message.reply_text("Использование: /diag <user_id>@<group_id>")
        return
    user_part, group_part = parts[1].split('@', 1)
    try:
        target_user_id = int(user_part)
        target_group_id = int(group_part)
    except ValueError:
        await message.reply_text("Неверный формат.")
        return
    repo = get_user_state_repo()
    from .database import spammers_cache, seen_users_cache, suspicious_users_cache
    db_ok = False
    entry = None
    try:
        entry = repo.entry(target_user_id, target_group_id)
        db_ok = True
    except Exception as e:
        entry = f"ERROR:{e}"
    try:
        is_spammer_in_group = repo.is_spammer_in_group(target_user_id, target_group_id)
    except Exception:
        is_spammer_in_group = False
    try:
        spam_groups = repo.groups_with_spam_flag(target_user_id)
    except Exception:
        spam_groups = []
    # Dry connectivity check
    try:
        from .database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close(); conn.close()
        dry = 'OK'
    except Exception as e:
        dry = f"FAIL:{e}"
    lines = [
        f"DB_CONNECT: {'OK' if db_ok else 'FAIL'}",
        f"ENTRY: {entry}",
        f"IS_SPAMMER_IN_GROUP: {is_spammer_in_group}",
        f"GROUPS_SPAM: {spam_groups}",
        f"GLOBAL_CACHE_SPAM: {'YES' if target_user_id in spammers_cache else 'NO'}",
        f"SEEN_ANY: {'YES' if target_user_id in seen_users_cache else 'NO'}",
        f"SUSPICIOUS: {'YES' if target_user_id in suspicious_users_cache else 'NO'}",
        f"DRY_SELECT: {dry}",
    ]
    try:
        await message.reply_text("\n".join(lines))
    except Exception:
        pass
    from .logging_setup import log_event
    log_event('admin_diag', target_user_id=target_user_id, target_group_id=target_group_id,
              db_connect=db_ok, entry=entry, spam_groups=spam_groups,
              is_spammer_in_group=is_spammer_in_group, dry=dry)
