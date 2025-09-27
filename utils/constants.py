# Bot states
WAITING_FOR_LOT_SIZE = "waiting_for_lot_size"
WAITING_FOR_EXPIRY = "waiting_for_expiry"

# Order sides
BUY_SIDE = "buy"
SELL_SIDE = "sell"

# Order types
MARKET_ORDER = "market_order"
LIMIT_ORDER = "limit_order"

# Strategy types
LONG_STRADDLE = "long"
SHORT_STRADDLE = "short"

# Contract types
CALL_OPTIONS = "call_options"
PUT_OPTIONS = "put_options"

# Messages
START_MESSAGE = """
🤖 <b>BTC Options Trading Bot</b>

Welcome! This bot helps you trade BTC options using straddle strategies.

<b>Features:</b>
📅 Select expiry dates
🎯 ATM strike identification
📊 Long/Short straddle execution
💼 Position monitoring

Use the menu below to get started:
"""

HELP_MESSAGE = """
<b>📖 Bot Commands & Usage</b>

<b>Main Features:</b>
• <b>Select Expiry:</b> Choose from available BTC option expiry dates
• <b>Show Positions:</b> View your current open positions

<b>Trading Flow:</b>
1️⃣ Select an expiry date
2️⃣ Bot finds BTC spot price and ATM strike
3️⃣ Enter desired lot size
4️⃣ Choose Long or Short straddle
5️⃣ Orders are executed at market price

<b>Straddle Strategies:</b>
• <b>Long Straddle:</b> Buy CE + Buy PE (profit from volatility)
• <b>Short Straddle:</b> Sell CE + Sell PE (profit from low volatility)

<b>Commands:</b>
/start - Start the bot
/help - Show this help message
/positions - Show current positions
"""
