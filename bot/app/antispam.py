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
        logger.exception(f"Error checking CAS for user_id {user_id}: {e}")
        return False
    
async def check_lols_ban(user_id: int) -> dict:
    """Проверка пользователя по базе lols.bot."""
    url = f"https://lols.bot/account?id={user_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()
                return data.get("ok", False)
    except Exception as e:
        logger.exception(f"Error checking lols.bot for user_id {user_id}: {e}")
        return False


async def check_openai_spam(message, instructions) -> bool:
    """Проверка текста на спам с помощью OpenAI."""
    logger.debug(f"Checking message for spam:{instructions}\n{message}")
    # Создаем улучшенный промпт для OpenAI
    system_prompt = f"""Ты - эксперт по обнаружению спама в групповых чатах. Твоя задача - точно определить, является ли данное сообщение спамом.

ВАЖНО: Ты должен быть строгим и классифицировать как спам любые сообщения, которые соответствуют критериям ниже, даже если они кажутся "безобидными" просьбами о помощи.

КРИТЕРИИ СПАМА:
{instructions}

ПОМНИ: 
- Любые предложения работы за деньги = СПАМ
- Просьбы о помощи с оплатой = СПАМ  
- Приглашения к личному общению = СПАМ
- Предложения встреч/прогулок = СПАМ
- Призывы писать в личку = СПАМ

Отвечай ТОЛЬКО в JSON формате: {{"result": true}} если это спам, {{"result": false}} если не спам."""

    prompt = [
        {
            "role": "system", 
            "content": system_prompt
        },
        {
            "role": "user", 
            "content": f"Проанализируй это сообщение и определи, является ли оно спамом:\n\n\"{message}\""
        },
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
