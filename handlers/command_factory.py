# handlers/command_factory.py
"""
Factory for creating command handlers with account-specific context.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from api.delta_client import DeltaClient

logger = logging.getLogger(__name__)

class CommandHandlerFactory:
    """Factory to create command handlers for a specific account"""
    
    def __init__(self, delta_client: DeltaClient, account_id: str, account_name: str):
        self.delta_client = delta_client
        self.account_id = account_id
        self.account_name = account_name
        
        # Import your existing handlers
        from handlers.expiry_handler import ExpiryHandler
        from handlers.options_handler import OptionsHandler
        from handlers.stoploss_handler import StoplossHandler
        from handlers.multi_stoploss_handler import MultiStrikeStopl0ssHandler
        
        # Initialize handlers with this account's delta client
        self.expiry_handler = ExpiryHandler(delta_client)
        self.options_handler = OptionsHandler(delta_client)
        self.stoploss_handler = StoplossHandler(delta_client)
        self.multi_stoploss_handler = MultiStrikeStopl0ssHandler(delta_client)
        
        logger.info(f"✅ Command handlers created for {account_name}")
    
    # ============= COMMAND HANDLERS =============
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command - shows account name in header"""
        try:
            logger.info(f"[{self.account_id}] Start command from user: {update.effective_user.id}")
            
            # Get portfolio
            import asyncio
            try:
                portfolio = await asyncio.wait_for(
                    asyncio.to_thread(self.delta_client.get_portfolio_summary),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                portfolio = {"success": False}
            
            # Build message
            message_parts = []
            
            # Add account identifier
            message_parts.append(f"<b>🏦 {self.account_name}</b>")
            
            # Add portfolio balance
            if portfolio.get('success'):
                balances = portfolio.get('result', [])
                total_balance = sum(float(b.get('available_balance', 0)) for b in balances)
                if total_balance > 0:
                    message_parts.append(f"💰 <b>Portfolio Value:</b> ₹{total_balance:,.2f}")
            
            # Main welcome message
            welcome_section = """
<b>🚀 Welcome to Delta Options Bot!</b>

<b>Available Actions:</b>
• 📊 View your current positions
• 📈 Start new options trading
• 🛡️ Multi-strike stop-loss protection
• 💰 Check portfolio summary

Choose an action below:"""
            
            message_parts.append(welcome_section)
            full_message = "\n\n".join(message_parts)
            
            # Create keyboard
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            from telegram.constants import ParseMode
            
            keyboard = [
                [InlineKeyboardButton("📅 Select Expiry", callback_data="select_expiry")],
                [InlineKeyboardButton("📊 Show Positions", callback_data="show_positions")],
                [InlineKeyboardButton("🛡️ Multi-Strike Stop-Loss", callback_data="multi_strike_stoploss")],
                [InlineKeyboardButton("💰 Portfolio Summary", callback_data="portfolio_summary")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                full_message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"[{self.account_id}] Error in start_command: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred. Please try again.")
    
    async def positions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Positions command"""
        try:
            logger.info(f"[{self.account_id}] Positions command from user: {update.effective_user.id}")
            
            loading_msg = await update.message.reply_text("🔄 Fetching positions...")
            
            # Import your position formatting function
            from utils.helpers import format_enhanced_positions_with_live_data
            from telegram.constants import ParseMode
            
            # Get positions
            positions = self.delta_client.force_enhance_positions()
            portfolio = self.delta_client.get_portfolio_summary()
            
            if not positions.get('success'):
                await loading_msg.edit_text("❌ Failed to fetch positions.")
                return
            
            positions_data = positions.get('result', [])
            message_parts = []
            
            # Add account identifier
            message_parts.append(f"<b>🏦 {self.account_name}</b>\n")
            
            # Format positions
            if positions_data:
                positions_message = format_enhanced_positions_with_live_data(positions_data, self.delta_client)
                message_parts.append(positions_message)
            else:
                message_parts.append("📊 <b>No Open Positions</b>\n\nYou currently have no active positions.")
            
            # Add portfolio balance
            if portfolio.get('success'):
                balances = portfolio.get('result', [])
                total_balance = sum(float(b.get('available_balance', 0)) for b in balances)
                if total_balance > 0:
                    message_parts.append(f"💰 <b>Total Portfolio Value:</b> ₹{total_balance:,.2f}")
            
            full_message = "\n\n".join(message_parts)
            await loading_msg.edit_text(full_message, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            logger.error(f"[{self.account_id}] Error in positions_command: {e}", exc_info=True)
            await update.message.reply_text("❌ Failed to fetch positions.")
    
    async def orders_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Orders command - delegate to your existing implementation"""
        # Your existing orders command implementation
        # Just add account logging
        logger.info(f"[{self.account_id}] Orders command")
        # ... rest of your existing orders_command code ...
    
    async def portfolio_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Portfolio command"""
        # Your existing portfolio command
        logger.info(f"[{self.account_id}] Portfolio command")
        # ... rest of your existing code ...
    
    async def stoploss_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stoploss command - delegate to stoploss handler"""
        logger.info(f"[{self.account_id}] Stoploss command")
        await self.stoploss_handler.show_stoploss_menu(update, context)
    
    async def cancelstops_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel stops command"""
        logger.info(f"[{self.account_id}] Cancel stops command")
        # ... your existing implementation ...
    
    async def debug_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Debug command - shows account info"""
        message = f"""<b>🐛 Debug Info</b>

<b>Account ID:</b> {self.account_id}
<b>Account Name:</b> {self.account_name}
<b>User ID:</b> {update.effective_user.id}
<b>Chat ID:</b> {update.effective_chat.id}"""
        
        from telegram.constants import ParseMode
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    
    # Test commands (optional)
    async def test_ticker_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Test ticker API"""
        # Your existing test ticker implementation
        pass
    
    async def test_format_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Test formatting"""
        # Your existing test format implementation
        pass
    
    # ============= CALLBACK HANDLERS =============
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Main callback handler - routes to appropriate handler"""
        try:
            query = update.callback_query
            data = query.data
            
            logger.info(f"[{self.account_id}] === PROCESSING CALLBACK: {data} ===")
            
            # Portfolio Summary
            if data == "portfolio_summary":
                await self._portfolio_summary_callback(update, context)
            
            # Multi-strike stop-loss callbacks
            elif data == "multi_strike_stoploss":
                await self.multi_stoploss_handler.show_multi_strike_menu(update, context)
            elif data.startswith("ms_"):
                await self._handle_multi_stoploss_callbacks(update, context, data)
            
            # Show positions
            elif data == "show_positions":
                await self._show_positions_callback(update, context)
            
            # Back to main
            elif data == "back_to_main":
                await self._back_to_main_callback(update, context)
            
            # Expiry selection
            elif data == "select_expiry":
                await self.expiry_handler.show_expiry_selection(update, context)
            elif data.startswith("expiry_"):
                await self.expiry_handler.handle_expiry_selection(update, context)
            
            # Strategy selection
            elif data.startswith("strategy_"):
                await self.options_handler.handle_strategy_selection(update, context)
            
            # Stop-loss callbacks
            elif data.startswith("sl_"):
                await self._handle_stoploss_callbacks(update, context, data)
            
            else:
                logger.warning(f"[{self.account_id}] ❌ Unknown callback: {data}")
                await query.answer("Unknown option")
            
            logger.info(f"[{self.account_id}] === COMPLETED CALLBACK: {data} ===")
            
        except Exception as e:
            logger.error(f"[{self.account_id}] ❌ Error in callback_handler: {e}", exc_info=True)
            try:
                await update.callback_query.answer("❌ An error occurred")
            except:
                pass
    
    async def _show_positions_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show positions callback"""
        try:
            query = update.callback_query
            await query.answer()
            
            from utils.helpers import format_enhanced_positions_with_live_data
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            from telegram.constants import ParseMode
            
            positions = self.delta_client.force_enhance_positions()
            
            if not positions.get('success'):
                await query.edit_message_text("❌ Failed to fetch positions.")
                return
            
            positions_data = positions.get('result', [])
            
            if not positions_data:
                message = f"<b>🏦 {self.account_name}</b>\n\n📊 <b>No Open Positions</b>\n\nYou currently have no active positions."
            else:
                header = f"<b>🏦 {self.account_name}</b>\n\n"
                positions_message = format_enhanced_positions_with_live_data(positions_data, self.delta_client)
                message = header + positions_message
            
            keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"[{self.account_id}] Error in show_positions_callback: {e}")
            await query.edit_message_text("❌ Failed to fetch positions.")
    
    async def _portfolio_summary_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Portfolio summary callback"""
        # Your existing portfolio summary implementation
        # Add self.account_name to the header
        pass
    
    async def _back_to_main_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Back to main menu"""
        # Call start_command logic
        query = update.callback_query
        await query.answer()
        
        # Re-create the start menu
        # Similar to start_command but edit existing message
        pass
    
    async def _handle_multi_stoploss_callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
        """Handle multi-strike stop-loss callbacks"""
        if data.startswith("ms_toggle_"):
            await self.multi_stoploss_handler.handle_position_toggle(update, context)
        elif data == "ms_proceed":
            await self.multi_stoploss_handler.handle_proceed_to_prices(update, context)
        elif data == "ms_clear":
            await self.multi_stoploss_handler.handle_clear_selection(update, context)
        elif data == "ms_cancel":
            await self.multi_stoploss_handler.handle_cancel(update, context)
    
    async def _handle_stoploss_callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
        """Handle stop-loss callbacks"""
        # Your existing stop-loss callback handling
        pass
    
    # ============= MESSAGE HANDLER =============
    
    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages (for input collection)"""
        try:
            message_text = update.message.text.strip()
            logger.info(f"[{self.account_id}] Text message: '{message_text}'")
            
            # Check all input states and route to appropriate handler
            if context.user_data.get('waiting_for_multi_trigger_percentage'):
                await self.multi_stoploss_handler.handle_trigger_percentage_input(update, context)
            elif context.user_data.get('waiting_for_multi_limit_percentage'):
                await self.multi_stoploss_handler.handle_limit_percentage_input(update, context)
            elif context.user_data.get('waiting_for_lot_size'):
                await self.options_handler.handle_lot_size_input(update, context)
            elif context.user_data.get('waiting_for_trigger_price'):
                await self.stoploss_handler.handle_trigger_price_input(update, context)
            elif context.user_data.get('waiting_for_limit_percentage'):
                await self.stoploss_handler.handle_limit_percentage_input(update, context)
            elif context.user_data.get('waiting_for_limit_absolute'):
                await self.stoploss_handler.handle_limit_absolute_input(update, context)
            elif context.user_data.get('waiting_for_trail_amount'):
                await self.stoploss_handler.handle_trail_amount_input(update, context)
            else:
                await update.message.reply_text(
                    f"👋 Hi! This is <b>{self.account_name}</b>\n\n"
                    "Available commands:\n"
                    "/start - Main menu\n"
                    "/positions - View positions\n"
                    "/orders - View active orders",
                    parse_mode="HTML"
                )
                
        except Exception as e:
            logger.error(f"[{self.account_id}] Error in message_handler: {e}", exc_info=True)
            await update.message.reply_text("❌ An error occurred. Please try /start")
              
