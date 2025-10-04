import asyncio
import logging
import os
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode
from telegram.error import TimedOut, NetworkError, RetryAfter
from telegram.request import HTTPXRequest
from bot_manager import BotManager
from config.accounts_config import ACCOUNTS, WEBHOOK_URL, WEBHOOK_PORT
import tornado.web
import tornado.ioloop
import tornado.httpserver
import json
import threading
import time

from config.config import TELEGRAM_BOT_TOKEN, HOST, PORT
from api.delta_client import DeltaClient
from api.telegram_client import TelegramClient
from handlers.expiry_handler import ExpiryHandler
from handlers.options_handler import OptionsHandler
from handlers.position_handler import PositionHandler
from utils.constants import START_MESSAGE, HELP_MESSAGE
from utils.helpers import format_enhanced_positions_with_live_data
from utils.helpers import format_enhanced_positions_message
from handlers.stoploss_handler import StopLossHandler
from handlers.multi_stoploss_handler import MultiStrikeStopl0ssHandler

# Initialize logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot_manager = None

# Global application instance
application = None
webhook_monitor_active = False

def start_webhook_monitor():
    """Start webhook health monitor with proper async handling"""
    import threading
    import time
    import requests
    
    def monitor_loop():
        """Monitor loop that runs in separate thread - uses requests instead of async"""
        while True:
            try:
                logger.info("🔍 Checking webhook health...")
                
                # Use synchronous requests instead of async
                response = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo",
                    timeout=10
                )
                
                if response.status_code == 200:
                    webhook_data = response.json()
                    pending_updates = webhook_data.get('result', {}).get('pending_update_count', 0)
                    logger.info(f"✅ Webhook healthy - Pending: {pending_updates}")
                    
                    # Alert if too many pending updates
                    if pending_updates > 10:
                        logger.warning(f"⚠️ High pending updates: {pending_updates}")
                else:
                    logger.error(f"❌ Webhook check failed: HTTP {response.status_code}")
                
                # Wait 5 minutes between checks
                time.sleep(300)
                
            except Exception as e:
                logger.error(f"❌ Webhook monitor error: {e}")
                time.sleep(60)  # Wait 1 minute before retrying on error
    
    # Start monitor in background daemon thread
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True, name="WebhookMonitor")
    monitor_thread.start()
    logger.info("✅ Webhook monitor started")

def webhook_health_monitor():
    """Background thread to monitor webhook health"""
    global webhook_monitor_active, application
    
    webhook_monitor_active = True
    check_interval = 300  # 5 minutes
    
    while webhook_monitor_active:
        try:
            time.sleep(check_interval)
            
            if not webhook_monitor_active or not application:
                break
                
            logger.info("🔍 Checking webhook health...")
            
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Get webhook info
                webhook_info = loop.run_until_complete(application.bot.get_webhook_info())
                
                if not webhook_info.url:
                    logger.warning("⚠️ Webhook not set, attempting to restore...")
                    success = loop.run_until_complete(setup_webhook())
                    if success:
                        logger.info("✅ Webhook restored successfully")
                elif webhook_info.pending_update_count > 100:
                    logger.warning(f"⚠️ High pending updates: {webhook_info.pending_update_count}, resetting...")
                    loop.run_until_complete(setup_webhook())
                else:
                    logger.info(f"✅ Webhook healthy - Pending: {webhook_info.pending_update_count}")
                    
            finally:
                loop.close()
                
        except Exception as e:
            logger.error(f"❌ Webhook monitor error: {e}")
    
    logger.info("🛑 Webhook monitor stopped")

async def setup_webhook():
    """Enhanced webhook setup with 502 error prevention"""
    global application
    
    # Construct webhook URL
    webhook_url = os.getenv('WEBHOOK_URL')
    if not webhook_url:
        app_name = os.getenv('RENDER_SERVICE_NAME')
        external_url = os.getenv('RENDER_EXTERNAL_URL')
        
        if external_url:
            webhook_url = f"{external_url}/{TELEGRAM_BOT_TOKEN}"
        elif app_name:
            webhook_url = f"https://{app_name}.onrender.com/{TELEGRAM_BOT_TOKEN}"
        else:
            logger.error("❌ Cannot determine webhook URL")
            return False
    
    logger.info(f"🔗 Setting webhook to: {webhook_url}")
    
    try:
        # Clear existing webhook and pending updates
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("🧹 Cleared existing webhook and dropped pending updates")
        
        # Wait before setting new webhook
        await asyncio.sleep(5)
        
        # Set new webhook with specific parameters to prevent 502s
        success = await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=['message', 'callback_query'],
            drop_pending_updates=True,
            max_connections=2
        )
        
        if success:
            await asyncio.sleep(2)  # Wait before verification
            webhook_info = await application.bot.get_webhook_info()
            
            if webhook_info.url == webhook_url:
                logger.info("✅ Webhook verified successfully")
                return True
            else:
                logger.error(f"❌ Webhook verification failed")
                return False
        else:
            logger.error("❌ Failed to set webhook")
            return False
            
    except Exception as e:
        logger.error(f"❌ Webhook setup failed: {e}")
        return False

# Initialize clients and handlers
delta_client = DeltaClient()
telegram_client = TelegramClient(TELEGRAM_BOT_TOKEN)
expiry_handler = ExpiryHandler(delta_client)
options_handler = OptionsHandler(delta_client)
position_handler = PositionHandler(delta_client)
stoploss_handler = StopLossHandler(delta_client)
multi_stoploss_handler = MultiStrikeStopl0ssHandler(delta_client)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors in the bot"""
    try:
        logger.error(f"Exception while handling update {update}: {context.error}")
        
        # Import error types
        from telegram.error import TimedOut, NetworkError, RetryAfter
        
        # Handle specific error types
        if isinstance(context.error, TimedOut):
            logger.warning("⚠️ Telegram API timeout - will retry")
            return
        
        elif isinstance(context.error, NetworkError):
            logger.warning("⚠️ Network error - connection issue")
            return
        
        elif isinstance(context.error, RetryAfter):
            retry_after = context.error.retry_after
            logger.warning(f"⚠️ Rate limited - retry after {retry_after}s")
            return
        
        # For other errors, try to notify user
        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "❌ An error occurred. Please try again in a moment."
                )
            except Exception as e:
                logger.error(f"Failed to send error message: {e}")
        
    except Exception as e:
        logger.error(f"Error in error_handler: {e}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced callback handler with proper stop-loss routing"""
    try:
        delta_client = context.bot_data.get('delta_client')
        query = update.callback_query
        data = query.data
        
        logger.info(f"=== PROCESSING CALLBACK: {data} ===")
        
        # Initialize handlers with account-specific delta_client
        expiry_handler = ExpiryHandler(delta_client)
        options_handler = OptionsHandler(delta_client)
        stoploss_handler = StoplossHandler(delta_client)
        multi_stoploss_handler = MultiStrikeStopl0ssHandler(delta_client)
        
        # Portfolio Summary callback
        if data == "portfolio_summary":
            logger.info("🎯 Processing portfolio summary")
            await portfolio_summary_callback(update, context)
            return
        
        # Multi-strike stop-loss callbacks
        elif data == "multi_strike_stoploss":
            logger.info("🎯 Processing multi-strike stop-loss")
            await multi_stoploss_handler.show_multi_strike_menu(update, context)
            return
        
        # Show positions callback
        elif data == "show_positions":
            logger.info("🎯 Processing show positions")
            await show_positions_callback(update, context)
            return
        
        # Back to main menu callback
        elif data == "back_to_main":
            logger.info("🎯 Processing back to main menu")
            await back_to_main_callback(update, context)
            return

        # Test callback first
        if data == "test_simple":
            await query.edit_message_text("✅ Simple callback works!")
            return

        if data == "show_positions":
            logger.info("🎯 Processing show positions")
            await show_positions_callback(update, context)
            return
        
        # Handle stop-loss specific callbacks FIRST
        if data == "sl_limit_percentage":
            logger.info("🎯 Processing percentage limit selection")
            try:
                await stoploss_handler.handle_limit_price_selection(update, context)
                logger.info("✅ Percentage handler completed successfully")
            except Exception as e:
                logger.error(f"❌ Percentage handler failed: {e}", exc_info=True)
                await query.edit_message_text("❌ Error processing percentage selection")
            return

        # Multi-strike stop-loss callbacks
        if data == "multi_strike_stoploss":
            logger.info("🎯 Processing multi-strike stop-loss")
            await multi_stoploss_handler.show_multi_strike_menu(update, context)
            return
        
        elif data.startswith("ms_toggle_"):
            await multi_stoploss_handler.handle_position_toggle(update, context)
            return
        
        elif data == "ms_proceed":
            await multi_stoploss_handler.handle_proceed_to_prices(update, context)
            return
        
        elif data == "ms_clear":
            await multi_stoploss_handler.handle_clear_selection(update, context)
            return
        
        elif data == "ms_cancel":
            await multi_stoploss_handler.handle_cancel(update, context)
            return
        
        # In your callback_handler function, add:
        elif data == "back_to_main":
            logger.info("🎯 Processing back to main menu")
            await back_to_main_callback(update, context)
            return
        
        elif data == "sl_limit_absolute":
            logger.info("🎯 Processing absolute limit selection")
            try:
                await stoploss_handler.handle_limit_price_selection(update, context)
                logger.info("✅ Absolute handler completed successfully")
            except Exception as e:
                logger.error(f"❌ Absolute handler failed: {e}", exc_info=True)
                await query.edit_message_text("❌ Error processing absolute selection")
            return
        
        elif data == "sl_cancel":
            logger.info("🎯 Processing cancel")
            await query.edit_message_text("❌ Stop-loss setup cancelled.")
            return
        
        elif data.startswith("sl_select_pos_"):
            logger.info("🎯 Processing position selection")
            await stoploss_handler.handle_position_selection(update, context)
            return
        
        elif data.startswith("sl_type_"):
            logger.info("🎯 Processing stop-loss type selection")
            await stoploss_handler.handle_stoploss_type_selection(update, context)
            return
        
        elif data.startswith("sl_limit_"):
            logger.info("🎯 Processing generic limit selection")
            await stoploss_handler.handle_limit_price_selection(update, context)
            return
        
        # Regular bot callbacks
        elif data == "select_expiry":
            await expiry_handler.show_expiry_selection(update, context)
        elif data.startswith("expiry_"):
            await expiry_handler.handle_expiry_selection(update, context)
        elif data.startswith("strategy_"):
            await options_handler.handle_strategy_selection(update, context)
        elif data == "show_positions":
            await position_handler.show_positions(update, context)
        elif data.startswith("add_stoploss_"):
            order_id = data.replace("add_stoploss_", "")
            await stoploss_handler.show_stoploss_selection(update, context, order_id)
        else:
            logger.warning(f"❌ Unknown callback: {data}")
            await query.answer("Unknown option")
        
        logger.info(f"=== COMPLETED CALLBACK: {data} ===")
            
    except Exception as e:
        logger.error(f"❌ Critical error in callback_handler: {e}", exc_info=True)
        try:
            await update.callback_query.answer("❌ An error occurred")
        except:
            pass

