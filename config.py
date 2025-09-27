import os
from dotenv import load_dotenv

load_dotenv()

# Delta Exchange API Configuration
DELTA_API_KEY = os.getenv('DELTA_API_KEY')
DELTA_API_SECRET = os.getenv('DELTA_API_SECRET')
DELTA_BASE_URL = 'https://api.india.delta.exchange'

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Server Configuration for Render.com
HOST = '0.0.0.0'
PORT = int(os.getenv('PORT', 10000))

# Trading Configuration
BTC_SPOT_SYMBOL = 'BTCUSD'
LOT_SIZE = 1  # 1 lot each for CE and PE
