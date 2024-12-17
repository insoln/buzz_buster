from telegram import User, Chat

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
