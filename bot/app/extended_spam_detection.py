"""
Extended spam detection module for advanced user and message analysis.

This module implements additional spam detection criteria:
1. Premium users with linked channels containing suspicious content
2. Users with invite links in their bio/description  
3. Messages sent on behalf of channels (excluding auto-forwards)
"""

import re
import aiohttp
from typing import Optional, Dict, Any, List
from telegram import User, Message, Chat
from telegram.ext import CallbackContext
from .logging_setup import logger
from .config import *


class ExtendedSpamDetector:
    """Extended spam detection using Telegram API data analysis."""
    
    def __init__(self):
        # Regex patterns for detecting invite links
        self.invite_patterns = [
            r't\.me/joinchat/[A-Za-z0-9_-]+',
            r't\.me/\+[A-Za-z0-9_-]+',
            r'telegram\.me/joinchat/[A-Za-z0-9_-]+',
            r'telegram\.me/\+[A-Za-z0-9_-]+',
        ]
        
        # Compiled regex for performance
        self.invite_regex = re.compile('|'.join(self.invite_patterns), re.IGNORECASE)
        
        # Suspicious link patterns (for premium channel analysis)
        self.suspicious_link_patterns = [
            r't\.me/[A-Za-z0-9_]+',  # Telegram channels/bots
            r'https?://[^\s]+',      # Any external links
        ]
        self.suspicious_link_regex = re.compile('|'.join(self.suspicious_link_patterns), re.IGNORECASE)

    async def check_premium_user_linked_channel(self, user: User, context: CallbackContext) -> bool:
        """
        Check if premium user has a linked channel with suspicious single message.
        
        Technical limitation: Telegram Bot API doesn't provide direct access to:
        - User's linked channel information 
        - Channel message history (requires channel admin privileges)
        - Premium status of users
        
        Returns False for now due to API limitations, but provides framework for future enhancement.
        """
        try:
            # Note: This is a research implementation showing the intended logic
            # Real implementation would require:
            # 1. MTProto API access (not Bot API) to get user's linked channels
            # 2. Channel admin privileges to read message history
            # 3. Premium status detection (may not be available via Bot API)
            
            logger.debug(f"Premium channel check for user {user.id} - API limitations prevent full implementation")
            
            # Placeholder for future implementation when API access is available
            # if user.is_premium:  # This field may not be available in Bot API
            #     linked_channels = await get_user_linked_channels(user.id)  # Not available in Bot API
            #     for channel in linked_channels:
            #         if await self._is_suspicious_single_message_channel(channel, context):
            #             return True
            
            return False
            
        except Exception as e:
            logger.exception(f"Error checking premium user linked channel for user {user.id}: {e}")
            return False

    async def check_user_bio_invite_links(self, user: User, context: CallbackContext) -> bool:
        """
        Check if user has invite links in their bio/description.
        
        Technical limitation: Telegram Bot API doesn't provide access to user bio/description
        through the standard User object in message events. Bio is only available when:
        - Getting chat member info in channels/supergroups  
        - User has a public username and we can get their chat info
        
        This method attempts to get user bio when possible.
        """
        try:
            # Bot API limitation: User bio is not available in message.from_user
            # Bio is only accessible through getChatMember or getChat for public users
            
            user_bio = None
            
            # Try to get bio if user has a public username
            if hasattr(user, 'username') and user.username:
                try:
                    # This will work only if user has a public username
                    user_chat = await context.bot.get_chat(f"@{user.username}")
                    user_bio = getattr(user_chat, 'bio', None) or getattr(user_chat, 'description', None)
                except Exception as e:
                    logger.debug(f"Could not get bio for @{user.username}: {e}")
            
            if not user_bio:
                logger.debug(f"Bio not accessible for user {user.id} - API limitations")
                return False
            
            # Check for invite links in bio
            if self.invite_regex.search(user_bio):
                logger.info(f"User {user.id} has invite link in bio: {user_bio[:100]}...")
                return True
                
            return False
            
        except Exception as e:
            logger.exception(f"Error checking user bio invite links for user {user.id}: {e}")
            return False

    async def check_channel_sent_message(self, message: Message, context: CallbackContext) -> bool:
        """
        Check if message was sent on behalf of a channel (excluding auto-forwards).
        
        This respects the existing logic that excludes automatic forwards from 
        linked discussion channels (user.id == 777000).
        """
        try:
            if not message:
                return False
            
            # Check if message has sender_chat (indicates channel sending)
            sender_chat = getattr(message, 'sender_chat', None)
            if not sender_chat:
                return False
            
            # Exclude automatic forwards from linked discussion channels
            # (This logic already exists in telegram_messages.py)
            user = message.from_user
            if user and user.id == 777000:
                auto_forward = getattr(message, 'is_automatic_forward', False)
                if auto_forward and message.forward_origin:
                    origin_type = getattr(message.forward_origin, 'type', None)
                    if origin_type == 'channel':
                        logger.debug(f"Skipping auto-forward from linked channel in message analysis")
                        return False
            
            # This is a channel-sent message (not an auto-forward)
            logger.info(f"Message sent on behalf of channel {sender_chat.id} (@{getattr(sender_chat, 'username', 'no_username')})")
            return True
            
        except Exception as e:
            logger.exception(f"Error checking channel sent message: {e}")
            return False

    async def _is_suspicious_single_message_channel(self, channel: Chat, context: CallbackContext) -> bool:
        """
        Helper method to check if a channel has only one suspicious message.
        
        Note: This requires admin access to the channel to read message history,
        which is typically not available for spam detection scenarios.
        """
        try:
            # This would require channel admin privileges to implement
            # For research purposes, showing the intended logic:
            
            # messages = await get_channel_messages(channel.id, limit=2)  # Not available in Bot API
            # if len(messages) == 1:
            #     message_text = messages[0].text or messages[0].caption or ""
            #     if self.suspicious_link_regex.search(message_text):
            #         return True
            
            logger.debug(f"Channel analysis for {channel.id} - requires admin privileges")
            return False
            
        except Exception as e:
            logger.exception(f"Error analyzing channel {channel.id}: {e}")
            return False

    async def analyze_user_for_extended_spam_criteria(self, user: User, message: Message, context: CallbackContext) -> Dict[str, bool]:
        """
        Comprehensive analysis of user against extended spam criteria.
        
        Returns a dictionary with results for each criterion:
        - premium_channel_spam: Premium user with suspicious linked channel
        - bio_invite_spam: User has invite links in bio  
        - channel_message_spam: Message sent on behalf of channel
        """
        results = {
            'premium_channel_spam': False,
            'bio_invite_spam': False,  
            'channel_message_spam': False
        }
        
        try:
            # Check each criterion
            results['premium_channel_spam'] = await self.check_premium_user_linked_channel(user, context)
            results['bio_invite_spam'] = await self.check_user_bio_invite_links(user, context)
            results['channel_message_spam'] = await self.check_channel_sent_message(message, context)
            
            # Log analysis results
            spam_criteria = [k for k, v in results.items() if v]
            if spam_criteria:
                logger.info(f"User {user.id} flagged for extended spam criteria: {spam_criteria}")
            else:
                logger.debug(f"User {user.id} passed extended spam analysis")
                
            return results
            
        except Exception as e:
            logger.exception(f"Error in extended spam analysis for user {user.id}: {e}")
            return results


# Global detector instance
extended_spam_detector = ExtendedSpamDetector()


async def check_extended_spam_criteria(user: User, message: Message, context: CallbackContext) -> bool:
    """
    Main entry point for extended spam detection.
    
    Returns True if any extended spam criterion is met.
    """
    try:
        results = await extended_spam_detector.analyze_user_for_extended_spam_criteria(user, message, context)
        
        # Return True if any criterion indicates spam
        is_spam = any(results.values())
        
        if is_spam:
            triggered_criteria = [k for k, v in results.items() if v]
            logger.info(f"Extended spam detection triggered for user {user.id}: {triggered_criteria}")
        
        return is_spam
        
    except Exception as e:
        logger.exception(f"Error in extended spam criteria check for user {user.id}: {e}")
        return False