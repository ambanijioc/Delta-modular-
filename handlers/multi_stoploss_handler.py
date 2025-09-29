import logging
from typing import Dict, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

class MultiStrikeStopl0ssHandler:
    def __init__(self, delta_client):
        self.delta_client = delta_client
    
    async def show_multi_strike_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show multi-strike stop-loss menu"""
        try:
            query = update.callback_query
            await query.answer()
            
            logger.info("📊 Starting multi-strike stop-loss setup")
            
            # Get all positions
            positions = self.delta_client.force_enhance_positions()
            
            if not positions.get('success'):
                await query.edit_message_text(
                    "❌ Unable to fetch positions. Please try again."
                )
                return
            
            positions_data = positions.get('result', [])
            active_positions = [pos for pos in positions_data if float(pos.get('size', 0)) != 0]
            
            if not active_positions:
                await query.edit_message_text(
                    "📊 No active positions found.\n\n"
                    "You need open positions to set multi-strike stop-loss."
                )
                return
            
            # Store positions for selection
            context.user_data['available_positions'] = active_positions
            context.user_data['selected_positions'] = []
            
            message = self._create_position_selection_message(active_positions)
            reply_markup = self._create_position_selection_keyboard(active_positions)
            
            await query.edit_message_text(
                message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in show_multi_strike_menu: {e}", exc_info=True)
            await query.edit_message_text("❌ An error occurred.")
    
    def _create_position_selection_message(self, positions: List[Dict], selected_positions: List[int] = None) -> str:
        """Create message for position selection"""
        if selected_positions is None:
            selected_positions = []
        
        message = """<b>🛡️ Multi-Strike Stop-Loss Setup</b>

<b>Step 1:</b> Select positions for stop-loss protection

