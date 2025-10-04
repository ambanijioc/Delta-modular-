# config/accounts_config.py
"""
Multi-account configuration for Delta Exchange bots.
Each account has its own Telegram bot and Delta Exchange credentials.
"""

import os

# Account configurations
# Add/remove accounts as needed
ACCOUNTS = {
    # Account 1 - Your existing/main account
    'account1': {
        'bot_token': os.getenv('TELEGRAM_BOT_TOKEN_1', 'YOUR_BOT_TOKEN_1'),
        'delta_api_key': os.getenv('DELTA_API_KEY_1', 'YOUR_DELTA_KEY_1'),
        'delta_api_secret': os.getenv('DELTA_API_SECRET_1', 'YOUR_DELTA_SECRET_1'),
        'account_name': 'Main Trading Account',
        'webhook_path': None,  # Will be auto-generated
        'enabled': True
    },
    
    # Account 2 - Add your second account
    'account2': {
        'bot_token': os.getenv('TELEGRAM_BOT_TOKEN_2', 'YOUR_BOT_TOKEN_2'),
        'delta_api_key': os.getenv('DELTA_API_KEY_2', 'YOUR_DELTA_KEY_2'),
        'delta_api_secret': os.getenv('DELTA_API_SECRET_2', 'YOUR_DELTA_SECRET_2'),
        'account_name': 'Secondary Trading Account',
        'webhook_path': None,
        'enabled': False
    },
    
    # Account 3 - Optional third account (commented out by default)
    # 'account3': {
    #     'bot_token': os.getenv('TELEGRAM_BOT_TOKEN_3', 'YOUR_BOT_TOKEN_3'),
    #     'delta_api_key': os.getenv('DELTA_API_KEY_3', 'YOUR_DELTA_KEY_3'),
    #     'delta_api_secret': os.getenv('DELTA_API_SECRET_3', 'YOUR_DELTA_SECRET_3'),
    #     'account_name': 'Third Trading Account',
    #     'webhook_path': None,
    #     'enabled': False  # Disabled by default
    # },
}

# Webhook configuration
WEBHOOK_ENABLED = os.getenv('WEBHOOK_ENABLED', 'true').lower() == 'true'
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_URL', '')  # e.g., https://your-app.onrender.com

# Server configuration
SERVER_HOST = os.getenv('HOST', '0.0.0.0')
SERVER_PORT = int(os.getenv('PORT', 10000))

# Get list of enabled accounts
def get_enabled_accounts():
    """Return dictionary of enabled accounts only"""
    return {
        account_id: config 
        for account_id, config in ACCOUNTS.items() 
        if config.get('enabled', True)
    }

# Generate webhook paths for each bot
def setup_webhook_paths():
    """Generate unique webhook paths for each bot"""
    for account_id, config in ACCOUNTS.items():
        if config.get('enabled', True):
            # Extract bot token for webhook path
            bot_token = config['bot_token']
            config['webhook_path'] = f"/{bot_token}"
    
    return ACCOUNTS

# Initialize webhook paths on import
ACCOUNTS = setup_webhook_paths()
