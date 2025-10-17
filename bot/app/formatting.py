from telegram import User, Chat  # type: ignore


def display_user(user) -> str:
    """Display user information as a string."""
    uid = getattr(user, 'id', None)
    first = getattr(user, 'first_name', '') or ''
    last = getattr(user, 'last_name', '') or ''
    uname = getattr(user, 'username', None)
    result = f"#{uid} {first} {last}".strip()
    if uname:
        result = f"{result} (@{user.username})"
    return result

def display_chat(chat) -> str:
    """Display chat information as a string."""
    cid = getattr(chat, 'id', None)
    title = getattr(chat, 'title', '') or ''
    uname = getattr(chat, 'username', None)
    result = f"#{cid} {title}".strip()
    if uname:
        result = f"{result} (@{uname})"
    return result
