import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import json
import os
import sys

# Mock the logging setup to avoid file creation issues
sys.modules['app.logging_setup'] = MagicMock()

from app.antispam import check_openai_spam
from app.config import INSTRUCTIONS_DEFAULT_TEXT

# Test the improved prompt structure without making actual API calls
@pytest.mark.asyncio
async def test_improved_prompt_structure():
    """Test that the improved prompt structure is correctly formatted."""
    
    # Mock the OpenAI API response
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = '{"result": true}'
    
    with patch('app.antispam.openai.chat.completions.create', return_value=mock_response) as mock_create:
        message = "Ищу мужа на час, не сложная помощь по дому"
        result = await check_openai_spam(message, INSTRUCTIONS_DEFAULT_TEXT)
        
        # Verify the API was called
        assert mock_create.called
        
        # Get the call arguments
        call_args = mock_create.call_args
        messages = call_args.kwargs['messages']
        
        # Verify the improved prompt structure
        assert len(messages) == 2
        assert messages[0]['role'] == 'system'
        assert messages[1]['role'] == 'user'
        
        # Verify key phrases are in the system message
        system_content = messages[0]['content']
        assert 'эксперт по обнаружению спама' in system_content
        assert 'должен быть строгим' in system_content
        assert 'Любые предложения работы за деньги = СПАМ' in system_content
        assert 'JSON формате' in system_content
        
        # Verify the user message contains the actual message
        user_content = messages[1]['content']
        assert message in user_content
        assert 'Проанализируй это сообщение' in user_content
        
        # Verify the response is parsed correctly
        assert result == True

@pytest.mark.asyncio 
async def test_json_parsing_error_handling():
    """Test that JSON parsing errors are handled gracefully."""
    
    # Mock invalid JSON response
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = 'invalid json response'
    
    with patch('app.antispam.openai.chat.completions.create', return_value=mock_response):
        result = await check_openai_spam("test message", INSTRUCTIONS_DEFAULT_TEXT)
        
        # Should return False when JSON parsing fails
        assert result == False

@pytest.mark.asyncio
async def test_instructions_integration():
    """Test that custom instructions are properly integrated into the prompt."""
    
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = '{"result": false}'
    
    custom_instructions = "Только сообщения про котиков считаются спамом"
    
    with patch('app.antispam.openai.chat.completions.create', return_value=mock_response) as mock_create:
        await check_openai_spam("test message", custom_instructions)
        
        # Verify custom instructions are included in the system prompt
        call_args = mock_create.call_args
        system_content = call_args.kwargs['messages'][0]['content']
        assert custom_instructions in system_content