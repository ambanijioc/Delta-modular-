import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Delta Exchange Configuration
DELTA_API_KEY = os.getenv('DELTA_API_KEY')
DELTA_API_SECRET = os.getenv('DELTA_API_SECRET')
DELTA_BASE_URL = 'https://api.india.delta.exchange'

# Server Configuration
HOST = '0.0.0.0'
PORT = 10000

# Trading Configuration
BTC_PRODUCT_ID = 27  # BTC perpetual futures product ID
