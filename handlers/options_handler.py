from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from api.delta_client import DeltaClient
from utils.helpers import format_position_message, validate_lot_size, calculate_straddle_cost
import logging

logger = logging.getLogger(__name__)

class OptionsHandler:
    def __init__(self, delta_client: DeltaClient):
        self.delta_client = delta_client
    
    def create_strategy_keyboard(self) -> InlineKeyboardMarkup:
        """Create inline keyboard for strategy selection"""
        keyboard = [
            [InlineKeyboardButton("Long Straddle", callback_data="strategy_long")],
            [InlineKeyboardButton("Short Straddle", callback_data="strategy_short")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    async def handle_lot_size_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle lot size input from user"""
        try:
            logger.info(f"Processing lot size input: {update.message.text}")
            
            if not context.user_data.get('waiting_for_lot_size'):
                logger.info("Not waiting for lot size, ignoring message")
                return
            
            is_valid, result = validate_lot_size(update.message.text)
            
            if not is_valid:
                await update.message.reply_text(f"❌ {result}")
                return
            
            lot_size = result
            context.user_data['lot_size'] = lot_size
            context.user_data['waiting_for_lot_size'] = False
            
            logger.info(f"Lot size set to: {lot_size}")
            
            # Show strategy selection using local method
            reply_markup = self.create_strategy_keyboard()
            
            # Calculate estimated cost
            ce_option = context.user_data.get('ce_option')
            pe_option = context.user_data.get('pe_option')
            
            message = f"✅ Lot size set to: {lot_size} contracts\n\n"
            
            if ce_option and pe_option:
                try:
                    long_cost = calculate_straddle_cost(ce_option, pe_option, lot_size, "long")
                    short_credit = calculate_straddle_cost(ce_option, pe_option, lot_size, "short")
                    
                    message += f"💰 <b>Estimated Costs:</b>\n"
                    message += f"Long Straddle: ${long_cost:,.2f} (debit)\n"
                    message += f"Short Straddle: ${abs(short_credit):,.2f} (credit)\n\n"
                except Exception as cost_error:
                    logger.warning(f"Failed to calculate costs: {cost_error}")
                    message += "⚠️ Could not calculate estimated costs\n\n"
            
            message += "📊 Choose your strategy:"
            
            await update.message.reply_text(
                message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in handle_lot_size_input: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ An error occurred while processing lot size. Please try again."
            )
    
    async def handle_strategy_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle strategy selection (long/short straddle)"""
        try:
            query = update.callback_query
            await query.answer()
            
            strategy = query.data.replace("strategy_", "")
            context.user_data['strategy'] = strategy
            
            logger.info(f"Strategy selected: {strategy}")
            
            # Execute the straddle strategy
            await self._execute_straddle(update, context, strategy)
            
        except Exception as e:
            logger.error(f"Error in handle_strategy_selection: {e}", exc_info=True)
            await query.edit_message_text("❌ An error occurred. Please try again.")
    
    async def _execute_straddle(self, update: Update, context: ContextTypes.DEFAULT_TYPE, strategy: str):
        """Execute long or short straddle strategy"""
        try:
            ce_option = context.user_data.get('ce_option')
            pe_option = context.user_data.get('pe_option')
            lot_size = context.user_data.get('lot_size')
            
            if not all([ce_option, pe_option, lot_size]):
                await update.callback_query.edit_message_text("❌ Missing trade data. Please start over.")
                return
            
            # Show execution confirmation
            strategy_name = "Long Straddle" if strategy == "long" else "Short Straddle"
            await update.callback_query.edit_message_text(
                f"🔄 Executing {strategy_name}...\n\nPlacing orders for {lot_size} contracts...",
                parse_mode='HTML'
            )
            
            # Determine order side based on strategy
            side = "buy" if strategy == "long" else "sell"
            
            logger.info(f"Executing {strategy_name} - Side: {side}, Lot size: {lot_size}")
            
            # Place CE order
            logger.info(f"Placing CE order: Product ID {ce_option.get('product_id')}")
            ce_result = self.delta_client.place_order(
                product_id=ce_option['product_id'],
                side=side,
                size=lot_size,
                order_type="market_order"
            )
            
            # Place PE order
            logger.info(f"Placing PE order: Product ID {pe_option.get('product_id')}")
            pe_result = self.delta_client.place_order(
                product_id=pe_option['product_id'],
                side=side,
                size=lot_size,
                order_type="market_order"
            )
            
            # Format and send result message
            message = self._format_trade_result(strategy, ce_result, pe_result, ce_option, pe_option, lot_size)
            await update.callback_query.edit_message_text(message, parse_mode='HTML')
            
            # Clear user data for next trade
            self._clear_trade_data(context)
            
        except Exception as e:
            logger.error(f"Error in _execute_straddle: {e}", exc_info=True)
            try:
                await update.callback_query.edit_message_text(
                    "❌ An error occurred while executing the trade. Please try again."
                )
            except:
                pass
    
    def _format_trade_result(self, strategy: str, ce_result: dict, pe_result: dict, 
                           ce_option: dict, pe_option: dict, lot_size: int) -> str:
        """Format trade execution result message"""
        try:
            strategy_name = "Long Straddle" if strategy == "long" else "Short Straddle"
            action = "Bought" if strategy == "long" else "Sold"
            
            message = f"<b>🎯 {strategy_name} Execution Report</b>\n\n"
            
            # Overall status
            ce_success = ce_result.get('success', False)
            pe_success = pe_result.get('success', False)
            
            if ce_success and pe_success:
                message += f"✅ <b>Trade Successfully Executed!</b>\n\n"
            elif ce_success or pe_success:
                message += f"⚠️ <b>Partial Execution</b>\n\n"
            else:
                message += f"❌ <b>Trade Failed</b>\n\n"
            
            # CE order result
            message += f"<b>📈 Call Option (CE):</b>\n"
            message += f"Symbol: {ce_option.get('symbol', 'N/A')}\n"
            if ce_success:
                message += f"Status: ✅ {action} {lot_size} contracts\n"
                order_id = ce_result.get('result', {}).get('id', 'N/A')
                message += f"Order ID: {order_id}\n"
            else:
                message += f"Status: ❌ Failed\n"
                error_msg = ce_result.get('error', 'Unknown error')
                message += f"Error: {error_msg}\n"
            
            message += "\n"
            
            # PE order result
            message += f"<b>📉 Put Option (PE):</b>\n"
            message += f"Symbol: {pe_option.get('symbol', 'N/A')}\n"
            if pe_success:
                message += f"Status: ✅ {action} {lot_size} contracts\n"
                order_id = pe_result.get('result', {}).get('id', 'N/A')
                message += f"Order ID: {order_id}\n"
            else:
                message += f"Status: ❌ Failed\n"
                error_msg = pe_result.get('error', 'Unknown error')
                message += f"Error: {error_msg}\n"
            
            message += f"\n<i>Use /positions to view your current positions</i>"
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting trade result: {e}")
            return f"Trade execution completed. Check logs for details."
    
    def _clear_trade_data(self, context: ContextTypes.DEFAULT_TYPE):
        """Clear trade-related data from user context"""
        try:
            keys_to_clear = [
                'selected_expiry', 'atm_strike', 'spot_price',
                'ce_option', 'pe_option', 'lot_size', 'strategy',
                'waiting_for_lot_size'
            ]
            for key in keys_to_clear:
                context.user_data.pop(key, None)
            logger.info("Trade data cleared from user context")
        except Exception as e:
            logger.warning(f"Error clearing trade data: {e}")

    def create_position_actions_keyboard(self, order_id: str) -> InlineKeyboardMarkup:
        """Create keyboard for position actions including stop-loss"""
        keyboard = [
        [InlineKeyboardButton("🛡️ Add Stop-Loss", callback_data=f"add_stoploss_{order_id}")],
        [InlineKeyboardButton("📊 View Details", callback_data=f"view_order_{order_id}")],
        [InlineKeyboardButton("❌ Close Position", callback_data=f"close_position_{order_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def _format_trade_result(self, strategy: str, ce_result: dict, pe_result: dict, 
                       ce_option: dict, pe_option: dict, lot_size: int) -> str:
    """Enhanced trade result with stop-loss options"""
    # ... existing code ...
    
    # Add stop-loss options for successful orders
    if ce_success and pe_success:
        ce_order_id = ce_result['result']['id']
        pe_order_id = pe_result['result']['id']
        
        message += f"\n<b>🛡️ Risk Management:</b>\n"
        message += f"Use /stoploss {ce_order_id} for CE protection\n"
        message += f"Use /stoploss {pe_order_id} for PE protection\n"
    
    return message
