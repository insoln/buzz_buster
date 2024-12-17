import openai
from .logging_setup import logger
import aiohttp
from .config import *
from .formatting import display_chat, display_user
import json


async def check_cas_ban(user_id: int) -> bool:
    """Проверка пользователя по базе CAS (Combot Anti-Spam)."""
    url = f"https://api.cas.chat/check?user_id={user_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                return data.get("ok", False)
    except Exception as e:
        logger.exception(f"Error checking CAS ban for user {user_id}: {e}")
        return False


async def check_openai_spam(message, instructions) -> bool:
    """Проверка текста на спам с помощью OpenAI."""
    logger.debug(f"Checking message for spam:{instructions}\n{message}")
    # Создаем промпт для OpenAI
    prompt = [
        {
            "role": "system",
            "content": f"Является ли спамом сообщение от пользователя? Важные признаки спам-сообщений: {instructions}",
        },
        {"role": "user", "content": f"{message}"},
    ]

    try:
        response = openai.chat.completions.create(
            model=MODEL_NAME,
            messages=prompt,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "boolean",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"result": {"type": "boolean"}},
                        "required": ["result"],
                        "additionalProperties": False,
                    },
                },
            }
        )
        reply = response.choices[0].message.content
        logger.debug(f"OpenAI response: {reply}")
        result = json.loads(reply)
        is_spam = result.get("result", False)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse OpenAI response: {e}")
        is_spam = False
    return is_spam

# Настройка OpenAI
openai.api_key = OPENAI_API_KEY
