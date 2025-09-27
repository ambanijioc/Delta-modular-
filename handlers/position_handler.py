from telegram import Update
from telegram.ext import ContextTypes
from api.delta_client import DeltaClient
from utils.helpers import format_positions_message

class PositionHandler:
    def __init__(self, delta_client: DeltaClient):
        self.delta_client = delta_client
    
    async def show_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all open positions"""
        query = update.callback_query
        await query.answer()
        
        positions = self.delta_client.get_positions()
        
        if not positions.get('success'):
            await query.edit_message_text("❌ Unable to fetch positions. Please try again.")
            return
        
        positions_data = positions.get('result', [])
        
        if not positions_data:
            await query.edit_message_text("📊 No open positions found.")
            return
        
        message = format_positions_message(positions_data)
        await query.edit_message_text(message, parse_mode='HTML')
      
