import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from api.delta_client import DeltaClient

logger = logging.getLogger(__name__)

class StopLossHandler:
    def __init__(self, delta_client: DeltaClient):
        self.delta_client = delta_client
        
    def create_stoploss_type_keyboard(self) -> InlineKeyboardMarkup:
        """Create keyboard for stop-loss type selection"""
        keyboard = [
            [InlineKeyboardButton("🛑 Stop Market", callback_data="sl_type_stop_market")],
            [InlineKeyboardButton("🎯 Stop Limit", callback_data="sl_type_stop_limit")],
            [InlineKeyboardButton("📈 Trailing Stop", callback_data="sl_type_trailing_stop")],
            [InlineKeyboardButton("❌ Cancel", callback_data="sl_cancel")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def create_limit_price_keyboard(self) -> InlineKeyboardMarkup:
        """Create keyboard for limit price selection"""
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Enter Custom Limit", callback_data="sl_limit_custom")],
            [InlineKeyboardButton("🔄 Use Auto (4% buffer)", callback_data="sl_limit_auto")],
            [InlineKeyboardButton("❌ Cancel", callback_data="sl_cancel")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def create_positions_keyboard(self, positions_data: list) -> InlineKeyboardMarkup:
        """Create keyboard for position selection"""
        keyboard = []
        
        for i, position in enumerate(positions_data[:8]):  # Limit to 8 positions
            # Extract position details
            symbol = position.get('product', {}).get('symbol', 'Unknown')
            size = position.get('size', 0)
            entry_price = position.get('entry_price', 0)
            pnl = position.get('unrealized_pnl', 0)
            
            # Create position identifier (use product_id if available, otherwise index)
            position_id = position.get('product', {}).get('id', f"pos_{i}")
            
            # Format position display text
            side = "LONG" if float(size) > 0 else "SHORT"
            pnl_emoji = "🟢" if float(pnl) >= 0 else "🔴"
            
            display_text = f"{symbol} {side} ({pnl_emoji}${pnl})"
            
            keyboard.append([
                InlineKeyboardButton(
                    display_text, 
                    callback_data=f"sl_select_pos_{position_id}"
                )
            ])
        
        # Add cancel option
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="sl_cancel")])
        
        return InlineKeyboardMarkup(keyboard)
    
    async def show_position_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show selectable positions for stop-loss"""
        try:
            # Get open positions
            positions = self.delta_client.get_positions()
            
            if not positions.get('success'):
                await update.message.reply_text(
                    "❌ Unable to fetch positions. Please try again or use:\n"
                    "/stoploss [order_id] for specific order"
                )
                return
            
            positions_data = positions.get('result', [])
            
            if not positions_data:
                await update.message.reply_text(
                    "📊 No open positions found.\n\n"
                    "You need active positions to add stop-loss protection.\n"
                    "Use /positions to check your current positions."
                )
                return
            
            # Store positions data for callback handling
            context.user_data['available_positions'] = positions_data
            
            message = f"""
<b>🛡️ Select Position for Stop-Loss</b>

Choose a position to add stop-loss protection:

