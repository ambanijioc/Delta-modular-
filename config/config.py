import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Delta Exchange Configuration
DELTA_API_KEY = os.getenv('DELTA_API_KEY')
DELTA_API_SECRET = os.getenv('DELTA_API_SECRET')
DELTA_BASE_URL = os.getenv('DELTA_BASE_URL', 'https://api.india.delta.exchange')

# Server Configuration
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 10000))

# Webhook Configuration
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
RENDER_SERVICE_NAME = os.getenv('RENDER_SERVICE_NAME')

# Trading Configuration
BTC_PRODUCT_ID = int(os.getenv('BTC_PRODUCT_ID', 27))  # BTC perpetual futures product ID

# Logging Configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# Validation
def validate_config():
    """Validate required configuration"""
    required_vars = {
        'TELEGRAM_BOT_TOKEN': TELEGRAM_BOT_TOKEN,
        'DELTA_API_KEY': DELTA_API_KEY,
        'DELTA_API_SECRET': DELTA_API_SECRET,
    }
    
    missing_vars = [var for var, value in required_vars.items() if not value]
    
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    return True
  