<b>Available Positions:</b>
"""
        
        for i, position in enumerate(positions[:10], 1):
            # Get position details
            product = position.get('product', {})
            symbol = product.get('symbol', 'Unknown')
            display_symbol = self._format_symbol_for_display(symbol)
            
            size = float(position.get('size', 0))
            entry_price = float(position.get('entry_price', 0))
            pnl = float(position.get('unrealized_pnl', 0))
            
            side = "LONG" if size > 0 else "SHORT"
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            
            # Show selection status
            selected_emoji = "✅" if i-1 in selected_positions else "⚪"
            
            message += f"""
{selected_emoji} <b>{i}. {display_symbol}</b> {side}
   Entry: ${entry_price:.4f} | PnL: {pnl_emoji}${pnl:.2f}"""
        
        if selected_positions:
            message += f"\n\n<b>Selected:</b> {len(selected_positions)} position(s)"
            message += "\n\n<i>Click positions to toggle selection, then proceed when ready.</i>"
        else:
            message += "\n\n<i>Click positions to select them for multi-strike stop-loss.</i>"
        
        return message
    
    def _create_position_selection_keyboard(self, positions: List[Dict], selected_positions: List[int] = None) -> InlineKeyboardMarkup:
        """Create keyboard for position selection"""
        if selected_positions is None:
            selected_positions = []
        
        keyboard = []
        
        # Position toggle buttons (2 per row)
        for i in range(0, len(positions[:8]), 2):  # Limit to 8 positions, 2 per row
            row = []
            
            for j in range(2):
                pos_index = i + j
                if pos_index < len(positions):
                    position = positions[pos_index]
                    product = position.get('product', {})
                    symbol = product.get('symbol', 'Unknown')
                    display_symbol = self._format_symbol_for_display(symbol)
                    
                    # Shorten for button display
                    if len(display_symbol) > 20:
                        display_symbol = display_symbol[:17] + "..."
                    
                    selected_emoji = "✅" if pos_index in selected_positions else "⚪"
                    button_text = f"{selected_emoji} {display_symbol}"
                    
                    row.append(InlineKeyboardButton(
                        button_text,
                        callback_data=f"ms_toggle_{pos_index}"
                    ))
            
            keyboard.append(row)
        
        # Control buttons
        if selected_positions:
            keyboard.append([
                InlineKeyboardButton("🎯 Set Stop-Loss for Selected", callback_data="ms_proceed"),
                InlineKeyboardButton("🔄 Clear Selection", callback_data="ms_clear")
            ])
        
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="ms_cancel")])
        
        return InlineKeyboardMarkup(keyboard)
    
    async def handle_position_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle position selection toggle"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Extract position index
            callback_data = query.data
            pos_index = int(callback_data.replace("ms_toggle_", ""))
            
            # Get current selections
            selected_positions = context.user_data.get('selected_positions', [])
            available_positions = context.user_data.get('available_positions', [])
            
            # Toggle selection
            if pos_index in selected_positions:
                selected_positions.remove(pos_index)
                logger.info(f"Deselected position {pos_index}")
            else:
                selected_positions.append(pos_index)
                logger.info(f"Selected position {pos_index}")
            
            context.user_data['selected_positions'] = selected_positions
            
            # Update message
            message = self._create_position_selection_message(available_positions, selected_positions)
            reply_markup = self._create_position_selection_keyboard(available_positions, selected_positions)
            
            await query.edit_message_text(
                message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in handle_position_toggle: {e}", exc_info=True)
            await query.edit_message_text("❌ An error occurred with selection.")
    
    async def handle_proceed_to_prices(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle proceed to price input"""
        try:
            query = update.callback_query
            await query.answer()
            
            selected_positions = context.user_data.get('selected_positions', [])
            available_positions = context.user_data.get('available_positions', [])
            
            if not selected_positions:
                await query.edit_message_text("❌ No positions selected. Please select at least one position.")
                return
            
            # Store selected position details
            selected_position_details = []
            for pos_index in selected_positions:
                if pos_index < len(available_positions):
                    position = available_positions[pos_index]
                    selected_position_details.append(position)
            
            context.user_data['selected_position_details'] = selected_position_details
            
            # Show trigger price input
            message = self._create_trigger_price_message(selected_position_details)
            
            context.user_data['waiting_for_multi_trigger_percentage'] = True
            
            await query.edit_message_text(message, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            logger.error(f"Error in handle_proceed_to_prices: {e}", exc_info=True)
            await query.edit_message_text("❌ An error occurred.")
    
    def _create_trigger_price_message(self, selected_positions: List[Dict]) -> str:
        """Create trigger price input message"""
        message = """<b>🎯 Multi-Strike Stop-Loss Setup</b>

<b>Step 2:</b> Set Trigger Price (Percentage)

<b>Selected Positions:</b>
"""
        
        for i, position in enumerate(selected_positions, 1):
            product = position.get('product', {})
            symbol = product.get('symbol', 'Unknown')
            display_symbol = self._format_symbol_for_display(symbol)
            
            size = float(position.get('size', 0))
            entry_price = float(position.get('entry_price', 0))
            side = "LONG" if size > 0 else "SHORT"
            
            message += f"{i}. <b>{display_symbol}</b> {side} (Entry: ${entry_price:.4f})\n"
        
        message += f"""
<b>🎯 Enter Trigger Price as Percentage:</b>

This percentage will be applied to ALL selected positions based on their individual entry prices.

<b>For LONG positions:</b> Percentage below entry price
<b>For SHORT positions:</b> Percentage above entry price

<b>Example:</b>
• Enter <code>10</code> for 10% stop-loss
• LONG at $100 → Stop triggers at $90
• SHORT at $50 → Stop triggers at $55

<b>Enter percentage (without % symbol):</b>
"""
        
        return message
    
    async def handle_trigger_percentage_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle trigger percentage input"""
        try:
            if not context.user_data.get('waiting_for_multi_trigger_percentage'):
                return
            
            user_input = update.message.text.strip()
            selected_positions = context.user_data.get('selected_position_details', [])
            
            logger.info(f"Processing multi-strike trigger percentage: {user_input}")
            
            try:
                trigger_percentage = float(user_input)
                if trigger_percentage <= 0 or trigger_percentage >= 100:
                    await update.message.reply_text("❌ Percentage must be between 0 and 100")
                    return
            except ValueError:
                await update.message.reply_text("❌ Please enter a valid number (e.g., 10 for 10%)")
                return
            
            # Calculate trigger prices for all positions
            trigger_calculations = []
            for position in selected_positions:
                entry_price = float(position.get('entry_price', 0))
                size = float(position.get('size', 0))
                
                if size > 0:  # Long position
                    trigger_price = entry_price * (1 - trigger_percentage / 100)
                else:  # Short position
                    trigger_price = entry_price * (1 + trigger_percentage / 100)
                
                trigger_calculations.append({
                    'position': position,
                    'trigger_price': trigger_price,
                    'entry_price': entry_price
                })
            
            context.user_data['trigger_percentage'] = trigger_percentage
            context.user_data['trigger_calculations'] = trigger_calculations
            context.user_data['waiting_for_multi_trigger_percentage'] = False
            
            # Show limit price input
            message = self._create_limit_price_message(trigger_calculations)
            context.user_data['waiting_for_multi_limit_percentage'] = True
            
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            logger.error(f"Error in handle_trigger_percentage_input: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred processing trigger percentage.")
    
    def _create_limit_price_message(self, trigger_calculations: List[Dict]) -> str:
        """Create limit price input message"""
        message = """<b>🎯 Multi-Strike Stop-Loss Setup</b>

<b>Step 3:</b> Set Limit Price Buffer (Percentage)

<b>Calculated Trigger Prices:</b>
"""
        
        for i, calc in enumerate(trigger_calculations, 1):
            position = calc['position']
            product = position.get('product', {})
            symbol = product.get('symbol', 'Unknown')
            display_symbol = self._format_symbol_for_display(symbol)
            
            entry_price = calc['entry_price']
            trigger_price = calc['trigger_price']
            
            message += f"{i}. <b>{display_symbol}</b>\n"
            message += f"   Entry: ${entry_price:.4f} → Trigger: ${trigger_price:.4f}\n"
        
        message += f"""
<b>💰 Enter Limit Price Buffer (Percentage):</b>

This creates a buffer from the trigger price for limit orders.

<b>How it works:</b>
• For LONG exits (SELL orders): Buffer BELOW trigger price
• For SHORT exits (BUY orders): Buffer ABOVE trigger price

<b>Example with 5% buffer:</b>
• LONG trigger at $90 → Limit at $85.50 (5% below)
• SHORT trigger at $55 → Limit at $57.75 (5% above)

<b>Recommended:</b> 3-8% for safe execution

<b>Enter limit buffer percentage (without % symbol):</b>
"""
        
        return message
    
    async def handle_limit_percentage_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle limit percentage input"""
        try:
            if not context.user_data.get('waiting_for_multi_limit_percentage'):
                return
            
            user_input = update.message.text.strip()
            trigger_calculations = context.user_data.get('trigger_calculations', [])
            trigger_percentage = context.user_data.get('trigger_percentage', 0)
            
            logger.info(f"Processing multi-strike limit percentage: {user_input}")
            
            try:
                limit_percentage = float(user_input)
                if limit_percentage <= 0 or limit_percentage >= 50:
                    await update.message.reply_text("❌ Limit buffer must be between 0 and 50%")
                    return
            except ValueError:
                await update.message.reply_text("❌ Please enter a valid number (e.g., 5 for 5%)")
                return
            
            # Calculate limit prices
            final_calculations = []
            for calc in trigger_calculations:
                position = calc['position']
                trigger_price = calc['trigger_price']
                size = float(position.get('size', 0))
                
                # Calculate limit price based on position side
                if size > 0:  # Long position (selling to exit) - limit below trigger
                    limit_price = trigger_price * (1 - limit_percentage / 100)
                else:  # Short position (buying to exit) - limit above trigger
                    limit_price = trigger_price * (1 + limit_percentage / 100)
                
                final_calculations.append({
                    'position': position,
                    'trigger_price': trigger_price,
                    'limit_price': limit_price,
                    'entry_price': calc['entry_price']
                })
            
            context.user_data['limit_percentage'] = limit_percentage
            context.user_data['final_calculations'] = final_calculations
            context.user_data['waiting_for_multi_limit_percentage'] = False
            
            # Show confirmation and execute
            await self._show_confirmation_and_execute(update, context, final_calculations)
            
        except Exception as e:
            logger.error(f"Error in handle_limit_percentage_input: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred processing limit percentage.")
    
    async def _show_confirmation_and_execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE, final_calculations: List[Dict]):
        """Show confirmation and execute multi-strike stop-loss orders"""
        try:
            trigger_percentage = context.user_data.get('trigger_percentage', 0)
            limit_percentage = context.user_data.get('limit_percentage', 0)
            
            # Show confirmation
            confirmation_message = f"""<b>✅ Multi-Strike Stop-Loss Confirmation</b>

<b>Settings Applied:</b>
• Trigger: {trigger_percentage}% from entry
• Limit Buffer: {limit_percentage}% from trigger

<b>Orders to be Placed:</b>
"""
            
            for i, calc in enumerate(final_calculations, 1):
                position = calc['position']
                product = position.get('product', {})
                symbol = product.get('symbol', 'Unknown')
                display_symbol = self._format_symbol_for_display(symbol)
                
                size = float(position.get('size', 0))
                side = "SELL" if size > 0 else "BUY"  # Exit side
                
                confirmation_message += f"""
{i}. <b>{display_symbol}</b>
   Side: {side} | Size: {abs(size):.0f}
   Trigger: ${calc['trigger_price']:.4f}
   Limit: ${calc['limit_price']:.4f}"""
            
            confirmation_message += "\n\n🔄 <b>Placing orders...</b>"
            
            await update.message.reply_text(confirmation_message, parse_mode=ParseMode.HTML)
            
            # Execute orders one by one
            await self._execute_multi_strike_orders(update, context, final_calculations)
            
        except Exception as e:
            logger.error(f"Error in _show_confirmation_and_execute: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred during confirmation.")
    
    async def _execute_multi_strike_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE, final_calculations: List[Dict]):
        """Execute all multi-strike stop-loss orders"""
        try:
            successful_orders = []
            failed_orders = []
            
            for i, calc in enumerate(final_calculations, 1):
                position = calc['position']
                product = position.get('product', {})
                product_id = product.get('id') or position.get('product_id')
                symbol = product.get('symbol', 'Unknown')
                display_symbol = self._format_symbol_for_display(symbol)
                
                size = abs(int(position.get('size', 0)))
                current_side = 'buy' if float(position.get('size', 0)) > 0 else 'sell'
                exit_side = 'sell' if current_side == 'buy' else 'buy'
                
                trigger_price = calc['trigger_price']
                limit_price = calc['limit_price']
                
                logger.info(f"Placing order {i}/{len(final_calculations)}: {display_symbol}")
                
                # Place the stop-loss order
                result = self.delta_client.place_stop_order(
                    product_id=product_id,
                    size=size,
                    side=exit_side,
                    stop_price=str(trigger_price),
                    limit_price=str(limit_price),
                    order_type="limit_order",
                    reduce_only=True
                )
                
                if result.get('success'):
                    order_id = result.get('result', {}).get('id', 'Unknown')
                    successful_orders.append({
                        'symbol': display_symbol,
                        'order_id': order_id,
                        'trigger': trigger_price,
                        'limit': limit_price
                    })
                    logger.info(f"✅ Order placed for {display_symbol}: {order_id}")
                else:
                    error_msg = result.get('error', 'Unknown error')
                    failed_orders.append({
                        'symbol': display_symbol,
                        'error': error_msg
                    })
                    logger.error(f"❌ Order failed for {display_symbol}: {error_msg}")
            
            # Send results summary
            await self._send_execution_results(update, successful_orders, failed_orders)
            
            # Clear user data
            self._clear_multi_stoploss_data(context)
            
        except Exception as e:
            logger.error(f"Error in _execute_multi_strike_orders: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred executing orders.")
    
    async def _send_execution_results(self, update: Update, successful_orders: List[Dict], failed_orders: List[Dict]):
        """Send execution results summary"""
        try:
            message = f"<b>🛡️ Multi-Strike Stop-Loss Results</b>\n\n"
            
            if successful_orders:
                message += f"<b>✅ Successful Orders ({len(successful_orders)}):</b>\n"
                for order in successful_orders:
                    message += f"• <b>{order['symbol']}</b>\n"
                    message += f"  ID: <code>{order['order_id']}</code>\n"
                    message += f"  Trigger: ${order['trigger']:.4f} | Limit: ${order['limit']:.4f}\n\n"
            
            if failed_orders:
                message += f"<b>❌ Failed Orders ({len(failed_orders)}):</b>\n"
                for order in failed_orders:
                    message += f"• <b>{order['symbol']}</b>\n"
                    message += f"  Error: {order['error']}\n\n"
            
            message += f"<b>📊 Summary:</b>\n"
            message += f"• Total Attempted: {len(successful_orders) + len(failed_orders)}\n"
            message += f"• Successful: {len(successful_orders)}\n"
            message += f"• Failed: {len(failed_orders)}\n\n"
            
            if successful_orders:
                message += f"<b>🛡️ Protection Active!</b>\n"
                message += f"Your positions are now protected with reduce-only stop-loss orders.\n\n"
                message += f"Use /orders to view all active orders."
            
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            logger.error(f"Error in _send_execution_results: {e}", exc_info=True)
    
    def _format_symbol_for_display(self, symbol: str) -> str:
        """Format symbol for display"""
        if not symbol or symbol == 'Unknown':
            return 'Unknown Position'
        
        if '-' in symbol:
            parts = symbol.split('-')
            if len(parts) >= 4:
                option_type = 'CE' if parts[0] == 'C' else 'PE' if parts[0] == 'P' else parts[0]
                return f"{parts[1]} {parts[2]} {option_type}"
        
        return symbol
    
    def _clear_multi_stoploss_data(self, context: ContextTypes.DEFAULT_TYPE):
        """Clear multi-strike stop-loss data"""
        keys_to_clear = [
            'available_positions', 'selected_positions', 'selected_position_details',
            'trigger_percentage', 'limit_percentage', 'trigger_calculations',
            'final_calculations', 'waiting_for_multi_trigger_percentage',
            'waiting_for_multi_limit_percentage'
        ]
        
        for key in keys_to_clear:
            context.user_data.pop(key, None)
        
        logger.info("Cleared multi-strike stop-loss data")
    
    async def handle_clear_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle clear selection"""
        try:
            query = update.callback_query
            await query.answer()
            
            context.user_data['selected_positions'] = []
            available_positions = context.user_data.get('available_positions', [])
            
            message = self._create_position_selection_message(available_positions, [])
            reply_markup = self._create_position_selection_keyboard(available_positions, [])
            
            await query.edit_message_text(
                message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in handle_clear_selection: {e}", exc_info=True)
    
    async def handle_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle cancel multi-strike setup"""
        try:
            query = update.callback_query
            await query.answer()
            
            self._clear_multi_stoploss_data(context)
            
            await query.edit_message_text(
                "❌ Multi-strike stop-loss setup cancelled.\n\n"
                "Use /start to access the main menu."
            )
            
        except Exception as e:
            logger.error(f"Error in handle_cancel: {e}", exc_info=True)
