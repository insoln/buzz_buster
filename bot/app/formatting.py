from telegram import User, Chat


def display_user(user: User) -> str:
    """Display user information as a string."""
    result = f"#{user.id} {user.first_name or ''} {user.last_name or ''}".strip()
    if user.username:
        result = f"{result} (@{user.username})"
    return result


def display_chat(chat: Chat) -> str:
    """Display chat information as a string."""
    result = f"#{chat.id} {chat.title or ''}".strip()
    if chat.username:
        result = f"{result} (@{chat.username})"
    return result
