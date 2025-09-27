# Delta-modular-
# BTC Options Trading Bot

A modular Telegram bot for trading BTC options on Delta Exchange India.

## Features
- Expiry date selection via inline keyboards
- Automatic ATM strike price identification
- Real-time BTC spot price fetching
- Market order execution for both CE and PE
- Render.com deployment ready

## Setup
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set environment variables in `.env` file
4. Run: `python main.py`

## Environment Variables
- `DELTA_API_KEY`: Your Delta Exchange API key
- `DELTA_API_SECRET`: Your Delta Exchange API secret
- `TELEGRAM_BOT_TOKEN`: Your Telegram bot token
- `PORT`: Server port (default: 10000)

## Deployment on Render.com
1. Connect your GitHub repository
2. Set environment variables in Render dashboard
3. Deploy as a Web Service
4. Start command: `python main.py`
5. 
