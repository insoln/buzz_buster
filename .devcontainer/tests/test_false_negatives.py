import pytest
import os
from app.antispam import check_openai_spam
from app.config import INSTRUCTIONS_DEFAULT_TEXT

# Test cases for the specific false negative examples from the issue
FALSE_NEGATIVE_EXAMPLES = [
    "Привет, кто сможет помочь закончить ремонт? Уже нет сил самой делать его. Заплачу 5000",
    "Срочно требуется помощь сегодня завтра, 8600 рублей..",
    "Приветик ) У кого есть желание поговорить, или выйти пройтись пишите",
    "требуются 2 человека на выгрузку коробок из машины, два часа работы, заплачу каждому по 3000р",
    "Ищу мужа на час, не сложная помощь по дому"
]

# Some legitimate messages that should NOT be spam
LEGITIMATE_EXAMPLES = [
    "Привет! Как дела? Обсуждаем новую технологию в нашей сфере",
    "Интересная статья по нашей тематике, что думаете?",
    "Кто-нибудь пробовал новый фреймворк? Поделитесь опытом",
    "Спасибо за информацию, очень полезно!",
    "Где можно найти документацию по этой теме?"
]

@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OpenAI API key not provided")
async def test_false_negative_examples():
    """Test that known spam examples are correctly identified as spam."""
    for message in FALSE_NEGATIVE_EXAMPLES:
        result = await check_openai_spam(message, INSTRUCTIONS_DEFAULT_TEXT)
        assert result == True, f"Message should be identified as spam: '{message}'"

@pytest.mark.asyncio 
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OpenAI API key not provided")
async def test_legitimate_examples():
    """Test that legitimate messages are not identified as spam."""
    for message in LEGITIMATE_EXAMPLES:
        result = await check_openai_spam(message, INSTRUCTIONS_DEFAULT_TEXT)
        assert result == False, f"Message should NOT be identified as spam: '{message}'"