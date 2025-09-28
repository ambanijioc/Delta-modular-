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
        """Create keyboard for position selection with proper indexing"""
        keyboard = []
        
        for i, position in enumerate(positions_data[:8]):  # Limit to 8 positions
            # Use simple index-based identification to avoid ID issues
            position_index = i
            
            # Extract position details with fallbacks
            product = position.get('product', {})
            size = float(position.get('size', 0))
            pnl = float(position.get('unrealized_pnl', 0))
            
            # Determine position side and format
            side = "LONG" if size > 0 else "SHORT"
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            
            # Enhanced symbol extraction with multiple fallbacks
            symbol = self._extract_symbol_from_position(position)
            
            # Create display text
            display_text = f"{symbol} {side} ({pnl_emoji}${pnl:,.0f})"
            
            # Truncate if too long for button (Telegram limit ~64 chars)
            if len(display_text) > 35:
                display_text = display_text[:32] + "..."
            
            keyboard.append([
                InlineKeyboardButton(
                    display_text, 
                    callback_data=f"sl_select_pos_{position_index}"  # Use simple index
                )
            ])
        
        # Add cancel option
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="sl_cancel")])
        
        return InlineKeyboardMarkup(keyboard)
    
    def _extract_symbol_from_position(self, position: dict) -> str:
        """Enhanced symbol extraction with Delta Exchange format support"""
        # Try 1: Direct product symbol (should work now with enhanced API calls)
        product = position.get('product', {})
        symbol = product.get('symbol', '')
        
        logger.info(f"Raw symbol from product: '{symbol}'")
        
        # Check if we have a valid Delta Exchange format symbol
        if symbol and symbol != 'Unknown':
            # Delta Exchange format examples:
            # C-BTC-112000-290925 (Call, BTC, Strike 112000, Exp 29-09-25)
            # P-BTC-85000-290925 (Put, BTC, Strike 85000, Exp 29-09-25)
            if '-' in symbol:
                parts = symbol.split('-')
                if len(parts) >= 4:
                    option_type = parts[0]  # C or P
                    underlying = parts[1]   # BTC
                    strike = parts[2]       # 112000
                    expiry = parts[3]       # 290925
                    
                    # Format for better display
                    if option_type in ['C', 'P']:
                        option_name = 'CE' if option_type == 'C' else 'PE'
                        
                        # Format expiry date
                        if len(expiry) == 6:  # DDMMYY format
                            day = expiry[:2]
                            month = expiry[2:4]
                            year = '20' + expiry[4:6]
                            formatted_expiry = f"{day}/{month}/{year}"
                        else:
                            formatted_expiry = expiry
                        
                        return f"{underlying} {strike} {option_name}"
            
            # Return the symbol as-is if it looks valid
            return symbol
        
        # Try 2: Build from product components if symbol is missing/invalid
        underlying_asset = product.get('underlying_asset', {})
        if isinstance(underlying_asset, dict):
            base_symbol = underlying_asset.get('symbol', 'BTC')
        else:
            base_symbol = 'BTC'
        
        contract_type = product.get('contract_type', '').lower()
        strike_price = product.get('strike_price', '')
        
        logger.info(f"Building from components: underlying={base_symbol}, contract_type={contract_type}, strike={strike_price}")
        
        # Enhanced option type detection
        if 'call' in contract_type:
            option_type = 'CE'
        elif 'put' in contract_type:
            option_type = 'PE'
        elif 'option' in contract_type:
            option_type = 'Option'
        elif 'future' in contract_type or 'perpetual' in contract_type:
            return f"{base_symbol} Future"
        else:
            option_type = 'Unknown'
        
        if strike_price and option_type in ['CE', 'PE']:
            return f"{base_symbol} {strike_price} {option_type}"
        elif option_type != 'Unknown':
            return f"{base_symbol} {option_type}"
        
        # Try 3: Check product ID for clues
        product_id = product.get('id') or position.get('product_id')
        if product_id:
            return f"{base_symbol} #{product_id}"
        
        # Final fallback
        return f"{base_symbol} Position"
    
    async def show_position_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show selectable positions for stop-loss using enhanced data"""
        try:
            # Use the enhanced positions method
            positions = self.delta_client.force_enhance_positions()
            
            if not positions.get('success'):
                await update.message.reply_text(
                    "❌ Unable to fetch positions. Please try again or use:\n"
                    "/stoploss [order_id] for specific order"
                )
                return
            
            positions_data = positions.get('result', [])
            
            # Filter out zero positions
            active_positions = [pos for pos in positions_data if float(pos.get('size', 0)) != 0]
            
            if not active_positions:
                await update.message.reply_text(
                    "📊 No open positions found.\n\n"
                    "You need active positions to add stop-loss protection.\n"
                    "Use /positions to check your current positions."
                )
                return
            
            # Store positions data with index mapping
            context.user_data['available_positions'] = active_positions
            
            message = f"""
