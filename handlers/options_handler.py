from telegram import Update
from telegram.ext import ContextTypes
from api.delta_client import DeltaClient
from utils.helpers import format_position_message

class OptionsHandler:
    def __init__(self, delta_client: DeltaClient):
        self.delta_client = delta_client
    
    async def handle_lot_size_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle lot size input from user"""
        if not context.user_data.get('waiting_for_lot_size'):
            return
        
        try:
            lot_size = int(update.message.text)
            if lot_size <= 0:
                await update.message.reply_text("❌ Please enter a positive number for lot size.")
                return
            
            context.user_data['lot_size'] = lot_size
            context.user_data['waiting_for_lot_size'] = False
            
            # Show strategy selection
            from api.telegram_client import TelegramClient
            telegram_client = TelegramClient("")
            reply_markup = telegram_client.create_strategy_keyboard()
            
            await update.message.reply_text(
                "📊 Choose your strategy:",
                reply_markup=reply_markup
            )
            
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number for lot size.")
    
    async def handle_strategy_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle strategy selection (long/short straddle)"""
        query = update.callback_query
        await query.answer()
        
        strategy = query.data.replace("strategy_", "")
        context.user_data['strategy'] = strategy
        
        # Execute the straddle strategy
        await self._execute_straddle(update, context, strategy)
    
    async def _execute_straddle(self, update: Update, context: ContextTypes.DEFAULT_TYPE, strategy: str):
        """Execute long or short straddle strategy"""
        ce_option = context.user_data.get('ce_option')
        pe_option = context.user_data.get('pe_option')
        lot_size = context.user_data.get('lot_size')
        
        if not all([ce_option, pe_option, lot_size]):
            await update.callback_query.edit_message_text("❌ Missing trade data. Please start over.")
            return
        
        # Determine order side based on strategy
        side = "buy" if strategy == "long" else "sell"
        
        # Place CE order
        ce_result = self.delta_client.place_order(
            product_id=ce_option['product_id'],
            side=side,
            size=lot_size,
            order_type="market_order"
        )
        
        # Place PE order
        pe_result = self.delta_client.place_order(
            product_id=pe_option['product_id'],
            side=side,
            size=lot_size,
            order_type="market_order"
        )
        
        # Format and send result message
        message = self._format_trade_result(strategy, ce_result, pe_result, ce_option, pe_option, lot_size)
        await update.callback_query.edit_message_text(message, parse_mode='HTML')
    
    def _format_trade_result(self, strategy: str, ce_result: dict, pe_result: dict, 
                           ce_option: dict, pe_option: dict, lot_size: int) -> str:
        """Format trade execution result message"""
        strategy_name = "Long Straddle" if strategy == "long" else "Short Straddle"
        
        message = f"<b>🎯 {strategy_name} Executed</b>\n\n"
        
        # CE order result
        if ce_result.get('success'):
            message += f"✅ <b>CE Order:</b> {ce_option['symbol']}\n"
            message += f"   Size: {lot_size} contracts\n"
            message += f"   Order ID: {ce_result['result']['id']}\n\n"
        else:
            message += f"❌ <b>CE Order Failed:</b> {ce_option['symbol']}\n"
            message += f"   Error: {ce_result.get('error', 'Unknown error')}\n\n"
        
        # PE order result
        if pe_result.get('success'):
            message += f"✅ <b>PE Order:</b> {pe_option['symbol']}\n"
            message += f"   Size: {lot_size} contracts\n"
            message += f"   Order ID: {pe_result['result']['id']}\n\n"
        else:
            message += f"❌ <b>PE Order Failed:</b> {pe_option['symbol']}\n"
            message += f"   Error: {pe_result.get('error', 'Unknown error')}\n\n"
        
        return message