<b>Available Positions:</b>
            """.strip()
            
            # Add position details to message
            for i, position in enumerate(positions_data[:5], 1):  # Show first 5 in message
                symbol = position.get('product', {}).get('symbol', 'Unknown')
                size = position.get('size', 0)
                entry_price = position.get('entry_price', 0)
                pnl = position.get('unrealized_pnl', 0)
                
                side = "LONG" if float(size) > 0 else "SHORT"
                pnl_emoji = "🟢" if float(pnl) >= 0 else "🔴"
                
                message += f"""
{i}. <b>{symbol}</b> {side}
   Entry: ${entry_price} | PnL: {pnl_emoji}${pnl}"""
            
            if len(positions_data) > 5:
                message += f"\n\n<i>... and {len(positions_data) - 5} more positions</i>"
            
            message += "\n\nTap a position below to add stop-loss:"
            
            reply_markup = self.create_positions_keyboard(positions_data)
            await update.message.reply_text(
                message, 
                parse_mode=ParseMode.HTML, 
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in show_position_selection: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred fetching positions.")
    
    async def handle_position_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle position selection from inline keyboard"""
        try:
            query = update.callback_query
            await query.answer()
            
            position_id = query.data.replace("sl_select_pos_", "")
            
            # Find the selected position
            positions_data = context.user_data.get('available_positions', [])
            selected_position = None
            
            for position in positions_data:
                pos_id = str(position.get('product', {}).get('id', ''))
                if pos_id == position_id or position_id.startswith('pos_'):
                    # If it's a positional index (pos_0, pos_1, etc.)
                    if position_id.startswith('pos_'):
                        index = int(position_id.split('_')[1])
                        if index < len(positions_data):
                            selected_position = positions_data[index]
                    else:
                        selected_position = position
                    break
            
            if not selected_position:
                await query.edit_message_text("❌ Position not found. Please try again.")
                return
            
            # Store selected position and show stop-loss options
            context.user_data['parent_order'] = self._convert_position_to_order_format(selected_position)
            context.user_data['stoploss_order_id'] = position_id
            
            await self._show_stoploss_options_for_position(query, selected_position)
            
        except Exception as e:
            logger.error(f"Error in handle_position_selection: {e}", exc_info=True)
            await query.edit_message_text("❌ An error occurred. Please try again.")
    
    def _convert_position_to_order_format(self, position: dict) -> dict:
        """Convert position data to order format for stop-loss processing"""
        product = position.get('product', {})
        size = position.get('size', 0)
        entry_price = position.get('entry_price', 0)
        
        return {
            'id': product.get('id', 'unknown'),
            'product_id': product.get('id'),
            'symbol': product.get('symbol', 'Unknown'),
            'side': 'buy' if float(size) > 0 else 'sell',  # Current position side
            'size': abs(float(size)),
            'price': float(entry_price),
            'status': 'filled'
        }
    
    async def _show_stoploss_options_for_position(self, query, position: dict):
        """Show stop-loss options for selected position"""
        product = position.get('product', {})
        symbol = product.get('symbol', 'Unknown')
        size = position.get('size', 0)
        entry_price = position.get('entry_price', 0)
        pnl = position.get('unrealized_pnl', 0)
        
        side = "LONG" if float(size) > 0 else "SHORT"
        pnl_emoji = "🟢" if float(pnl) >= 0 else "🔴"
        
        message = f"""
<b>🛡️ Add Stop-Loss Protection</b>

<b>Selected Position:</b>
• <b>Symbol:</b> {symbol}
• <b>Side:</b> {side}
• <b>Size:</b> {abs(float(size))} contracts
• <b>Entry Price:</b> ${entry_price}
• <b>Current PnL:</b> {pnl_emoji} ${pnl}

<b>Available Stop-Loss Types:</b>

🛑 <b>Stop Market:</b> Triggers market order at stop price
🎯 <b>Stop Limit:</b> Triggers limit order with price control  
📈 <b>Trailing Stop:</b> Follows market with fixed distance

Choose your stop-loss type:
        """.strip()
        
        reply_markup = self.create_stoploss_type_keyboard()
        await query.edit_message_text(message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    
    async def show_stoploss_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str = None):
        """Show stop-loss type selection for a given order or position"""
        try:
            if order_id:
                # Direct order ID provided - use existing logic
                query = update.callback_query
                if query:
                    await query.answer()
                
                # Store order ID for later use
                context.user_data['stoploss_order_id'] = order_id
                
                # Get order details to show context
                order_details = await self._get_order_details(order_id)
                
                if not order_details:
                    error_msg = "❌ Unable to fetch order details. Please try again."
                    if query:
                        await query.edit_message_text(error_msg)
                    else:
                        await update.message.reply_text(error_msg)
                    return
                
                context.user_data['parent_order'] = order_details
                
                message = f"""
<b>🛡️ Add Stop-Loss Protection</b>

<b>Parent Order:</b> #{order_id}
<b>Symbol:</b> {order_details.get('symbol', 'Unknown')}
<b>Side:</b> {order_details.get('side', 'Unknown').title()}
<b>Size:</b> {order_details.get('size', 0)} contracts
<b>Entry Price:</b> ${order_details.get('price', 0)}

<b>Available Stop-Loss Types:</b>

🛑 <b>Stop Market:</b> Triggers market order at stop price
🎯 <b>Stop Limit:</b> Triggers limit order with price control
📈 <b>Trailing Stop:</b> Follows market with fixed distance

Choose your stop-loss type:
                """.strip()
                
                reply_markup = self.create_stoploss_type_keyboard()
                
                if query:
                    await query.edit_message_text(message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
                else:
                    await update.message.reply_text(message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            else:
                # No order ID - show position selection
                await self.show_position_selection(update, context)
            
        except Exception as e:
            logger.error(f"Error in show_stoploss_selection: {e}", exc_info=True)
            error_msg = "❌ An error occurred. Please try again."
            query = update.callback_query
            if query:
                await query.edit_message_text(error_msg)
            else:
                await update.message.reply_text(error_msg)
    
    # ... (keep all existing methods unchanged: handle_stoploss_type_selection, 
    # _handle_stop_market_setup, _handle_stop_limit_setup, etc.)
    
    async def handle_stoploss_type_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle stop-loss type selection"""
        try:
            query = update.callback_query
            await query.answer()
            
            stoploss_type = query.data.replace("sl_type_", "")
            context.user_data['stoploss_type'] = stoploss_type
            
            if stoploss_type == "stop_market":
                await self._handle_stop_market_setup(update, context)
            elif stoploss_type == "stop_limit":
                await self._handle_stop_limit_setup(update, context)
            elif stoploss_type == "trailing_stop":
                await self._handle_trailing_stop_setup(update, context)
            else:
                await query.edit_message_text("❌ Invalid selection. Please try again.")
                
        except Exception as e:
            logger.error(f"Error in handle_stoploss_type_selection: {e}", exc_info=True)
            await query.edit_message_text("❌ An error occurred. Please try again.")
    
    async def _handle_stop_market_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle stop market order setup"""
        query = update.callback_query
        parent_order = context.user_data.get('parent_order', {})
        
        message = f"""
<b>🛑 Stop Market Order Setup</b>

<b>Position:</b> {parent_order.get('symbol', 'Unknown')} ({parent_order.get('side', '').title()})
<b>Entry Price:</b> ${parent_order.get('price', 0)}

<b>How Stop Market Works:</b>
• When trigger price is hit, a market order is executed
• Guarantees execution but not specific price
• Best for quick exits

<b>Enter Trigger Price:</b>
• As percentage: 25% (25% loss from entry)
• As absolute price: 230 (direct price value)

Type your trigger price:
        """.strip()
        
        context.user_data['waiting_for_trigger_price'] = True
        await query.edit_message_text(message, parse_mode=ParseMode.HTML)
    
    async def _handle_stop_limit_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle stop limit order setup"""
        query = update.callback_query
        parent_order = context.user_data.get('parent_order', {})
        
        message = f"""
<b>🎯 Stop Limit Order Setup</b>

<b>Position:</b> {parent_order.get('symbol', 'Unknown')} ({parent_order.get('side', '').title()})
<b>Entry Price:</b> ${parent_order.get('price', 0)}

<b>How Stop Limit Works:</b>
• When trigger price is hit, a limit order is placed
• Better price control but may not execute
• Best for volatile markets

<b>Enter Trigger Price:</b>
• As percentage: 25% (25% loss from entry)
• As absolute price: 230 (direct price value)

Type your trigger price:
        """.strip()
        
        context.user_data['waiting_for_trigger_price'] = True
        await query.edit_message_text(message, parse_mode=ParseMode.HTML)
    
    async def _handle_trailing_stop_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle trailing stop order setup"""
        query = update.callback_query
        parent_order = context.user_data.get('parent_order', {})
        
        message = f"""
<b>📈 Trailing Stop Order Setup</b>

<b>Position:</b> {parent_order.get('symbol', 'Unknown')} ({parent_order.get('side', '').title()})
<b>Entry Price:</b> ${parent_order.get('price', 0)}

<b>How Trailing Stop Works:</b>
• Stop price follows market at fixed distance
• Locks in profits as market moves favorably
• Best for trending markets

<b>Enter Trail Amount:</b>
• As percentage: 10% (trail 10% behind peak)
• As absolute amount: 50 (trail $50 behind)

Type your trail amount:
        """.strip()
        
        context.user_data['waiting_for_trail_amount'] = True
        await query.edit_message_text(message, parse_mode=ParseMode.HTML)
    
    # ... (keep all other existing methods: handle_trigger_price_input, 
    # handle_trail_amount_input, _ask_limit_price, etc. - no changes needed)
    
    async def handle_trigger_price_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle trigger price input from user"""
        try:
            if not context.user_data.get('waiting_for_trigger_price'):
                return
            
            user_input = update.message.text.strip()
            parent_order = context.user_data.get('parent_order', {})
            entry_price = float(parent_order.get('price', 0))
            side = parent_order.get('side', '').lower()
            stoploss_type = context.user_data.get('stoploss_type')
            
            # Validate and parse trigger price
            is_valid, trigger_price, error_msg = self._parse_price_input(user_input, entry_price, side)
            
            if not is_valid:
                await update.message.reply_text(f"❌ {error_msg}")
                return
            
            context.user_data['trigger_price'] = trigger_price
            context.user_data['waiting_for_trigger_price'] = False
            
            # For stop limit, ask about limit price
            if stoploss_type == "stop_limit":
                await self._ask_limit_price(update, context, trigger_price, entry_price, side)
            else:
                # For stop market, execute immediately
                await self._execute_stoploss_order(update, context)
                
        except Exception as e:
            logger.error(f"Error in handle_trigger_price_input: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred processing trigger price.")
    
    async def handle_trail_amount_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle trail amount input for trailing stops"""
        try:
            if not context.user_data.get('waiting_for_trail_amount'):
                return
            
            user_input = update.message.text.strip()
            parent_order = context.user_data.get('parent_order', {})
            entry_price = float(parent_order.get('price', 0))
            
            # Parse trail amount
            is_valid, trail_amount, error_msg = self._parse_trail_amount(user_input, entry_price)
            
            if not is_valid:
                await update.message.reply_text(f"❌ {error_msg}")
                return
            
            context.user_data['trail_amount'] = trail_amount
            context.user_data['waiting_for_trail_amount'] = False
            
            # Execute trailing stop order
            await self._execute_trailing_stop_order(update, context)
                
        except Exception as e:
            logger.error(f"Error in handle_trail_amount_input: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred processing trail amount.")
    
    async def _ask_limit_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                              trigger_price: float, entry_price: float, side: str):
        """Ask user about limit price for stop limit orders"""
        # Calculate suggested limit price (4% buffer)
        if side == 'buy':  # Long position, selling to exit
            suggested_limit = trigger_price * 0.96  # 4% below trigger
        else:  # Short position, buying to exit
            suggested_limit = trigger_price * 1.04  # 4% above trigger
        
        message = f"""
<b>🎯 Set Limit Price</b>

<b>Trigger Price:</b> ${trigger_price:,.2f}
<b>Suggested Limit:</b> ${suggested_limit:,.2f} (4% buffer)

<b>Limit Price Options:</b>
• <b>Auto:</b> Use suggested price with 4% safety buffer
• <b>Custom:</b> Enter your own limit price

Delta Exchange auto-fills limit price, but you can customize it:
        """.strip()
        
        reply_markup = self.create_limit_price_keyboard()
        await update.message.reply_text(message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    
    async def handle_limit_price_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle limit price selection"""
        try:
            query = update.callback_query
            await query.answer()
            
            selection = query.data.replace("sl_limit_", "")
            
            if selection == "auto":
                # Use automatic 4% buffer
                trigger_price = context.user_data.get('trigger_price', 0)
                parent_order = context.user_data.get('parent_order', {})
                side = parent_order.get('side', '').lower()
                
                if side == 'buy':  # Long position
                    limit_price = trigger_price * 0.96  # 4% below trigger
                else:  # Short position
                    limit_price = trigger_price * 1.04  # 4% above trigger
                
                context.user_data['limit_price'] = limit_price
                await self._execute_stoploss_order(update, context)
                
            elif selection == "custom":
                # Ask for custom limit price
                await self._ask_custom_limit_price(update, context)
            
        except Exception as e:
            logger.error(f"Error in handle_limit_price_selection: {e}", exc_info=True)
            await query.edit_message_text("❌ An error occurred. Please try again.")
    
    async def _ask_custom_limit_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ask for custom limit price input"""
        query = update.callback_query
        trigger_price = context.user_data.get('trigger_price', 0)
        
        message = f"""
<b>🎯 Enter Custom Limit Price</b>

<b>Trigger Price:</b> ${trigger_price:,.2f}

Enter your limit price as a number:
Example: 240

<b>Important:</b>
• For long positions: Limit should be ≤ trigger price
• For short positions: Limit should be ≥ trigger price

Type your limit price:
        """.strip()
        
        context.user_data['waiting_for_limit_price'] = True
        await query.edit_message_text(message, parse_mode=ParseMode.HTML)
    
    async def handle_limit_price_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle custom limit price input"""
        try:
            if not context.user_data.get('waiting_for_limit_price'):
                return
            
            user_input = update.message.text.strip()
            trigger_price = context.user_data.get('trigger_price', 0)
            parent_order = context.user_data.get('parent_order', {})
            side = parent_order.get('side', '').lower()
            
            try:
                limit_price = float(user_input)
            except ValueError:
                await update.message.reply_text("❌ Please enter a valid number for limit price.")
                return
            
            # Validate limit price logic
            if side == 'buy' and limit_price > trigger_price:  # Long position
                await update.message.reply_text(
                    "⚠️ For long positions, limit price should be ≤ trigger price.\n"
                    "Otherwise, the order may not execute as intended."
                )
            elif side == 'sell' and limit_price < trigger_price:  # Short position  
                await update.message.reply_text(
                    "⚠️ For short positions, limit price should be ≥ trigger price.\n"
                    "Otherwise, the order may not execute as intended."
                )
            
            context.user_data['limit_price'] = limit_price
            context.user_data['waiting_for_limit_price'] = False
            
            await self._execute_stoploss_order(update, context)
                
        except Exception as e:
            logger.error(f"Error in handle_limit_price_input: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred processing limit price.")
    
    async def _execute_stoploss_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute the stop-loss order"""
        try:
            parent_order = context.user_data.get('parent_order', {})
            stoploss_type = context.user_data.get('stoploss_type')
            trigger_price = context.user_data.get('trigger_price')
            limit_price = context.user_data.get('limit_price')
            
            product_id = parent_order.get('product_id')
            size = abs(int(parent_order.get('size', 0)))  # Absolute size for exit
            side = 'sell' if parent_order.get('side') == 'buy' else 'buy'  # Opposite side
            
            loading_msg = await update.message.reply_text("🔄 Placing stop-loss order...")
            
            # Place stop-loss order based on type
            if stoploss_type == "stop_market":
                result = self.delta_client.place_stop_order(
                    product_id=product_id,
                    size=size,
                    side=side,
                    stop_price=str(trigger_price),
                    order_type="market_order"
                )
            else:  # stop_limit
                result = self.delta_client.place_stop_order(
                    product_id=product_id,
                    size=size,
                    side=side,
                    stop_price=str(trigger_price),
                    limit_price=str(limit_price),
                    order_type="limit_order"
                )
            
            # Format and send result
            message = self._format_stoploss_result(result, stoploss_type, parent_order, 
                                                  trigger_price, limit_price, size, side)
            
            await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
            
            # Clear user data
            self._clear_stoploss_data(context)
            
        except Exception as e:
            logger.error(f"Error in _execute_stoploss_order: {e}", exc_info=True)
            await update.message.reply_text("❌ Failed to place stop-loss order. Please try again.")
    
    async def _execute_trailing_stop_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute trailing stop order"""
        try:
            parent_order = context.user_data.get('parent_order', {})
            trail_amount = context.user_data.get('trail_amount')
            
            product_id = parent_order.get('product_id')
            size = abs(int(parent_order.get('size', 0)))
            side = 'sell' if parent_order.get('side') == 'buy' else 'buy'
            
            loading_msg = await update.message.reply_text("🔄 Placing trailing stop order...")
            
            result = self.delta_client.place_stop_order(
                product_id=product_id,
                size=size,
                side=side,
                trail_amount=str(trail_amount),
                order_type="market_order",
                isTrailingStopLoss=True
            )
            
            # Format and send result
            message = self._format_trailing_stop_result(result, parent_order, trail_amount, size, side)
            
            await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
            
            # Clear user data
            self._clear_stoploss_data(context)
            
        except Exception as e:
            logger.error(f"Error in _execute_trailing_stop_order: {e}", exc_info=True)
            await update.message.reply_text("❌ Failed to place trailing stop order. Please try again.")
    
    def _parse_price_input(self, user_input: str, entry_price: float, side: str) -> tuple:
        """Parse user input for trigger price"""
        try:
            user_input = user_input.strip()
            
            if user_input.endswith('%'):
                # Percentage input
                percentage = float(user_input[:-1])
                if percentage <= 0 or percentage >= 100:
                    return False, 0, "Percentage must be between 0% and 100%"
                
                # Calculate trigger price based on side and percentage loss
                if side == 'buy':  # Long position, stop when price falls
                    trigger_price = entry_price * (1 - percentage / 100)
                else:  # Short position, stop when price rises
                    trigger_price = entry_price * (1 + percentage / 100)
                
                return True, trigger_price, ""
            
            else:
                # Direct price input
                trigger_price = float(user_input)
                if trigger_price <= 0:
                    return False, 0, "Price must be greater than 0"
                
                return True, trigger_price, ""
                
        except ValueError:
            return False, 0, "Please enter a valid number or percentage (e.g., 25% or 230)"
    
    def _parse_trail_amount(self, user_input: str, entry_price: float) -> tuple:
        """Parse user input for trail amount"""
        try:
            user_input = user_input.strip()
            
            if user_input.endswith('%'):
                # Percentage input
                percentage = float(user_input[:-1])
                if percentage <= 0 or percentage >= 50:
                    return False, 0, "Trail percentage must be between 0% and 50%"
                
                # Calculate trail amount as percentage of entry price
                trail_amount = entry_price * (percentage / 100)
                return True, trail_amount, ""
            
            else:
                # Direct amount input
                trail_amount = float(user_input)
                if trail_amount <= 0:
                    return False, 0, "Trail amount must be greater than 0"
                
                return True, trail_amount, ""
                
        except ValueError:
            return False, 0, "Please enter a valid number or percentage (e.g., 10% or 50)"
    
    def _format_stoploss_result(self, result: dict, stoploss_type: str, parent_order: dict, 
                               trigger_price: float, limit_price: float, size: int, side: str) -> str:
        """Format stop-loss order result message"""
        try:
            type_name = "Stop Market" if stoploss_type == "stop_market" else "Stop Limit"
            symbol = parent_order.get('symbol', 'Unknown')
            
            message = f"<b>🛡️ {type_name} Order Placed</b>\n\n"
            
            if result.get('success'):
                order_id = result.get('result', {}).get('id', 'N/A')
                message += f"✅ <b>Order Successful!</b>\n\n"
                message += f"<b>Stop-Loss Details:</b>\n"
                message += f"Order ID: {order_id}\n"
                message += f"Symbol: {symbol}\n"
                message += f"Type: {type_name}\n"
                message += f"Side: {side.title()}\n"
                message += f"Size: {size} contracts\n"
                message += f"Trigger Price: ${trigger_price:,.2f}\n"
                
                if stoploss_type == "stop_limit" and limit_price:
                    message += f"Limit Price: ${limit_price:,.2f}\n"
                
                message += f"\n<b>Protection:</b> Your position is now protected!"
            else:
                error_msg = result.get('error', 'Unknown error')
                message += f"❌ <b>Order Failed</b>\n\n"
                message += f"Error: {error_msg}\n"
                message += f"Please try again or check your position."
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting stop-loss result: {e}")
            return "Stop-loss order completed. Check your orders for details."
    
    def _format_trailing_stop_result(self, result: dict, parent_order: dict, 
                                   trail_amount: float, size: int, side: str) -> str:
        """Format trailing stop result message"""
        try:
            symbol = parent_order.get('symbol', 'Unknown')
            
            message = f"<b>📈 Trailing Stop Order Placed</b>\n\n"
            
            if result.get('success'):
                order_id = result.get('result', {}).get('id', 'N/A')
                message += f"✅ <b>Order Successful!</b>\n\n"
                message += f"<b>Trailing Stop Details:</b>\n"
                message += f"Order ID: {order_id}\n"
                message += f"Symbol: {symbol}\n"
                message += f"Side: {side.title()}\n"
                message += f"Size: {size} contracts\n"
                message += f"Trail Amount: ${trail_amount:,.2f}\n"
                message += f"\n<b>Protection:</b> Stop will trail the market!"
            else:
                error_msg = result.get('error', 'Unknown error')
                message += f"❌ <b>Order Failed</b>\n\n"
                message += f"Error: {error_msg}\n"
                message += f"Please try again or check your position."
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting trailing stop result: {e}")
            return "Trailing stop order completed. Check your orders for details."
    
    async def _get_order_details(self, order_id: str) -> dict:
        """Get order details from Delta Exchange"""
        try:
            # Mock data for now - replace with actual API call
            return {
                'id': order_id,
                'product_id': 12345,
                'symbol': 'BTC-OPTIONS',
                'side': 'buy',
                'size': 10,
                'price': 250.50,
                'status': 'filled'
            }
        except Exception as e:
            logger.error(f"Error getting order details: {e}")
            return None
    
    def _clear_stoploss_data(self, context: ContextTypes.DEFAULT_TYPE):
        """Clear stop-loss related data from user context"""
        keys_to_clear = [
            'stoploss_order_id', 'parent_order', 'stoploss_type',
            'trigger_price', 'limit_price', 'trail_amount',
            'waiting_for_trigger_price', 'waiting_for_limit_price',
            'waiting_for_trail_amount', 'available_positions'
        ]
        
        for key in keys_to_clear:
            context.user_data.pop(key, None)
