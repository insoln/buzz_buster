import json
from types import SimpleNamespace
import pytest
import app.antispam as antispam
from app.config import INSTRUCTIONS_DEFAULT_TEXT


@pytest.fixture(autouse=True)
def mock_external(monkeypatch):
    # Mock OpenAI chat completion
    class FakeChatCompletions:
        def create(self, model, messages, response_format):  # type: ignore[override]
            user_msg = next(m for m in messages if m["role"] == "user") if isinstance(messages, list) else messages[-1]
            # support both dict-like and object params
            content = getattr(user_msg, "content", "") if not isinstance(user_msg, dict) else user_msg.get("content", "")
            is_spam = "spam" in content.lower()
            result = json.dumps({"result": is_spam})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=result))])

    # Attach fake completions object
    monkeypatch.setattr(antispam.openai, "chat", SimpleNamespace(completions=FakeChatCompletions()))

    # Mock aiohttp ClientSession for CAS
    class FakeResponse:
        def __init__(self, url):
            self._url = url
        async def json(self):
            # parse user_id param
            try:
                user_part = self._url.split("user_id=")[1]
                uid = int(user_part)
            except Exception:
                uid = 0
            return {"ok": uid in {7609784265, 42}}
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        def get(self, url):
            return FakeResponse(url)

    monkeypatch.setattr(antispam.aiohttp, "ClientSession", lambda: FakeSession())
    yield


@pytest.mark.asyncio
async def test_openai_ham():
    assert await antispam.check_openai_spam("This is a normal message", INSTRUCTIONS_DEFAULT_TEXT) is False


@pytest.mark.asyncio
async def test_openai_spam():
    assert await antispam.check_openai_spam("This is a spam OFFER", INSTRUCTIONS_DEFAULT_TEXT) is True


@pytest.mark.asyncio
async def test_cas_ban_ham():
    assert await antispam.check_cas_ban(1) is False


@pytest.mark.asyncio
async def test_cas_ban_spam():
    assert await antispam.check_cas_ban(7609784265) is True