<b>🛡️ Select Position for Stop-Loss</b>

Choose a position to add stop-loss protection:

<b>Available Positions:</b>
            """.strip()
            
            # Add position details to message with enhanced display
            for i, position in enumerate(active_positions[:5], 1):  # Show first 5 in message
                # Get enhanced symbol from product data
                product = position.get('product', {})
                symbol = product.get('symbol', 'Unknown')
                
                # Format symbol for display
                display_symbol = self._format_symbol_for_display(symbol)
                
                size = float(position.get('size', 0))
                entry_price = float(position.get('entry_price', 0))
                pnl = float(position.get('unrealized_pnl', 0))
                
                side = "LONG" if size > 0 else "SHORT"
                pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                
                entry_text = f"${entry_price:,.4f}" if entry_price > 0 else "N/A"
                
                message += f"""
{i}. <b>{display_symbol}</b> {side}
   Entry: {entry_text} | PnL: {pnl_emoji}${pnl:,.2f}"""
            
            if len(active_positions) > 5:
                message += f"\n\n<i>... and {len(active_positions) - 5} more positions</i>"
            
            message += "\n\nTap a position below to add stop-loss:"
            
            reply_markup = self.create_positions_keyboard(active_positions)
            await update.message.reply_text(
                message, 
                parse_mode=ParseMode.HTML, 
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in show_position_selection: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred fetching positions.")
    
    def _format_symbol_for_display(self, symbol: str) -> str:
        """Format symbol for display using the same logic as positions"""
        if not symbol or symbol == 'Unknown':
            return 'Unknown Position'
        
        # Handle Delta Exchange format: C-BTC-112000-290925
        if '-' in symbol:
            parts = symbol.split('-')
            if len(parts) >= 4:
                option_type = parts[0]  # C or P
                underlying = parts[1]   # BTC
                strike = parts[2]       # 112000
                
                # Convert option type
                if option_type == 'C':
                    option_name = 'CE'
                elif option_type == 'P':
                    option_name = 'PE'
                else:
                    option_name = option_type
                
                return f"{underlying} {strike} {option_name}"
        
        # Return original symbol if not in expected format
        return symbol
    
    def create_positions_keyboard(self, positions_data: list) -> InlineKeyboardMarkup:
        """Create keyboard for position selection with enhanced symbols"""
        keyboard = []
        
        for i, position in enumerate(positions_data[:8]):  # Limit to 8 positions
            # Use simple index-based identification
            position_index = i
            
            # Get enhanced symbol
            product = position.get('product', {})
            symbol = product.get('symbol', 'Unknown')
            display_symbol = self._format_symbol_for_display(symbol)
            
            size = float(position.get('size', 0))
            pnl = float(position.get('unrealized_pnl', 0))
            
            # Determine position side and format
            side = "LONG" if size > 0 else "SHORT"
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            
            # Create display text
            display_text = f"{display_symbol} {side} ({pnl_emoji}${pnl:,.0f})"
            
            # Truncate if too long for button
            if len(display_text) > 35:
                display_text = display_text[:32] + "..."
            
            keyboard.append([
                InlineKeyboardButton(
                    display_text, 
                    callback_data=f"sl_select_pos_{position_index}"
                )
            ])
        
        # Add cancel option
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="sl_cancel")])
        
        return InlineKeyboardMarkup(keyboard)

    async def handle_position_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle position selection from inline keyboard with fixed matching"""
        try:
            query = update.callback_query
            await query.answer()
            
            callback_data = query.data
            logger.info(f"Processing position selection: {callback_data}")
            
            # Extract position index from callback data
            if not callback_data.startswith("sl_select_pos_"):
                await query.edit_message_text("❌ Invalid selection. Please try again.")
                return
            
            position_identifier = callback_data.replace("sl_select_pos_", "")
            
            # Get stored positions
            positions_data = context.user_data.get('available_positions', [])
            
            if not positions_data:
                await query.edit_message_text("❌ Position data expired. Please use /stoploss again.")
                return
            
            selected_position = None
            
            try:
                # Try to parse as index first
                position_index = int(position_identifier)
                if 0 <= position_index < len(positions_data):
                    selected_position = positions_data[position_index]
                    logger.info(f"Selected position by index: {position_index}")
            except ValueError:
                # If not a number, try to match by product_id
                logger.info(f"Trying to match by product_id: {position_identifier}")
                for position in positions_data:
                    product = position.get('product', {})
                    product_id = str(product.get('id', ''))
                    alt_product_id = str(position.get('product_id', ''))
                    
                    if (product_id and product_id == position_identifier) or \
                       (alt_product_id and alt_product_id == position_identifier):
                        selected_position = position
                        logger.info(f"Found position by product_id: {position_identifier}")
                        break
            
            if not selected_position:
                logger.error(f"Position not found. Identifier: {position_identifier}, Available positions: {len(positions_data)}")
                
                # Debug information
                debug_info = "\n".join([
                    f"Index {i}: ID={pos.get('product', {}).get('id')} | ProdID={pos.get('product_id')}"
                    for i, pos in enumerate(positions_data[:3])
                ])
                
                await query.edit_message_text(
                    f"❌ Position not found. Please try /stoploss again.\n\n"
                    f"Debug info:\nLooking for: {position_identifier}\n{debug_info}"
                )
                return
            
            # Convert position to order format and store
            order_data = self._convert_position_to_order_format(selected_position)
            context.user_data['parent_order'] = order_data
            context.user_data['stoploss_order_id'] = position_identifier
            
            logger.info(f"Successfully converted position to order format: {order_data.get('symbol')}")
            
            # Show stop-loss options
            await self._show_stoploss_options_for_position(query, selected_position)
            
        except Exception as e:
            logger.error(f"Error in handle_position_selection: {e}", exc_info=True)
            await query.edit_message_text("❌ An error occurred. Please try again with /stoploss.")
    
    def _convert_position_to_order_format(self, position: dict) -> dict:
        """Convert position data to order format for stop-loss processing"""
        try:
            product = position.get('product', {})
            size = float(position.get('size', 0))
            entry_price = float(position.get('entry_price', 0))
            
            # Get product_id with multiple fallbacks
            product_id = product.get('id') or position.get('product_id')
            
            # Enhanced symbol extraction
            symbol = self._extract_symbol_from_position(position)
            
            # Determine current position side for exit order calculation
            current_side = 'buy' if size > 0 else 'sell'
            
            order_data = {
                'id': product_id or f"pos_{symbol}",
                'product_id': product_id,
                'symbol': symbol,
                'side': current_side,  # Current position side
                'size': abs(size),     # Absolute size
                'price': entry_price,  # Entry price for calculations
                'status': 'filled',
                'position_size': size  # Store original size for reference
            }
            
            logger.info(f"Converted position: {symbol}, Size: {size}, Side: {current_side}")
            
            return order_data
            
        except Exception as e:
            logger.error(f"Error converting position to order format: {e}")
            return {
                'id': 'unknown',
                'product_id': None,
                'symbol': 'Unknown Position',
                'side': 'buy' if float(position.get('size', 0)) > 0 else 'sell',
                'size': abs(float(position.get('size', 1))),
                'price': float(position.get('entry_price', 0)),
                'status': 'filled'
            }
    
    async def _show_stoploss_options_for_position(self, query, position: dict):
        """Show stop-loss options for selected position"""
        try:
            symbol = self._extract_symbol_from_position(position)
            size = float(position.get('size', 0))
            entry_price = float(position.get('entry_price', 0))
            pnl = float(position.get('unrealized_pnl', 0))
            
            side = "LONG" if size > 0 else "SHORT"
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            
            message = f"""
<b>🛡️ Add Stop-Loss Protection</b>

<b>Selected Position:</b>
• <b>Symbol:</b> {symbol}
• <b>Side:</b> {side}
• <b>Size:</b> {abs(size):,.0f} contracts
• <b>Entry Price:</b> ${entry_price:,.4f}
• <b>Current PnL:</b> {pnl_emoji} ${pnl:,.2f}

<b>Available Stop-Loss Types:</b>

🛑 <b>Stop Market:</b> Triggers market order at stop price
🎯 <b>Stop Limit:</b> Triggers limit order with price control  
📈 <b>Trailing Stop:</b> Follows market with fixed distance

Choose your stop-loss type:
            """.strip()
            
            reply_markup = self.create_stoploss_type_keyboard()
            await query.edit_message_text(message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in _show_stoploss_options_for_position: {e}")
            await query.edit_message_text("❌ An error occurred showing stop-loss options.")
    
    # Keep all other existing methods unchanged (handle_stoploss_type_selection, 
    # _handle_stop_market_setup, etc.)
    
    async def show_stoploss_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str = None):
        """Show stop-loss selection - main entry point"""
        try:
            if order_id:
                # Direct order ID provided - use existing logic with mock data
                query = update.callback_query
                if query:
                    await query.answer()
                
                context.user_data['stoploss_order_id'] = order_id
                
                # Mock order details since we don't have real order API
                order_details = {
                    'id': order_id,
                    'product_id': 12345,
                    'symbol': 'BTC-OPTIONS',
                    'side': 'buy',
                    'size': 10,
                    'price': 250.50,
                    'status': 'filled'
                }
                
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
    
    # Add remaining methods with proper indentation...
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
<b>Entry Price:</b> ${parent_order.get('price', 0):,.4f}

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
<b>Entry Price:</b> ${parent_order.get('price', 0):,.4f}

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
<b>Entry Price:</b> ${parent_order.get('price', 0):,.4f}

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
    
    # ... (include all other existing methods with proper indentation)
    # For brevity, I'll show the key remaining methods:
    
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
            
    async def handle_trigger_price_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle trigger price input from user"""
        try:
            logger.info("Handling trigger price input")
            
            if not context.user_data.get('waiting_for_trigger_price'):
                logger.warning("Not waiting for trigger price")
                return
            
            user_input = update.message.text.strip()
            parent_order = context.user_data.get('parent_order', {})
            entry_price = float(parent_order.get('price', 0))
            side = parent_order.get('side', '').lower()
            stoploss_type = context.user_data.get('stoploss_type')
            
            logger.info(f"Processing input: {user_input}, entry_price: {entry_price}, side: {side}")
            
            # Validate and parse trigger price
            is_valid, trigger_price, error_msg = self._parse_price_input(user_input, entry_price, side)
            
            if not is_valid:
                await update.message.reply_text(f"❌ {error_msg}")
                return
            
            context.user_data['trigger_price'] = trigger_price
            context.user_data['waiting_for_trigger_price'] = False
            
            logger.info(f"Parsed trigger price: {trigger_price}")
            
            # For stop limit, ask about limit price
            if stoploss_type == "stop_limit":
                await self._ask_limit_price(update, context, trigger_price, entry_price, side)
            else:
                # For stop market, execute immediately
                await self._execute_stoploss_order(update, context)
                
        except Exception as e:
            logger.error(f"Error in handle_trigger_price_input: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred processing trigger price.")
    
    def _parse_price_input(self, user_input: str, entry_price: float, side: str) -> tuple:
        """Parse user input for trigger price"""
        try:
            user_input = user_input.strip()
            
            logger.info(f"Parsing price input: '{user_input}', entry: {entry_price}, side: {side}")
            
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
                
                logger.info(f"Calculated percentage trigger: {trigger_price}")
                return True, trigger_price, ""
            
            else:
                # Direct price input
                trigger_price = float(user_input)
                if trigger_price <= 0:
                    return False, 0, "Price must be greater than 0"
                
                logger.info(f"Direct price trigger: {trigger_price}")
                return True, trigger_price, ""
                
        except ValueError as e:
            logger.error(f"ValueError parsing price: {e}")
            return False, 0, "Please enter a valid number or percentage (e.g., 25% or 15)"
    
    async def _execute_stoploss_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute the stop-loss order"""
        try:
            parent_order = context.user_data.get('parent_order', {})
            stoploss_type = context.user_data.get('stoploss_type')
            trigger_price = context.user_data.get('trigger_price')
            limit_price = context.user_data.get('limit_price')
            
            logger.info(f"Executing stop-loss: type={stoploss_type}, trigger={trigger_price}")
            
            product_id = parent_order.get('product_id')
            size = abs(int(parent_order.get('size', 0)))  # Absolute size for exit
            side = 'sell' if parent_order.get('side') == 'buy' else 'buy'  # Opposite side
            
            loading_msg = await update.message.reply_text("🔄 Placing stop-loss order...")
            
            # For now, simulate the order (since we don't have real trading enabled)
            # In real implementation, use the Delta API
            
            message = f"""<b>🛡️ Stop-Loss Order Simulated</b>

✅ <b>Order Details:</b>
• Symbol: {parent_order.get('symbol')}
• Type: {stoploss_type.replace('_', ' ').title()}
• Side: {side.title()}
• Size: {size} contracts
• Trigger Price: ${trigger_price:,.4f}
"""
            
            if stoploss_type == "stop_limit" and limit_price:
                message += f"• Limit Price: ${limit_price:,.4f}\n"
            
            message += f"\n<b>⚠️ Note:</b> This is a simulation. Real order placement requires additional API setup."
            
            await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
            
            # Clear user data
            self._clear_stoploss_data(context)
            
        except Exception as e:
            logger.error(f"Error in _execute_stoploss_order: {e}", exc_info=True)
            await update.message.reply_text("❌ Failed to process stop-loss order.")

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