async def back_to_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle back to main menu"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Get portfolio for balance
        portfolio = delta_client.get_portfolio_summary()
        
        message_parts = []
        
        if portfolio.get('success'):
            balances = portfolio.get('result', [])
            total_balance = sum(float(b.get('available_balance', 0)) for b in balances)
            if total_balance > 0:
                message_parts.append(f"💰 <b>Portfolio Value:</b> ₹{total_balance:,.2f}")
        
        welcome_section = """<b>🚀 Welcome to Delta Options Bot!</b>

<b>Available Actions:</b>
• 📊 View your current positions
• 📈 Start new options trading
• 🛡️ Add stop-loss protection
• 💰 Check portfolio summary

Choose an action below:"""
        
        message_parts.append(welcome_section)
        full_message = "\n\n".join(message_parts)
        
        # Create main menu keyboard
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [InlineKeyboardButton("📅 Select Expiry", callback_data="select_expiry")],
            [InlineKeyboardButton("📊 Show Positions", callback_data="show_positions")],
            [InlineKeyboardButton("🛡️ Add Stop-Loss", callback_data="add_stoploss_menu")],
            [InlineKeyboardButton("💰 Portfolio Summary", callback_data="portfolio_summary")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            full_message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in back_to_main_callback: {e}", exc_info=True)

async def show_positions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle show positions button click - with live market data"""
    try:
        query = update.callback_query
        await query.answer()
        
        logger.info("📊 Fetching positions for show positions callback")
        
        # Get enhanced positions
        positions = delta_client.force_enhance_positions()
        
        if not positions.get('success'):
            error_msg = positions.get('error', 'Unknown error')
            await query.edit_message_text(f"❌ Failed to fetch positions: {error_msg}")
            return
        
        positions_data = positions.get('result', [])
        
        if not positions_data:
            message = "📊 <b>No Open Positions</b>\n\nYou currently have no active positions.\n\nUse 'Select Expiry' to start trading!"
        else:
            # IMPORTANT: Pass delta_client to get live market data
            message = format_enhanced_positions_with_live_data(positions_data, delta_client)
        
        # Add back button
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in show_positions_callback: {e}", exc_info=True)
        await query.edit_message_text("❌ Failed to fetch positions.")

async def portfolio_summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle portfolio summary button click"""
    try:
        query = update.callback_query
        await query.answer()
        
        logger.info("💰 Fetching portfolio summary")
        
        # Get portfolio and positions data
        portfolio = delta_client.get_portfolio_summary()
        positions = delta_client.force_enhance_positions()
        
        message_parts = []
        
        # Portfolio balances section
        if portfolio.get('success'):
            balances = portfolio.get('result', [])
            
            message_parts.append("<b>💰 Portfolio Summary</b>\n")
            
            total_balance = 0
            balance_details = []
            
            for balance in balances:
                asset = balance.get('asset_symbol', 'Unknown')
                available = float(balance.get('available_balance', 0))
                total_balance += available
                
                if available > 0.01:  # Only show assets with meaningful balance
                    if asset == 'USDT':
                        balance_details.append(f"• {asset}: ${available:,.2f}")
                    else:
                        balance_details.append(f"• {asset}: ₹{available:,.2f}")
            
            if balance_details:
                message_parts.append("<b>💵 Balances:</b>")
                message_parts.append("\n".join(balance_details))
                message_parts.append(f"\n<b>📊 Total Value: ₹{total_balance:,.2f}</b>")
            else:
                message_parts.append("💵 <b>No significant balances found</b>")
        
        # Positions summary
        if positions.get('success'):
            positions_data = positions.get('result', [])
            
            if positions_data:
                message_parts.append(f"\n<b>📈 Active Positions: {len(positions_data)}</b>")
                
                total_pnl = 0
                long_positions = 0
                short_positions = 0
                
                for position in positions_data:
                    size = float(position.get('size', 0))
                    pnl = float(position.get('unrealized_pnl', 0))
                    
                    # Get live PnL if available
                    product = position.get('product', {})
                    product_id = product.get('id') or position.get('product_id')
                    
                    if pnl == 0 and product_id:
                        try:
                            live_data = delta_client.get_live_ticker(product_id)
                            if live_data and live_data.get('mark_price'):
                                mark_price = float(live_data.get('mark_price', 0))
                                entry_price = float(position.get('entry_price', 0))
                                
                                if mark_price > 0 and entry_price > 0:
                                    if size > 0:  # Long position
                                        pnl = (mark_price - entry_price) * abs(size)
                                    else:  # Short position
                                        pnl = (entry_price - mark_price) * abs(size)
                        except Exception as e:
                            logger.error(f"Error calculating live PnL: {e}")
                    
                    total_pnl += pnl
                    
                    if size > 0:
                        long_positions += 1
                    elif size < 0:
                        short_positions += 1
                
                pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                message_parts.append(f"• Long: {long_positions} | Short: {short_positions}")
                message_parts.append(f"• Total PnL: {pnl_emoji} ${total_pnl:,.2f}")
            else:
                message_parts.append(f"\n<b>📈 No Active Positions</b>")
        
        # Performance metrics
        message_parts.append(f"\n<b>📊 Quick Stats:</b>")
        
        if portfolio.get('success') and positions.get('success'):
            positions_count = len(positions.get('result', []))
            message_parts.append(f"• Open Trades: {positions_count}")
            message_parts.append(f"• Account Status: {'🟢 Active' if total_balance > 0 else '🔴 Low Balance'}")
        
        # Combine all parts
        full_message = "\n".join(message_parts)
        
        # Add navigation buttons
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [InlineKeyboardButton("📊 View Positions", callback_data="show_positions")],
            [InlineKeyboardButton("🛡️ Add Stop-Loss", callback_data="multi_strike_stoploss")],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            full_message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in portfolio_summary_callback: {e}", exc_info=True)
        await query.edit_message_text("❌ Failed to fetch portfolio summary.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An error occurred. Please try again or use /start to restart."
            )
    except Exception as e:
        logger.error(f"Failed to send error message: {e}")

async def test_ticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test ticker API with your positions"""
    try:
        logger.info(f"Testing ticker API from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Testing ticker API...")
        
        # Get positions first
        positions = delta_client.force_enhance_positions()
        
        if not positions.get('success') or not positions.get('result'):
            await loading_msg.edit_text("❌ No positions found to test ticker API")
            return
        
        position = positions['result'][0]  # Test first position
        product = position.get('product', {})
        product_id = product.get('id')
        symbol = product.get('symbol', 'Unknown')
        
        # Test ticker API
        message = f"<b>🧪 Ticker API Test</b>\n\n"
        message += f"<b>Position:</b> {symbol}\n"
        message += f"<b>Product ID:</b> {product_id}\n\n"
        
        # Test method 1: By product_id
        ticker1 = delta_client.get_live_ticker(product_id)
        if ticker1:
            mark_price1 = ticker1.get('mark_price', 'N/A')
            message += f"<b>✅ Method 1 (product_id):</b>\n"
            message += f"Mark Price: {mark_price1}\n"
            message += f"Close: {ticker1.get('close', 'N/A')}\n\n"
        else:
            message += f"<b>❌ Method 1 (product_id):</b> Failed\n\n"
        
        # Test method 2: By symbol
        ticker2 = delta_client.get_live_ticker_by_symbol(symbol)
        if ticker2:
            mark_price2 = ticker2.get('mark_price', 'N/A')
            message += f"<b>✅ Method 2 (symbol):</b>\n"
            message += f"Mark Price: {mark_price2}\n"
            message += f"Close: {ticker2.get('close', 'N/A')}\n\n"
        else:
            message += f"<b>❌ Method 2 (symbol):</b> Failed\n\n"
        
        # Test method 3: All tickers filtered
        all_tickers = delta_client.get_all_tickers_filtered("call_options,put_options")
        if all_tickers.get('success'):
            tickers_list = all_tickers.get('result', [])
            found_ticker = None
            for ticker in tickers_list:
                if ticker.get('product_id') == product_id:
                    found_ticker = ticker
                    break
            
            if found_ticker:
                mark_price3 = found_ticker.get('mark_price', 'N/A')
                message += f"<b>✅ Method 3 (all tickers filtered):</b>\n"
                message += f"Mark Price: {mark_price3}\n"
                message += f"Close: {found_ticker.get('close', 'N/A')}\n"
            else:
                message += f"<b>❌ Method 3:</b> Product not found in all tickers\n"
        else:
            message += f"<b>❌ Method 3:</b> All tickers failed\n"
        
        await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in test_ticker_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Test failed: {e}")

# Add to initialize_bot function

async def check_handlers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check if handlers are properly initialized"""
    try:
        handlers_status = []
        
        # Check stoploss_handler
        if 'stoploss_handler' in globals():
            handlers_status.append("✅ stoploss_handler exists globally")
            if hasattr(stoploss_handler, 'handle_limit_price_selection'):
                handlers_status.append("✅ handle_limit_price_selection method exists")
            else:
                handlers_status.append("❌ handle_limit_price_selection method missing")
        else:
            handlers_status.append("❌ stoploss_handler not found globally")
        
        # Check other handlers
        handlers_to_check = ['expiry_handler', 'options_handler', 'position_handler']
        for handler_name in handlers_to_check:
            if handler_name in globals():
                handlers_status.append(f"✅ {handler_name} exists")
            else:
                handlers_status.append(f"❌ {handler_name} missing")
        
        message = "<b>🔍 Handlers Status:</b>\n\n" + "\n".join(handlers_status)
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Check failed: {e}")

# Add to initialize_bot function

async def simple_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple callback test"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    keyboard = [[InlineKeyboardButton("Test Button", callback_data="test_simple")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("Simple test:", reply_markup=reply_markup)

async def compare_positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compare position formatting methods"""
    try:
        loading_msg = await update.message.reply_text("🔄 Comparing position formats...")
        
        positions = delta_client.force_enhance_positions()
        positions_data = positions.get('result', [])
        
        if not positions_data:
            await loading_msg.edit_text("❌ No positions to compare")
            return
        
        # Format WITHOUT live data
        message_old = format_enhanced_positions_with_live_data(positions_data, None)
        
        # Format WITH live data  
        message_new = format_enhanced_positions_with_live_data(positions_data, delta_client)
        
        comparison = f"<b>🔍 Position Format Comparison</b>\n\n"
        comparison += f"<b>WITHOUT Live Data:</b>\n{message_old}\n\n"
        comparison += f"<b>WITH Live Data:</b>\n{message_new}"
        
        # Send in parts if too long
        if len(comparison) > 4000:
            await loading_msg.edit_text(f"<b>WITHOUT Live Data:</b>\n{message_old}", parse_mode=ParseMode.HTML)
            await update.message.reply_text(f"<b>WITH Live Data:</b>\n{message_new}", parse_mode=ParseMode.HTML)
        else:
            await loading_msg.edit_text(comparison, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Comparison failed: {e}")

# Add to initialize_bot function

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Optimized start command with proper error handling"""
    try:
        # GET DELTA CLIENT FROM CONTEXT (injected by bot manager)
        delta_client = context.bot_data.get('delta_client')
        account_name = context.bot_data.get('account_name', 'Unknown')
        
        logger.info(f"Start command from user: {update.effective_user.id} (Account: {account_name})")
        
        # Fetch portfolio data with timeout protection
        import asyncio
        
        try:
            # Run portfolio fetch with timeout
            portfolio = await asyncio.wait_for(
                asyncio.to_thread(delta_client.get_portfolio_summary),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.error("Portfolio fetch timed out")
            portfolio = {"success": False}
        except Exception as e:
            logger.error(f"Portfolio fetch error: {e}")
            portfolio = {"success": False}
        # Rest of your existing start_command code, but use delta_client variable
        portfolio = delta_client.get_portfolio_summary()
        
        # Build message
        message_parts = []
        
        # Add portfolio balance
        if portfolio.get('success'):
            balances = portfolio.get('result', [])
            total_balance = sum(float(b.get('available_balance', 0)) for b in balances)
            if total_balance > 0:
                message_parts.append(f"💰 <b>Portfolio Value:</b> ₹{total_balance:,.2f}")
        
        # Add account identifier
        message_parts.append(f"<b>📊 Account:</b> {account_name}")
        
        welcome_section = """<b>🚀 Welcome to Delta Options Bot!</b>

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
        keyboard = [
            [InlineKeyboardButton("📅 Select Expiry", callback_data="select_expiry")],
            [InlineKeyboardButton("📊 Show Positions", callback_data="show_positions")],
            [InlineKeyboardButton("🛡️ Multi-Strike Stop-Loss", callback_data="multi_strike_stoploss")],
            [InlineKeyboardButton("💰 Portfolio Summary", callback_data="portfolio_summary")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send message with timeout protection
        try:
            await asyncio.wait_for(
                update.message.reply_text(
                    full_message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                ),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.error("Failed to send message - timeout")
            # Try sending a simpler message
            try:
                await update.message.reply_text("❌ Response timeout. Please try /start again.")
            except:
                pass
        
    except Exception as e:
        logger.error(f"Error in start_command: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ An error occurred. Please try again.")
        except:
            pass

async def debug_order_details_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show raw order details for debugging"""
    try:
        logger.info(f"Debug order details from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Fetching raw order details...")
        
        # Get all orders
        response = delta_client._make_request('GET', '/orders', {'states': 'open,pending'})
        
        if not response.get('success'):
            await loading_msg.edit_text(f"❌ Failed: {response.get('error')}")
            return
        
        orders = response.get('result', [])
        
        if not orders:
            await loading_msg.edit_text("📋 No orders found")
            return
        
        # Show details of first order
        first_order = orders[0]
        
        message = f"<b>🔍 Raw Order Details</b>\n\n"
        message += f"<b>Order ID:</b> {first_order.get('id')}\n"
        message += f"<b>Product Symbol:</b> {first_order.get('product_symbol')}\n"
        message += f"<b>Order Type:</b> {first_order.get('order_type')}\n"
        message += f"<b>Stop Order Type:</b> {first_order.get('stop_order_type')}\n"
        message += f"<b>Side:</b> {first_order.get('side')}\n"
        message += f"<b>Size:</b> {first_order.get('size')}\n"
        message += f"<b>Stop Price:</b> {first_order.get('stop_price')}\n"
        message += f"<b>Limit Price:</b> {first_order.get('limit_price')}\n"
        message += f"<b>State:</b> {first_order.get('state')}\n"
        message += f"<b>Reduce Only:</b> {first_order.get('reduce_only')}\n"
        
        # Show all keys for reference
        message += f"\n<b>All Keys:</b>\n<code>{', '.join(first_order.keys())}</code>"
        
        await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in debug_order_details_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Debug failed: {e}")

# Add to initialize_bot function

async def check_method_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check if get_stop_orders method exists"""
    try:
        if hasattr(delta_client, 'get_stop_orders'):
            await update.message.reply_text("✅ get_stop_orders method exists")
            
            # Test calling it
            result = delta_client.get_stop_orders()
            await update.message.reply_text(f"📊 Method result: {result}")
        else:
            await update.message.reply_text("❌ get_stop_orders method does NOT exist")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Check failed: {e}")

# Add to initialize_bot function

async def test_simple_orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test simple orders call without parameters"""
    try:
        loading_msg = await update.message.reply_text("🔄 Testing simple orders...")
        
        # Test without any parameters
        response = delta_client._make_request('GET', '/orders')
        
        if response.get('success'):
            orders = response.get('result', [])
            message = f"✅ Simple orders call successful!\n\n"
            message += f"Total orders: {len(orders)}\n"
            
            if orders:
                first_order = orders[0]
                message += f"First order state: {first_order.get('state')}\n"
                message += f"First order type: {first_order.get('order_type')}\n"
        else:
            message = f"❌ Simple orders failed: {response.get('error')}"
        
        await loading_msg.edit_text(message)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Test failed: {e}")

# Add to initialize_bot function

async def test_position_formatting_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test position formatting with live data"""
    try:
        logger.info(f"Testing position formatting from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Testing position formatting...")
        
        # Get positions
        positions = delta_client.force_enhance_positions()
        
        if not positions.get('success') or not positions.get('result'):
            await loading_msg.edit_text("❌ No positions found")
            return
        
        positions_data = positions['result']
        
        # Test formatting WITH delta_client
        message_with_live = format_enhanced_positions_with_live_data(positions_data, delta_client)
        
        # Test formatting WITHOUT delta_client (to see the difference)
        message_without_live = format_enhanced_positions_with_live_data(positions_data, None)
        
        result_message = f"<b>🧪 Position Formatting Test</b>\n\n"
        result_message += f"<b>WITH Live Data:</b>\n{message_with_live}\n\n"
        result_message += f"<b>WITHOUT Live Data:</b>\n{message_without_live}"
        
        # Split message if too long
        if len(result_message) > 4000:
            await loading_msg.edit_text(f"<b>🧪 WITH Live Data:</b>\n{message_with_live}", parse_mode=ParseMode.HTML)
            await update.message.reply_text(f"<b>WITHOUT Live Data:</b>\n{message_without_live}", parse_mode=ParseMode.HTML)
        else:
            await loading_msg.edit_text(result_message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in test_position_formatting_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Test failed: {e}")

# Add to initialize_bot function

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command to check system status"""
    try:
        logger.info(f"Debug command from user: {update.effective_user.id}")
        
        # Test Delta API
        connection_test = delta_client.test_connection()
        api_status = "✅ Connected" if connection_test.get('success') else f"❌ Failed: {connection_test.get('error')}"
        
        # Get webhook info
        webhook_info = await application.bot.get_webhook_info()
        webhook_status = f"✅ Active" if webhook_info.url else "❌ Not set"
        
        # Get BTC price
        btc_price = delta_client.get_btc_spot_price()
        price_status = f"✅ ${btc_price:,.2f}" if btc_price else "❌ Failed to fetch"
        
        debug_message = f"""
<b>🔧 System Status</b>

<b>Delta API:</b> {api_status}
<b>BTC Price:</b> {price_status}
<b>Webhook:</b> {webhook_status}
<b>Pending Updates:</b> {webhook_info.pending_update_count}

<i>Last Error: {webhook_info.last_error_message or 'None'}</i>
        """.strip()
        
        await update.message.reply_text(debug_message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in debug_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Debug command failed.")

async def raw_positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show raw position data for debugging"""
    try:
        logger.info(f"Raw positions debug from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Fetching raw position data...")
        
        # Get raw positions
        positions = delta_client.get_positions()
        
        if not positions.get('success'):
            await loading_msg.edit_text(f"❌ Failed: {positions.get('error')}")
            return
        
        positions_data = positions.get('result', [])
        
        if not positions_data:
            await loading_msg.edit_text("📊 No positions found.")
            return
        
        # Show first position's raw data
        position = positions_data[0]
        product = position.get('product', {})
        
        debug_info = f"""<b>🔍 Raw Position Data</b>

<b>Position Level:</b>
• Size: {position.get('size')}
• Entry Price: {position.get('entry_price')}
• PnL: {position.get('unrealized_pnl')}
• Product ID: {position.get('product_id')}

<b>Product Level:</b>
• Symbol: '{product.get('symbol')}'
• Contract Type: {product.get('contract_type')}
• Strike Price: {product.get('strike_price')}
• Underlying: {product.get('underlying_asset')}
• Product ID: {product.get('id')}

<b>Full Product Keys:</b>
{', '.join(product.keys()) if product else 'No product data'}"""
        
        await loading_msg.edit_text(debug_info, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in raw_positions_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Debug failed.")

async def debug_positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command to check raw position data"""
    try:
        logger.info(f"Debug positions command from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Fetching raw position data...")
        
        # Get raw positions data
        positions = delta_client.get_positions()
        
        if not positions.get('success'):
            await loading_msg.edit_text(f"❌ Failed to fetch positions: {positions.get('error')}")
            return
        
        positions_data = positions.get('result', [])
        
        if not positions_data:
            await loading_msg.edit_text("📊 No positions found in raw data.")
            return
        
        # Format raw data for debugging
        debug_message = "<b>🔍 Raw Position Data Debug</b>\n\n"
        
        for i, position in enumerate(positions_data[:3], 1):  # Show first 3 for debugging
            debug_message += f"<b>Position {i}:</b>\n"
            debug_message += f"Raw Size: {position.get('size', 'N/A')}\n"
            debug_message += f"Entry Price: {position.get('entry_price', 'N/A')}\n"
            debug_message += f"Product ID: {position.get('product_id', 'N/A')}\n"
            
            product = position.get('product', {})
            debug_message += f"Product Symbol: {product.get('symbol', 'N/A')}\n"
            debug_message += f"Contract Type: {product.get('contract_type', 'N/A')}\n"
            debug_message += f"Underlying: {product.get('underlying_asset', 'N/A')}\n"
            debug_message += f"Strike: {product.get('strike_price', 'N/A')}\n"
            debug_message += "\n---\n\n"
        
        await loading_msg.edit_text(debug_message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in debug_positions_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Debug command failed.")

async def webhook_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check and reset webhook if needed"""
    try:
        logger.info(f"Webhook command from user: {update.effective_user.id}")
        
        # Get current webhook info
        webhook_info = await application.bot.get_webhook_info()
        
        message = f"""
<b>🔗 Webhook Status</b>

<b>URL:</b> {webhook_info.url or 'Not set'}
<b>Pending Updates:</b> {webhook_info.pending_update_count}
<b>Max Connections:</b> {webhook_info.max_connections}
<b>Last Error Date:</b> {webhook_info.last_error_date or 'None'}
<b>Last Error:</b> {webhook_info.last_error_message or 'None'}
        """.strip()
        
        # If there are errors, offer to reset
        if webhook_info.last_error_message:
            message += "\n\n⚠️ <b>Webhook has errors!</b>"
            
            # Auto-reset if 502 error detected
            if "502" in webhook_info.last_error_message or "Bad Gateway" in webhook_info.last_error_message:
                message += "\n🔄 <b>Attempting automatic fix...</b>"
                
                success = await setup_webhook()
                if success:
                    message += "\n✅ <b>Webhook reset successfully!</b>"
                else:
                    message += "\n❌ <b>Webhook reset failed.</b>"
        
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in webhook_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to check webhook status.")

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show positions with live market data - enhanced version"""
    try:
        delta_client = context.bot_data.get('delta_client')
        account_name = context.bot_data.get('account_name', 'Unknown')
        
        logger.info(f"Positions command from user: {update.effective_user.id} (Account: {account_name})")
        
        loading_msg = await update.message.reply_text("🔄 Fetching positions...")
        
        # Get enhanced positions
        positions = delta_client.force_enhance_positions()
        portfolio = delta_client.get_portfolio_summary()
        
        if not positions.get('success'):
            error_msg = positions.get('error', 'Unknown error')
            await loading_msg.edit_text(f"❌ Failed to fetch positions: {error_msg}")
            return
        
        positions_data = positions.get('result', [])
        
        # Build message with live market data
        message_parts = []
        
        if positions_data:
            # Use the SAME function as "Show Positions" button - with live data
            positions_message = format_enhanced_positions_with_live_data(positions_data, delta_client)
            message_parts.append(positions_message)
        else:
            message_parts.append("📊 <b>No Open Positions</b>\n\nYou currently have no active positions.")
        
        # Add portfolio balance
        if portfolio.get('success'):
            balances = portfolio.get('result', [])
            total_balance = sum(float(b.get('available_balance', 0)) for b in balances)
            if total_balance > 0:
                message_parts.append(f"💰 <b>Total Portfolio Value:</b> ₹{total_balance:,.2f}")
        
        # Add account name
        message_parts.append(f"<b>📊 Account:</b> {account_name}")
        
        # Combine all parts
        full_message = "\n\n".join(message_parts)
        
        await loading_msg.edit_text(full_message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in positions_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to fetch positions.")

async def stoploss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced /stoploss command with position selection"""
    try:
        delta_client = context.bot_data.get('delta_client')
        account_name = context.bot_data.get('account_name', 'Unknown')
        
        logger.info(f"Stop-loss command from user: {update.effective_user.id}")
        
        # Check if order ID is provided
        if context.args:
            order_id = context.args[0]
            await stoploss_handler.show_stoploss_selection(update, context, order_id)
        else:
            # No order ID - show position selection interface
            await stoploss_handler.show_stoploss_selection(update, context)
            
    except Exception as e:
        logger.error(f"Error in stoploss_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to process stop-loss command.")

async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show portfolio summary"""
    try:
        delta_client = context.bot_data.get('delta_client')
        account_name = context.bot_data.get('account_name', 'Unknown')
        
        logger.info(f"Portfolio command from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Fetching portfolio data...")
        
        portfolio = delta_client.get_portfolio_summary()
        
        if not portfolio.get('success'):
            error_msg = portfolio.get('error', 'Unknown error')
            await loading_msg.edit_text(f"❌ Failed to fetch portfolio: {error_msg}")
            return
        
        balances = portfolio.get('result', [])
        
        if not balances:
            await loading_msg.edit_text("📊 No balance data available.")
            return
        
        message = "<b>💰 Portfolio Summary</b>\n\n"
        
        total_value = 0
        for balance in balances:
            asset = balance.get('asset_symbol', 'Unknown')
            available = float(balance.get('available_balance', 0))
            reserved = float(balance.get('order_margin', 0))
            
            if available > 0 or reserved > 0:
                message += f"<b>{asset}:</b>\n"
                message += f"  Available: {available:,.4f}\n"
                if reserved > 0:
                    message += f"  Reserved: {reserved:,.4f}\n"
                message += "\n"
                
                if asset == 'INR':
                    total_value += available + reserved
        
        if total_value > 0:
            message += f"<b>Total INR Value:</b> ₹{total_value:,.2f}"
        
        await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in portfolio_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to fetch portfolio data.")

async def debug_products_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug: Show available products"""
    try:
        await update.message.reply_text("🔄 Fetching products...")
        
        # Get all products
        products = delta_client.get_products('call_options,put_options,futures')
        
        if not products.get('success'):
            await update.message.reply_text(f"❌ Failed to get products: {products.get('error')}")
            return
        
        products_list = products.get('result', [])
        
        message = f"<b>📦 Available Products ({len(products_list)})</b>\n\n"
        
        # Show first 5 products
        for i, product in enumerate(products_list[:5], 1):
            symbol = product.get('symbol', 'Unknown')
            product_id = product.get('id', 'No ID')
            contract_type = product.get('contract_type', 'Unknown')
            
            message += f"{i}. <b>{symbol}</b>\n"
            message += f"   ID: {product_id}\n"
            message += f"   Type: {contract_type}\n\n"
        
        if len(products_list) > 5:
            message += f"<i>... and {len(products_list) - 5} more products</i>"
        
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Debug failed: {e}")

async def debug_raw_positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug: Show raw position API response with required parameters"""
    try:
        await update.message.reply_text("🔄 Fetching raw positions with BTC filter...")
        
        # Direct API call with required parameter
        positions = delta_client._make_request('GET', '/positions', {'underlying_asset_symbol': 'BTC'})
        
        if not positions.get('success'):
            await update.message.reply_text(f"❌ BTC positions failed: {positions.get('error')}")
            return
        
        positions_list = positions.get('result', [])
        
        if not positions_list:
            await update.message.reply_text("📊 No BTC positions found")
            return
        
        # Show raw data for first position
        pos = positions_list[0]
        
        message = f"<b>🔍 Raw BTC Position Data</b>\n\n"
        message += f"<b>Position Keys:</b>\n{', '.join(pos.keys())}\n\n"
        message += f"<b>Size:</b> {pos.get('size')}\n"
        message += f"<b>Product ID:</b> {pos.get('product_id')}\n"
        message += f"<b>Entry Price:</b> {pos.get('entry_price')}\n\n"
        
        product = pos.get('product', {})
        if product:
            message += f"<b>Product Keys:</b>\n{', '.join(product.keys())}\n\n"
            message += f"<b>Product Symbol:</b> '{product.get('symbol')}'\n"
            message += f"<b>Product ID:</b> {product.get('id')}\n"
            message += f"<b>Contract Type:</b> {product.get('contract_type')}\n"
        else:
            message += f"<b>Product:</b> No product data in response\n"
        
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Debug failed: {e}")

async def debug_stop_order_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug stop order placement with detailed logging"""
    try:
        logger.info(f"Debug stop order from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Testing stop order placement...")
        
        # Get your current position first
        positions = delta_client.force_enhance_positions()
        
        if not positions.get('success') or not positions.get('result'):
            await loading_msg.edit_text("❌ No positions found for testing")
            return
        
        position = positions['result'][0]  # First position
        product_id = position.get('product', {}).get('id') or position.get('product_id')
        size = abs(int(position.get('size', 0)))
        current_side = 'buy' if float(position.get('size', 0)) > 0 else 'sell'
        exit_side = 'sell' if current_side == 'buy' else 'buy'
        
        if not product_id:
            await loading_msg.edit_text("❌ Product ID not found in position data")
            return
        
        debug_info = f"""<b>🔍 Stop Order Debug Test</b>

<b>Position Data:</b>
• Product ID: {product_id}
• Current Size: {position.get('size')}
• Current Side: {current_side}
• Exit Side: {exit_side}
• Entry Price: ${position.get('entry_price')}

<b>Test Order Parameters:</b>
• Product ID: {product_id}
• Size: {size}
• Side: {exit_side}
• Stop Price: $10.00
• Limit Price: $11.00
• Reduce Only: True

<b>Testing API call...</b>"""
        
        await loading_msg.edit_text(debug_info, parse_mode=ParseMode.HTML)
        
        # Test the actual API call
        result = delta_client.place_stop_order(
            product_id=product_id,
            size=size,
            side=exit_side,
            stop_price="10.00",
            limit_price="11.00",
            order_type="limit_order",
            reduce_only=True
        )
        
        # Show detailed result
        debug_result = f"""<b>🔍 API Response Debug</b>

<b>Success:</b> {result.get('success')}

<b>Raw Response:</b>
<code>{json.dumps(result, indent=2)}</code>

<b>Analysis:</b>"""
        
        if result.get('success'):
            order_id = result.get('result', {}).get('id', 'Missing')
            debug_result += f"\n✅ Order placed successfully\n• Order ID: {order_id}"
        else:
            error = result.get('error', 'No error info')
            debug_result += f"\n❌ Order failed\n• Error: {error}"
        
        await loading_msg.edit_text(debug_result, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in debug_stop_order_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Debug failed: {e}")

# Add to initialize_bot function

async def debug_matching_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug: Test the product matching process with fixed API calls"""
    try:
        await update.message.reply_text("🔄 Testing product matching...")
        
        # Get products and positions with proper parameters
        products_response = delta_client.get_products('call_options,put_options,futures')
        positions_response = delta_client._make_request('GET', '/positions', {'underlying_asset_symbol': 'BTC'})
        
        if not products_response.get('success'):
            await update.message.reply_text(f"❌ Products failed: {products_response.get('error')}")
            return
            
        if not positions_response.get('success'):
            await update.message.reply_text(f"❌ BTC positions failed: {positions_response.get('error')}")
            return
        
        products_list = products_response.get('result', [])
        positions_list = positions_response.get('result', [])
        
        # Filter non-zero positions
        active_positions = [p for p in positions_list if float(p.get('size', 0)) != 0]
        
        message = f"<b>🔍 Matching Debug</b>\n\n"
        message += f"Products found: {len(products_list)}\n"
        message += f"Total BTC positions: {len(positions_list)}\n"
        message += f"Active positions: {len(active_positions)}\n\n"
        
        if active_positions:
            pos = active_positions[0]
            pos_product_id = pos.get('product_id') or pos.get('product', {}).get('id')
            
            message += f"<b>Position Product ID:</b> {pos_product_id}\n\n"
            
            # Look for matching product
            matching_product = None
            for product in products_list:
                if product.get('id') == pos_product_id:
                    matching_product = product
                    break
            
            if matching_product:
                message += f"<b>✅ Match Found!</b>\n"
                message += f"Symbol: {matching_product.get('symbol')}\n"
                message += f"Contract Type: {matching_product.get('contract_type')}\n"
                message += f"Strike: {matching_product.get('strike_price')}\n"
            else:
                message += f"<b>❌ No Match Found</b>\n"
                message += f"Looking for product ID: {pos_product_id}\n"
                
                # Show some example product IDs for comparison
                example_ids = [p.get('id') for p in products_list if 'C-BTC-112' in p.get('symbol', '')][:3]
                message += f"Similar product IDs: {example_ids}\n"
        
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Matching debug failed: {e}")

async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show active orders - fixed version"""
    try:
        delta_client = context.bot_data.get('delta_client')
        account_name = context.bot_data.get('account_name', 'Unknown')
        
        logger.info(f"Orders command from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Fetching active orders...")
        
        # Use the fixed get_stop_orders method
        stop_orders = delta_client.get_stop_orders()
        
        if not stop_orders.get('success'):
            error = stop_orders.get('error', 'Unknown error')
            logger.error(f"❌ Orders failed: {error}")
            await loading_msg.edit_text(f"❌ Failed to fetch orders: {error}")
            return
        
        orders_data = stop_orders.get('result', [])
        logger.info(f"📊 Processing {len(orders_data)} orders")
        
        if not orders_data:
            await loading_msg.edit_text("📋 No active stop orders found.\n\nYou currently have no pending stop-loss orders.")
            return
        
        message = "<b>📋 Active Stop Orders</b>\n\n"
        
        for i, order in enumerate(orders_data[:10], 1):
            try:
                # Extract order details
                order_id = order.get('id', 'N/A')
                product_symbol = order.get('product_symbol', 'Unknown')
                side = order.get('side', 'Unknown')
                size = order.get('size', 0)
                stop_price = order.get('stop_price', 'N/A')
                limit_price = order.get('limit_price')
                status = order.get('state', 'Unknown')
                order_type = order.get('order_type', 'Unknown')
                stop_order_type = order.get('stop_order_type', 'N/A')
                
                message += f"<b>{i}. {product_symbol}</b>\n"
                message += f"   ID: <code>{order_id}</code>\n"
                message += f"   Type: {order_type.title()}\n"
                message += f"   Side: {side.title()}\n"
                message += f"   Size: {size} contracts\n"
                
                if stop_price and stop_price != 'N/A':
                    message += f"   Stop Price: ${stop_price}\n"
                
                if limit_price:
                    message += f"   Limit Price: ${limit_price}\n"
                
                message += f"   Status: {status.title()}\n\n"
                
            except Exception as e:
                logger.error(f"❌ Error processing order {i}: {e}")
                message += f"<b>{i}. Processing Error</b>\n   ID: {order.get('id', 'N/A')}\n\n"
        
        await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in orders_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to fetch orders.")

async def cancel_stops_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel all stop orders"""
    try:
        logger.info(f"Cancel stops command from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Cancelling all stop orders...")
        
        result = delta_client.cancel_all_stop_orders()
        
        if result.get('success'):
            cancelled_count = len(result.get('result', []))
            message = f"✅ Successfully cancelled {cancelled_count} stop orders."
        else:
            error_msg = result.get('error', 'Unknown error')
            message = f"❌ Failed to cancel orders: {error_msg}"
        
        await loading_msg.edit_text(message)
        
    except Exception as e:
        logger.error(f"Error in cancel_stops_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to cancel stop orders.")

# Add these to initialize_bot function

async def test_force_enhance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test the complete force enhance process"""
    try:
        await update.message.reply_text("🔄 Testing complete force enhancement...")
        
        result = delta_client.force_enhance_positions()
        
        if result.get('success'):
            positions = result.get('result', [])
            
            if positions:
                pos = positions[0]
                product = pos.get('product', {})
                symbol = product.get('symbol', 'Unknown')
                size = pos.get('size')
                
                message = f"<b>✅ Force Enhancement Success!</b>\n\n"
                message += f"<b>Enhanced Symbol:</b> {symbol}\n"
                message += f"<b>Size:</b> {size}\n"
                message += f"<b>Product ID:</b> {product.get('id')}\n"
                message += f"<b>Contract Type:</b> {product.get('contract_type')}\n"
                message += f"<b>Strike:</b> {product.get('strike_price')}\n"
                
                await update.message.reply_text(message, parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text("✅ Enhancement worked but no positions found")
        else:
            await update.message.reply_text(f"❌ Enhancement failed: {result.get('error')}")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Test failed: {e}")    

async def test_correct_stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test stop order with correct Delta Exchange API"""
    try:
        logger.info(f"Testing correct stop API from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Testing correct stop order API...")
        
        # Get position
        positions = delta_client.force_enhance_positions()
        
        if not positions.get('success') or not positions.get('result'):
            await loading_msg.edit_text("❌ No positions found")
            return
        
        position = positions['result'][0]
        product_id = position.get('product', {}).get('id') or position.get('product_id')
        size = abs(int(position.get('size', 0)))
        current_side = 'buy' if float(position.get('size', 0)) > 0 else 'sell'
        exit_side = 'sell' if current_side == 'buy' else 'buy'
        
        # Test the corrected API call
        result = delta_client.place_stop_order(
            product_id=product_id,
            size=size,
            side=exit_side,
            stop_price="10.00",
            limit_price="11.00", 
            order_type="limit_order",
            reduce_only=True
        )
        
        debug_result = f"""<b>🔍 Corrected API Test Result</b>

<b>Using:</b> POST /orders (not /orders/stop)
<b>Stop Order Type:</b> stop_loss_order

<b>Success:</b> {result.get('success')}

<b>Response:</b>
<code>{json.dumps(result, indent=2)}</code>"""
        
        if result.get('success'):
            order_id = result.get('result', {}).get('id', 'Missing')
            debug_result += f"\n\n✅ <b>Order placed!</b>\nOrder ID: <code>{order_id}</code>"
        
        await loading_msg.edit_text(debug_result, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in test_correct_stop_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Test failed: {e}")

# Add to initialize_bot function

async def test_orders_api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test orders API directly"""
    try:
        logger.info(f"Testing orders API from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Testing orders API...")
        
        # Test 1: Basic orders call
        logger.info("🧪 Test 1: Basic /orders call")
        test1 = delta_client._make_request('GET', '/orders', {})
        logger.info(f"Test 1 result: {test1}")
        
        # Test 2: Orders with state filter
        logger.info("🧪 Test 2: Orders with state filter")
        test2 = delta_client._make_request('GET', '/orders', {'states': 'open'})
        logger.info(f"Test 2 result: {test2}")
        
        # Test 3: Orders with BTC filter
        logger.info("🧪 Test 3: Orders with underlying filter")
        test3 = delta_client._make_request('GET', '/orders', {'underlying_asset_symbol': 'BTC'})
        logger.info(f"Test 3 result: {test3}")
        
        # Format results
        results = []
        for i, (name, result) in enumerate([
            ("Basic /orders", test1),
            ("With state filter", test2), 
            ("With BTC filter", test3)
        ], 1):
            if result.get('success'):
                count = len(result.get('result', []))
                results.append(f"✅ Test {i} ({name}): {count} orders")
            else:
                error = result.get('error', 'Unknown')
                results.append(f"❌ Test {i} ({name}): {error}")
        
        message = f"<b>🧪 Orders API Test Results</b>\n\n" + "\n".join(results)
        
        # Show first order structure if any test succeeded
        for test_name, result in [("Basic", test1), ("State", test2), ("BTC", test3)]:
            if result.get('success') and result.get('result'):
                first_order = result['result'][0]
                message += f"\n\n<b>Sample Order Structure ({test_name}):</b>\n"
                message += f"<code>{list(first_order.keys())}</code>"
                break
        
        await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in test_orders_api_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Test failed: {e}")

# Add to initialize_bot function

async def test_callback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test callback handling directly"""
    try:
        # Set up test context
        context.user_data['trigger_price'] = 15.0
        context.user_data['parent_order'] = {
            'side': 'sell',
            'symbol': 'BTC 112000 CE'
        }
        
        # Create test keyboard
        keyboard = [
            [InlineKeyboardButton("📊 Test Percentage", callback_data="sl_limit_percentage")],
            [InlineKeyboardButton("💰 Test Absolute", callback_data="sl_limit_absolute")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "<b>🧪 Callback Test</b>\n\nTrigger: $15.00\nTry the buttons below:",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Test failed: {e}")

# Add to initialize_bot function

async def check_permissions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check API key permissions"""
    try:
        logger.info(f"Check permissions from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Checking API permissions...")
        
        # Test different API endpoints to check permissions
        tests = [
            ("Read Data", delta_client.get_positions_by_underlying, 'BTC'),
            ("Read Products", delta_client.get_products, None),
            ("Read Orders", delta_client.get_stop_orders, None)
        ]
        
        results = []
        
        for test_name, method, param in tests:
            try:
                if param:
                    result = method(param)
                else:
                    result = method()
                
                if result.get('success'):
                    results.append(f"✅ {test_name}: Working")
                else:
                    error = result.get('error', 'Unknown')
                    results.append(f"❌ {test_name}: {error}")
            except Exception as e:
                results.append(f"❌ {test_name}: Exception - {e}")
        
        # Test a simple order placement (with invalid data to avoid actual execution)
        try:
            test_order = delta_client._make_request('POST', '/orders/stop', 
                payload=json.dumps({"product_id": 999999, "size": 1, "side": "buy", "stop_price": "1"}))
            
            if 'permission' in str(test_order.get('error', '')).lower():
                results.append("❌ Trading Permission: Not granted")
            elif 'invalid' in str(test_order.get('error', '')).lower() or 'not found' in str(test_order.get('error', '')).lower():
                results.append("✅ Trading Permission: Granted (invalid test data rejected as expected)")
            else:
                results.append(f"⚠️ Trading Permission: Unknown - {test_order.get('error', 'No error')}")
        except Exception as e:
            results.append(f"❌ Trading Permission: Exception - {e}")
        
        message = f"""<b>🔐 API Key Permissions Check</b>

{chr(10).join(results)}

<b>Required Permissions for Stop Orders:</b>
• ✅ Read Data - View positions & products
• ✅ Trading - Place & cancel orders

<b>Note:</b> If Trading permission is missing, enable it in your Delta Exchange API settings.
"""
        
        await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in check_permissions_command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Permission check failed: {e}")

# Add to initialize_bot function

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced message handler with multi-strike inputs"""
    try:
        delta_client = context.bot_data.get('delta_client')
        message_text = update.message.text.strip()
        
        logger.info(f"Text message: '{message_text}'")

        # Initialize handlers
        stoploss_handler = StoplossHandler(delta_client)
        multi_stoploss_handler = MultiStrikeStopl0ssHandler(delta_client)
        options_handler = OptionsHandler(delta_client)
        
        # Check all input states
        if context.user_data.get('waiting_for_multi_trigger_percentage'):
            logger.info("🎯 Routing to multi-strike trigger percentage handler")
            await multi_stoploss_handler.handle_trigger_percentage_input(update, context)
        elif context.user_data.get('waiting_for_multi_limit_percentage'):
            logger.info("🎯 Routing to multi-strike limit percentage handler")
            await multi_stoploss_handler.handle_limit_percentage_input(update, context)
        elif context.user_data.get('waiting_for_lot_size'):
            logger.info("🎯 Routing to lot size handler")
            await options_handler.handle_lot_size_input(update, context)
        elif context.user_data.get('waiting_for_trigger_price'):
            logger.info("🎯 Routing to trigger price handler")
            await stoploss_handler.handle_trigger_price_input(update, context)
        elif context.user_data.get('waiting_for_limit_percentage'):
            logger.info("🎯 Routing to limit percentage handler")
            await stoploss_handler.handle_limit_percentage_input(update, context)
        elif context.user_data.get('waiting_for_limit_absolute'):
            logger.info("🎯 Routing to limit absolute handler")
            await stoploss_handler.handle_limit_absolute_input(update, context)
        elif context.user_data.get('waiting_for_trail_amount'):
            logger.info("🎯 Routing to trail amount handler")
            await stoploss_handler.handle_trail_amount_input(update, context)
        else:
            logger.info("ℹ️ No waiting state - showing help menu")
            await update.message.reply_text(
                "👋 Hi! Available commands:\n"
                "/start - Main menu\n"
                "/positions - View positions\n"
                "/orders - View active orders"
            )
            
    except Exception as e:
        logger.error(f"Error in message_handler: {e}", exc_info=True)
        await update.message.reply_text("❌ An error occurred. Please try /start")

# ============= TORNADO HANDLERS =============

class RootHandler(tornado.web.RequestHandler):
    """Enhanced root handler for UptimeRobot"""
    def get(self):
        try:
            user_agent = self.request.headers.get('User-Agent', 'Unknown')
            remote_ip = self.request.remote_ip
            logger.info(f"Root request from {remote_ip} - User-Agent: {user_agent}")
            
            self.set_status(200)
            self.set_header("Content-Type", "text/html; charset=utf-8")
            
            html_response = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>BTC Options Trading Bot</title>
                <meta charset="utf-8">
            </head>
            <body>
                <h1>✅ BTC Options Trading Bot</h1>
                <p><strong>Status:</strong> Running</p>
                <p><strong>Version:</strong> 2.0</p>
                <p><strong>Service:</strong> Telegram Bot for Delta Exchange Options Trading</p>
                <p><strong>Uptime:</strong> Service is healthy and responding</p>
                <hr>
                <p><small>This endpoint is monitored for service availability.</small></p>
            </body>
            </html>
            """
            
            self.write(html_response)
            
        except Exception as e:
            logger.error(f"Root handler error: {e}")
            self.set_status(500)
            self.write("<h1>Service Error</h1>")

class UptimeHandler(tornado.web.RequestHandler):
    """Dedicated handler for uptime monitoring"""
    def get(self):
        try:
            logger.info(f"Uptime check from {self.request.remote_ip}")
            self.set_status(200)
            self.set_header("Content-Type", "text/plain")
            self.write("OK - Service is running")
        except Exception as e:
            logger.error(f"Uptime handler error: {e}")
            self.set_status(500)
            self.write("ERROR")

    def head(self):
        """Handle HEAD requests"""
        try:
            self.set_status(200)
            self.set_header("Content-Type", "text/plain")
        except Exception as e:
            logger.error(f"Uptime HEAD handler error: {e}")
            self.set_status(500)

class WebhookHandler(tornado.web.RequestHandler):
    """Enhanced webhook handler to prevent 502 errors"""
    async def post(self):
        try:
            # Set response immediately to prevent timeouts
            self.set_status(200)
            self.set_header("Content-Type", "text/plain")
            
            body = self.request.body.decode('utf-8')
            logger.info(f"📨 Webhook: {len(body)} bytes from {self.request.remote_ip}")
            
            if not body:
                logger.warning("Empty webhook body received")
                self.write("OK")
                return
            
            try:
                update_data = json.loads(body)
            except json.JSONDecodeError as e:
                logger.error(f"❌ Invalid JSON: {e}")
                self.write("OK")
                return
            
            # Respond immediately before processing
            self.write("OK")
            self.finish()  # Send response to Telegram immediately
            
            # Process update asynchronously after responding
            try:
                update = Update.de_json(update_data, application.bot)
                
                # Process with shorter timeout
                await asyncio.wait_for(
                    application.process_update(update),
                    timeout=15.0  # Reduced timeout
                )
                logger.info("✅ Update processed successfully")
                
            except asyncio.TimeoutError:
                logger.error("❌ Update processing timeout - but webhook already responded")
            except Exception as process_error:
                logger.error(f"❌ Update processing error: {process_error}")
            
        except Exception as e:
            logger.error(f"❌ Webhook handler error: {e}", exc_info=True)
            try:
                if not self.finished:
                    self.set_status(200)
                    self.write("OK")
            except:
                pass

    async def get(self):
        """Handle GET requests for testing"""
        self.set_status(200)
        self.write("Webhook endpoint is active")

class HealthHandler(tornado.web.RequestHandler):
    """Enhanced health check endpoint"""
    def get(self):
        try:
            health_status = {
                "status": "healthy",
                "service": "btc-options-bot",
                "version": "2.0",
                "timestamp": int(time.time())
            }
            
            try:
                if application and application.bot:
                    health_status["bot_status"] = "connected"
                else:
                    health_status["bot_status"] = "disconnected"
                    health_status["status"] = "degraded"
            except:
                health_status["bot_status"] = "error"
                health_status["status"] = "degraded"
            
            if health_status["status"] == "healthy":
                self.set_status(200)
            else:
                self.set_status(503)
                
            self.set_header("Content-Type", "application/json")
            self.write(health_status)
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self.set_status(503)
            self.set_header("Content-Type", "application/json")
            self.write({
                "status": "unhealthy", 
                "error": str(e),
                "timestamp": int(time.time())
            })

# ============= APPLICATION SETUP =============

def make_app():
    """Create Tornado application"""
    return tornado.web.Application([
        (r"/", RootHandler),
        (r"/uptime", UptimeHandler),
        (r"/status", UptimeHandler),
        (r"/ping", UptimeHandler),
        (rf"/{TELEGRAM_BOT_TOKEN}", WebhookHandler),
        (r"/health", HealthHandler),
    ])

async def initialize_bot():
    """Initialize the bot application"""
    global application
    
    try:
        logger.info("🚀 Initializing bot application...")
        # Configure custom request with larger pool
        request = HTTPXRequest(
            connection_pool_size=20,  # Increase from default 1
            pool_timeout=30.0,        # Increase timeout to 30 seconds
            read_timeout=30.0,        # Read timeout
            write_timeout=30.0,       # Write timeout
            connect_timeout=30.0      # Connection timeout
        )
        
        # Create application with custom request configuration
        application = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .request(request)
            .concurrent_updates(True)  # Enable concurrent update processing
            .build()
        )
        
        # Add all handlers
        application.add_handler(CommandHandler("checkhandlers", check_handlers_command))
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("debug", debug_command))
        application.add_handler(CommandHandler("debugpos", debug_positions_command))
        application.add_handler(CommandHandler("webhook", webhook_command))
        application.add_handler(CommandHandler("positions", positions_command))
        application.add_handler(CommandHandler("portfolio", portfolio_command))
        application.add_handler(CommandHandler("rawpos", raw_positions_command))
        application.add_handler(CommandHandler("stoploss", stoploss_command))
        application.add_handler(CommandHandler("orders", orders_command))
        application.add_handler(CommandHandler("cancelstops", cancel_stops_command))
        application.add_handler(CommandHandler("testforce", test_force_enhance_command))
        application.add_handler(CommandHandler("debugproducts", debug_products_command))
        application.add_handler(CommandHandler("debugrawpos", debug_raw_positions_command))
        application.add_handler(CommandHandler("debugstop", debug_stop_order_command))
        application.add_handler(CommandHandler("testsimple", test_simple_orders_command))
        application.add_handler(CommandHandler("testorders", test_orders_api_command))
        application.add_handler(CommandHandler("testformat", test_position_formatting_command))
        application.add_handler(CommandHandler("testticker", test_ticker_command))
        application.add_handler(CommandHandler("checkmethod", check_method_command))
        application.add_handler(CommandHandler("debugorder", debug_order_details_command))
        application.add_handler(CommandHandler("comparepos", compare_positions_command))
        application.add_handler(CommandHandler("checkperms", check_permissions_command))
        application.add_handler(CommandHandler("testcorrect", test_correct_stop_command))
        application.add_handler(CommandHandler("simpletest", simple_test_command))
        application.add_handler(CommandHandler("testcb", test_callback_command))
        application.add_handler(CommandHandler("debugmatch", debug_matching_command))
        application.add_handler(CallbackQueryHandler(callback_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        application.add_error_handler(error_handler)
        
        logger.info("✅ All handlers registered")
        
        await application.initialize()
        await application.start()
        
        logger.info("✅ Bot initialized successfully with enhanced connection pool")
        return application
        
        webhook_success = await setup_webhook()
        if webhook_success:
            logger.info("✅ Webhook configured successfully")
        else:
            logger.warning("⚠️ Webhook setup failed, but continuing...")
        
        me = await application.bot.get_me()
        logger.info(f"✅ Bot ready: @{me.username} ({me.first_name})")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Bot initialization failed: {e}")
        return False

def main():
    """Main function with corrected HTTPServer parameters"""
    global webhook_monitor_active
    
    logger.info("🤖 Starting BTC Options Trading Bot v2.0")
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        initialization_success = loop.run_until_complete(initialize_bot())
        
        if not initialization_success:
            logger.error("❌ Failed to initialize bot")
            return
        
        monitor_thread = threading.Thread(target=webhook_health_monitor, daemon=True)
        monitor_thread.start()
        logger.info("✅ Webhook monitor started")
        
        # Create server with only supported parameters
        app = make_app()
        http_server = tornado.httpserver.HTTPServer(app)
        http_server.listen(PORT, HOST)
        
        logger.info(f"🌐 Server listening on {HOST}:{PORT}")
        logger.info("✅ Bot ready! Available endpoints:")
        logger.info("  • / (main page)")
        logger.info("  • /uptime (UptimeRobot endpoint)")  
        logger.info("  • /health (health check)")
        logger.info("  • /webhook (webhook status)")
        
        tornado.ioloop.IOLoop.current().start()
        
    except KeyboardInterrupt:
        logger.info("🛑 Received shutdown signal")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        webhook_monitor_active = False
        
        if application:
            try:
                current_loop = asyncio.get_event_loop()
                if not current_loop.is_closed():
                    try:
                        current_loop.run_until_complete(application.stop())
                        logger.info("✅ Application stopped")
                    except RuntimeError as e:
                        if "not running" in str(e):
                            logger.info("ℹ️ Application was already stopped")
                        else:
                            logger.error(f"Stop error: {e}")
                            
                    try:
                        current_loop.run_until_complete(application.shutdown())
                        logger.info("✅ Application shutdown complete")
                    except Exception as e:
                        logger.error(f"Shutdown error: {e}")
                        
            except Exception as e:
                logger.error(f"❌ Cleanup error: {e}")

if __name__ == '__main__':
    main()
