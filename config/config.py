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
BTC_PRODUCT_ID = int(os.getenv('BTC_PRODUCT_ID', 27))

# Basic validation without raising errors
def validate_config():
    """Basic config validation"""
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append('TELEGRAM_BOT_TOKEN')
    if not DELTA_API_KEY:
        missing.append('DELTA_API_KEY')
    if not DELTA_API_SECRET:
        missing.append('DELTA_API_SECRET')
    
    if missing:
        print(f"⚠️ Missing environment variables: {', '.join(missing)}")
        return False
    
    return True

# Run validation on import
validate_config()
