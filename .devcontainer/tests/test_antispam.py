from app.antispam import check_cas_ban, check_openai_spam
from app.config import INSTRUCTIONS_DEFAULT_TEXT
import pytest

@pytest.mark.asyncio
async def test_openai_ham():
    assert await check_openai_spam("This is a normal message",INSTRUCTIONS_DEFAULT_TEXT) == False

@pytest.mark.asyncio
async def test_openai_spam():
    assert await check_openai_spam("This is a spam message",INSTRUCTIONS_DEFAULT_TEXT) == True

@pytest.mark.asyncio
async def test_cas_ban_ham():
    assert await check_cas_ban(1) == False
    
@pytest.mark.asyncio
async def test_cas_ban_spam():
    assert await check_cas_ban(7609784265) == True
