from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import logging
from typing import Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TelegramClient:
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(token).build()
        self.user_states = {}  # Track user conversation states
        
    def create_expiry_keyboard(self, expiry_dates: List[str]) -> InlineKeyboardMarkup:
        """Create inline keyboard for expiry date selection"""
        keyboard = []
        for date in expiry_dates[:10]:  # Limit to 10 dates to avoid message size limit
            keyboard.append([InlineKeyboardButton(date, callback_data=f"expiry_{date}")])
        return InlineKeyboardMarkup(keyboard)
    
    def create_strategy_keyboard(self) -> InlineKeyboardMarkup:
        """Create inline keyboard for strategy selection"""
        keyboard = [
            [InlineKeyboardButton("Long Straddle", callback_data="strategy_long")],
            [InlineKeyboardButton("Short Straddle", callback_data="strategy_short")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def create_main_menu_keyboard(self):
        """Create the main menu keyboard with all options"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
        keyboard = [
            [InlineKeyboardButton("📅 Select Expiry", callback_data="select_expiry")],
            [InlineKeyboardButton("📊 Show Positions", callback_data="show_positions")],
            [InlineKeyboardButton("💰 Portfolio Summary", callback_data="portfolio_summary")],
            [InlineKeyboardButton("🛡️ Add Stop-Loss", callback_data="add_stoploss_menu")]
        ]
    
        return InlineKeyboardMarkup(keyboard)
