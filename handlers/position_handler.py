from telegram import Update
from telegram.ext import ContextTypes
from api.delta_client import DeltaClient
from utils.helpers import format_positions_message

class PositionHandler:
    def __init__(self, delta_client: DeltaClient):
        self.delta_client = delta_client
    
    # In handlers/position_handler.py
    async def show_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show positions with live market data"""
        try:
            query = update.callback_query
            await query.answer()
        
        # Get positions
            positions = self.delta_client.force_enhance_positions()
        
            if not positions.get('success'):
                await query.edit_message_text("❌ Failed to fetch positions.")
                return
        
            positions_data = positions.get('result', [])
        
            if not positions_data:
                message = "📊 No active positions found."
            else:
            # Pass delta_client for live data
                message = format_enhanced_positions_with_live_data(positions_data, self.delta_client)
        
        # Add back button
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
        
            await query.edit_message_text(
                message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        
        except Exception as e:
            logger.error(f"Error in show_positions: {e}")
            await query.edit_message_text("❌ An error occurred.")
