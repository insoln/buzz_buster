# Sentry Integration Setup

## Overview
This bot now includes Sentry integration for error monitoring and performance tracking.

## Configuration

### Environment Variables
Add these environment variables to your `.env` file:

```bash
# Sentry DSN for error monitoring (replace with your real DSN)
# NEVER commit a production DSN into public repos
SENTRY_DSN=<YOUR_SENTRY_DSN>

# Optional: App version for release tracking
APP_VERSION=1.0.0

# Optional: Debug mode (affects Sentry environment tag)
DEBUG=false
```

### Features Implemented

1. **Error Monitoring**: All errors (ERROR level and above) are automatically sent to Sentry
2. **Performance Monitoring**: 10% of transactions are sampled for performance tracking
3. **Context Enhancement**: Each Sentry event includes:
   - Telegram update ID
   - Bot username and ID
   - User information when available
   - Component information (database, bot_main_loop, etc.)

4. **Logging Integration**: 
   - INFO level and above are captured as breadcrumbs
   - ERROR level and above are sent as events
   - Custom Sentry handler preserves Telegram context

5. **Exception Handling**: Strategic try-catch blocks around:
   - Database initialization
   - Bot initialization
   - Main event loop
   - Critical operations

## Testing

Use the `/test_sentry` command (admin only) to verify Sentry integration:
- Sends test messages
- Captures a controlled exception
- Includes user context and tags

## Sentry Dashboard

Monitor your bot at: https://sentry.careerum.com/

### What You'll See:
- Real-time error tracking
- Performance metrics
- User impact analysis
- Release tracking (if APP_VERSION is set)
- Custom tags and context for each event

## Production Recommendations

1. **Sampling Rates**: Consider reducing sampling rates in production:
   ```python
   traces_sample_rate=0.01,  # 1% instead of 10%
   profiles_sample_rate=0.01,  # 1% instead of 10%
   ```

2. **Environment**: Set `DEBUG=false` for production environment tagging

3. **Releases**: Set `APP_VERSION` environment variable for release tracking

4. **Alerts**: Configure Sentry alerts for critical errors

## Privacy & Security Notes

The integration is configured with `send_default_pii=True` to include user information (Telegram user IDs and usernames when available) for better debugging.

Security guidelines:
1. Keep your actual DSN secret; use environment variables.
2. Consider disabling `send_default_pii` if compliance requires minimal user data.
3. Use `before_send` hook (not implemented here) to redact sensitive fields if needed.