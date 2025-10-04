"""
Multi-account configuration
Add your bot tokens and Delta Exchange API credentials here
"""

ACCOUNTS = {
    'account1': {
        'bot_token': '7253849861:AAFldL44jRYaaTFhY45e2tl1dvHUYPL-GNc',  # Your current bot token
        'delta_api_key': 'YOUR_CURRENT_API_KEY',
        'delta_api_secret': 'YOUR_CURRENT_API_SECRET',
        'account_name': 'Main Trading Account',
        'webhook_path': '/webhook1'  # Unique webhook path for this bot
    },
    'account2': {
        'bot_token': 'SECOND_BOT_TOKEN_HERE',  # Get from @BotFather
        'delta_api_key': 'SECOND_DELTA_API_KEY',
        'delta_api_secret': 'SECOND_DELTA_API_SECRET',
        'account_name': 'Secondary Account',
        'webhook_path': '/webhook2'
    },
    # Add more accounts as needed (up to 3 for free tier)
    # 'account3': {
    #     'bot_token': 'THIRD_BOT_TOKEN_HERE',
    #     'delta_api_key': 'THIRD_DELTA_API_KEY',
    #     'delta_api_secret': 'THIRD_DELTA_API_SECRET',
    #     'account_name': 'Third Account',
    #     'webhook_path': '/webhook3'
    # },
}

# Webhook configuration
WEBHOOK_URL = "https://delta-modular.onrender.com"  # Your Render URL
WEBHOOK_PORT = 10000