<b>Trigger Price:</b> ${trigger_price:,.4f}
<b>Suggested Limit:</b> ${suggested_limit:,.4f} (4% buffer)

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

<b>Trigger Price:</b> ${trigger_price:,.4f}

Enter your limit price as a number:
Example: 18

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
            return False, 0, "Please enter a valid number or percentage (e.g., 10% or 5)"
    
    async def _execute_trailing_stop_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute trailing stop order"""
        try:
            parent_order = context.user_data.get('parent_order', {})
            trail_amount = context.user_data.get('trail_amount')
            
            product_id = parent_order.get('product_id')
            size = abs(int(parent_order.get('size', 0)))
            side = 'sell' if parent_order.get('side') == 'buy' else 'buy'
            
            loading_msg = await update.message.reply_text("🔄 Placing trailing stop order...")
            
            # Simulate trailing stop order
            message = f"""<b>📈 Trailing Stop Order Simulated</b>

✅ <b>Order Details:</b>
• Symbol: {parent_order.get('symbol')}
• Side: {side.title()}
• Size: {size} contracts
• Trail Amount: ${trail_amount:,.4f}

<b>⚠️ Note:</b> This is a simulation. Real order placement requires additional API setup.
"""
            
            await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
            
            # Clear user data
            self._clear_stoploss_data(context)
            
        except Exception as e:
            logger.error(f"Error in _execute_trailing_stop_order: {e}", exc_info=True)
            await update.message.reply_text("❌ Failed to place trailing stop order.")
    
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
        
        logger.info("Cleared stop-loss data from user context")
            
