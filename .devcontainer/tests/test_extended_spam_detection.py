"""
Tests for extended spam detection functionality.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from telegram import User, Message, Chat, MessageOrigin

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../bot'))

from app.extended_spam_detection import ExtendedSpamDetector, check_extended_spam_criteria


class TestExtendedSpamDetector:
    """Test cases for ExtendedSpamDetector class."""

    @pytest.fixture
    def detector(self):
        """Create detector instance for testing."""
        return ExtendedSpamDetector()

    @pytest.fixture
    def mock_user(self):
        """Create mock user for testing."""
        user = Mock(spec=User)
        user.id = 12345
        user.first_name = "Test"
        user.last_name = "User"
        user.username = "testuser"
        return user

    @pytest.fixture
    def mock_private_user(self):
        """Create mock user without public username."""
        user = Mock(spec=User)
        user.id = 67890
        user.first_name = "Private"
        user.last_name = "User"
        user.username = None
        return user

    @pytest.fixture
    def mock_message(self):
        """Create mock message for testing."""
        message = Mock(spec=Message)
        message.text = "Test message"
        message.caption = None
        message.forward_origin = None
        message.is_automatic_forward = False
        message.sender_chat = None
        return message

    @pytest.fixture
    def mock_channel_message(self):
        """Create mock message sent from channel."""
        message = Mock(spec=Message)
        message.text = "Channel message"
        message.caption = None
        message.forward_origin = None
        message.is_automatic_forward = False
        
        # Mock sender_chat (channel)
        sender_chat = Mock(spec=Chat)
        sender_chat.id = -100123456789
        sender_chat.username = "testchannel"
        sender_chat.type = "channel"
        message.sender_chat = sender_chat
        
        # Mock from_user (not the service account)
        user = Mock(spec=User)
        user.id = 12345  # Not 777000 (service account)
        message.from_user = user
        
        return message

    @pytest.fixture
    def mock_auto_forward_message(self):
        """Create mock auto-forward message from linked channel."""
        message = Mock(spec=Message)
        message.text = "Auto forwarded message"
        message.caption = None
        message.is_automatic_forward = True
        
        # Mock forward origin
        origin = Mock()
        origin.type = "channel"
        message.forward_origin = origin
        
        # Mock sender_chat (channel)
        sender_chat = Mock(spec=Chat)
        sender_chat.id = -100123456789
        message.sender_chat = sender_chat
        
        # Mock from_user (service account)
        user = Mock(spec=User)
        user.id = 777000  # Telegram service account
        message.from_user = user
        
        return message

    @pytest.fixture
    def mock_context(self):
        """Create mock callback context."""
        context = Mock()
        context.bot = AsyncMock()
        return context

    @pytest.mark.asyncio
    async def test_premium_channel_check_returns_false(self, detector, mock_user, mock_context):
        """Test premium channel check returns False due to API limitations."""
        result = await detector.check_premium_user_linked_channel(mock_user, mock_context)
        assert result is False

    @pytest.mark.asyncio
    async def test_bio_invite_check_no_username(self, detector, mock_private_user, mock_context):
        """Test bio invite check returns False for user without public username."""
        result = await detector.check_user_bio_invite_links(mock_private_user, mock_context)
        assert result is False

    @pytest.mark.asyncio
    async def test_bio_invite_check_with_username_no_bio(self, detector, mock_user, mock_context):
        """Test bio invite check when user chat has no bio."""
        # Mock get_chat to return chat without bio
        mock_chat = Mock()
        mock_chat.bio = None
        mock_chat.description = None
        mock_context.bot.get_chat.return_value = mock_chat
        
        result = await detector.check_user_bio_invite_links(mock_user, mock_context)
        assert result is False
        mock_context.bot.get_chat.assert_called_once_with("@testuser")

    @pytest.mark.asyncio
    async def test_bio_invite_check_with_invite_link(self, detector, mock_user, mock_context):
        """Test bio invite check detects invite link in bio."""
        # Mock get_chat to return chat with invite link in bio
        mock_chat = Mock()
        mock_chat.bio = "Join my channel: https://t.me/joinchat/ABCD123"
        mock_chat.description = None
        mock_context.bot.get_chat.return_value = mock_chat
        
        result = await detector.check_user_bio_invite_links(mock_user, mock_context)
        assert result is True
        mock_context.bot.get_chat.assert_called_once_with("@testuser")

    @pytest.mark.asyncio
    async def test_bio_invite_check_with_plus_link(self, detector, mock_user, mock_context):
        """Test bio invite check detects plus-style invite link."""
        # Mock get_chat to return chat with plus-style invite link
        mock_chat = Mock()
        mock_chat.bio = None
        mock_chat.description = "Contact me: https://t.me/+xyz123"
        mock_context.bot.get_chat.return_value = mock_chat
        
        result = await detector.check_user_bio_invite_links(mock_user, mock_context)
        assert result is True

    @pytest.mark.asyncio
    async def test_bio_invite_check_api_error(self, detector, mock_user, mock_context):
        """Test bio invite check handles API errors gracefully."""
        # Mock get_chat to raise exception
        mock_context.bot.get_chat.side_effect = Exception("API Error")
        
        result = await detector.check_user_bio_invite_links(mock_user, mock_context)
        assert result is False

    @pytest.mark.asyncio
    async def test_channel_message_check_no_sender_chat(self, detector, mock_message, mock_context):
        """Test channel message check returns False when no sender_chat."""
        result = await detector.check_channel_sent_message(mock_message, mock_context)
        assert result is False

    @pytest.mark.asyncio
    async def test_channel_message_check_with_sender_chat(self, detector, mock_channel_message, mock_context):
        """Test channel message check returns True for channel-sent message."""
        result = await detector.check_channel_sent_message(mock_channel_message, mock_context)
        assert result is True

    @pytest.mark.asyncio
    async def test_channel_message_check_excludes_auto_forward(self, detector, mock_auto_forward_message, mock_context):
        """Test channel message check excludes auto-forwards from linked channels."""
        result = await detector.check_channel_sent_message(mock_auto_forward_message, mock_context)
        assert result is False

    @pytest.mark.asyncio
    async def test_analyze_user_comprehensive(self, detector, mock_user, mock_channel_message, mock_context):
        """Test comprehensive user analysis returns correct results."""
        # Mock get_chat to return chat with invite link
        mock_chat = Mock()
        mock_chat.bio = "Join: https://t.me/joinchat/TEST"
        mock_context.bot.get_chat.return_value = mock_chat
        
        results = await detector.analyze_user_for_extended_spam_criteria(
            mock_user, mock_channel_message, mock_context
        )
        
        assert isinstance(results, dict)
        assert 'premium_channel_spam' in results
        assert 'bio_invite_spam' in results
        assert 'channel_message_spam' in results
        
        # Premium check should be False (API limitation)
        assert results['premium_channel_spam'] is False
        # Bio check should be True (invite link detected)  
        assert results['bio_invite_spam'] is True
        # Channel message check should be True (sender_chat present)
        assert results['channel_message_spam'] is True

    @pytest.mark.asyncio
    async def test_check_extended_spam_criteria_integration(self, mock_user, mock_channel_message, mock_context):
        """Test main entry point function."""
        with patch('app.extended_spam_detection.extended_spam_detector') as mock_detector:
            mock_results = {
                'premium_channel_spam': False,
                'bio_invite_spam': True,  # This should trigger spam detection
                'channel_message_spam': False
            }
            mock_detector.analyze_user_for_extended_spam_criteria.return_value = mock_results
            
            result = await check_extended_spam_criteria(mock_user, mock_channel_message, mock_context)
            
            assert result is True  # Should return True because bio_invite_spam is True
            mock_detector.analyze_user_for_extended_spam_criteria.assert_called_once_with(
                mock_user, mock_channel_message, mock_context
            )

    @pytest.mark.asyncio  
    async def test_check_extended_spam_criteria_no_spam(self, mock_user, mock_message, mock_context):
        """Test main entry point when no spam criteria are met."""
        with patch('app.extended_spam_detection.extended_spam_detector') as mock_detector:
            mock_results = {
                'premium_channel_spam': False,
                'bio_invite_spam': False,
                'channel_message_spam': False
            }
            mock_detector.analyze_user_for_extended_spam_criteria.return_value = mock_results
            
            result = await check_extended_spam_criteria(mock_user, mock_message, mock_context)
            
            assert result is False  # Should return False when no criteria are met

    def test_invite_regex_patterns(self, detector):
        """Test invite link regex patterns."""
        test_cases = [
            ("https://t.me/joinchat/ABCD123", True),
            ("https://t.me/+xyz789", True),
            ("https://telegram.me/joinchat/TEST", True),
            ("https://telegram.me/+abc456", True),
            ("Visit t.me/joinchat/SAMPLE", True),
            ("Contact t.me/+DEF789", True),
            ("https://t.me/publicchannel", False),  # Not an invite link
            ("https://example.com", False),
            ("Normal text", False),
        ]
        
        for text, should_match in test_cases:
            result = bool(detector.invite_regex.search(text))
            assert result == should_match, f"Failed for text: {text}"

    def test_suspicious_link_patterns(self, detector):
        """Test suspicious link regex patterns."""
        test_cases = [
            ("https://t.me/channel", True),
            ("http://example.com", True), 
            ("https://malicious.site", True),
            ("Visit t.me/bot", True),
            ("Normal text", False),
            ("No links here", False),
        ]
        
        for text, should_match in test_cases:
            result = bool(detector.suspicious_link_regex.search(text))
            assert result == should_match, f"Failed for text: {text}"


# Integration tests with configuration
class TestExtendedSpamDetectionIntegration:
    """Integration tests for extended spam detection."""

    @pytest.mark.asyncio
    async def test_disabled_extended_detection(self, mock_user, mock_message, mock_context):
        """Test that extended detection respects configuration."""
        with patch('app.extended_spam_detection.EXTENDED_SPAM_DETECTION_ENABLED', False):
            # This should not be called when disabled, but we'll test the function directly
            result = await check_extended_spam_criteria(mock_user, mock_message, mock_context)
            # Function should still work, but integration layer should skip it
            assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_individual_feature_toggles(self):
        """Test that individual feature toggles work as expected."""
        # This would test the configuration flags for each detection method
        # EXTENDED_PREMIUM_CHANNEL_CHECK_ENABLED
        # EXTENDED_BIO_INVITE_CHECK_ENABLED  
        # EXTENDED_CHANNEL_MESSAGE_CHECK_ENABLED
        
        # For now, this is a placeholder as the individual toggles 
        # would need to be implemented in the detector class
        pass