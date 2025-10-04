# main.py
"""
Multi-Account Delta Options Bot
"""

import asyncio
import logging
import os
import sys

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Import Telegram components
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.request import HTTPXRequest
from telegram.error import TimedOut, NetworkError, RetryAfter

# Import Delta client
from api.delta_client import DeltaClient

# Try to import multi-account config
try:
    from config.accounts_config import get_enabled_accounts, WEBHOOK_ENABLED, WEBHOOK_BASE_URL, SERVER_HOST, SERVER_PORT
    MULTI_ACCOUNT_MODE = True
    logger.info("✅ Multi-account configuration found")
except ImportError:
    MULTI_ACCOUNT_MODE = False
    logger.info("ℹ️ Running in single-account mode")
    
    WEBHOOK_ENABLED = os.getenv('WEBHOOK_ENABLED', 'true').lower() == 'true'
    WEBHOOK_BASE_URL = os.getenv('WEBHOOK_URL', '')
    SERVER_HOST = os.getenv('HOST', '0.0.0.0')
    SERVER_PORT = int(os.getenv('PORT', 10000))

# Global variables
bot_applications = {}
delta_clients = {}

# Import ALL your handler functions directly
# This will work regardless of your file structure
try:
    import main as handlers_module
    logger.info("✅ Loaded handlers from main module")
except:
    handlers_module = None
    logger.warning("⚠️ Could not load handlers module")

# ==================== HANDLER FUNCTIONS (ADD THESE) ====================

# Import your handler modules
from handlers.expiry_handler import ExpiryHandler
from handlers.options_handler import OptionsHandler
try:
    from handlers.multi_stoploss_handler import MultiStrikeStopl0ssHandler
except:
    MultiStrikeStopl0ssHandler = None

# Initialize handler instances (will be created per bot)
expiry_handler = None
options_handler = None
multi_stoploss_handler = None

def init_handlers(delta_client):
    """Initialize handlers with delta client"""
    global expiry_handler, options_handler, multi_stoploss_handler
    expiry_handler = ExpiryHandler(delta_client)
    options_handler = OptionsHandler(delta_client)
    if MultiStrikeStopl0ssHandler:
        multi_stoploss_handler = MultiStrikeStopl0ssHandler(delta_client)

# Command handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    try:
        delta_client = context.application.bot_data.get('delta_client')
        account_name = context.application.bot_data.get('account_name', 'Trading Account')
        
        logger.info(f"Start command from user: {update.effective_user.id}")
        
        # Get portfolio
        import asyncio
        try:
            portfolio = await asyncio.wait_for(
                asyncio.to_thread(delta_client.get_portfolio_summary),
                timeout=10.0
            )
        except:
            portfolio = {"success": False}
        
        # Build message
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.constants import ParseMode
        
        message_parts = []
        message_parts.append(f"<b>🏦 {account_name}</b>")
        
        if portfolio.get('success'):
            balances = portfolio.get('result', [])
            total_balance = sum(float(b.get('available_balance', 0)) for b in balances)
            if total_balance > 0:
                message_parts.append(f"💰 <b>Portfolio Value:</b> ₹{total_balance:,.2f}")
        
        welcome = """
<b>🚀 Welcome to Delta Options Bot!</b>

<b>Available Actions:</b>
• 📊 View your current positions
• 📈 Start new options trading
• 🛡️ Multi-strike stop-loss protection
• 💰 Check portfolio summary

Choose an action below:"""
        
        message_parts.append(welcome)
        full_message = "\n\n".join(message_parts)
        
        keyboard = [
            [InlineKeyboardButton("📅 Select Expiry", callback_data="select_expiry")],
            [InlineKeyboardButton("📊 Show Positions", callback_data="show_positions")],
            [InlineKeyboardButton("🛡️ Multi-Strike Stop-Loss", callback_data="multi_strike_stoploss")],
            [InlineKeyboardButton("💰 Portfolio Summary", callback_data="portfolio_summary")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(full_message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error in start_command: {e}", exc_info=True)
        await update.message.reply_text("❌ An error occurred.")

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Positions command"""
    try:
        delta_client = context.application.bot_data.get('delta_client')
        account_name = context.application.bot_data.get('account_name', 'Trading Account')
        
        from utils.helpers import format_enhanced_positions_with_live_data
        from telegram.constants import ParseMode
        
        loading_msg = await update.message.reply_text("🔄 Fetching positions...")
        
        positions = delta_client.force_enhance_positions()
        portfolio = delta_client.get_portfolio_summary()
        
        if not positions.get('success'):
            await loading_msg.edit_text("❌ Failed to fetch positions.")
            return
        
        positions_data = positions.get('result', [])
        message_parts = [f"<b>🏦 {account_name}</b>\n"]
        
        if positions_data:
            positions_message = format_enhanced_positions_with_live_data(positions_data, delta_client)
            message_parts.append(positions_message)
        else:
            message_parts.append("📊 <b>No Open Positions</b>")
        
        if portfolio.get('success'):
            balances = portfolio.get('result', [])
            total_balance = sum(float(b.get('available_balance', 0)) for b in balances)
            if total_balance > 0:
                message_parts.append(f"💰 <b>Total: ₹{total_balance:,.2f}</b>")
        
        await loading_msg.edit_text("\n\n".join(message_parts), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in positions_command: {e}")
        await update.message.reply_text("❌ Error")

async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Orders command"""
    try:
        delta_client = context.application.bot_data.get('delta_client')
        from telegram.constants import ParseMode
        
        loading_msg = await update.message.reply_text("🔄 Fetching orders...")
        
        stop_orders = delta_client.get_stop_orders()
        
        if not stop_orders.get('success'):
            await loading_msg.edit_text("❌ Failed to fetch orders.")
            return
        
        orders_data = stop_orders.get('result', [])
        
        if not orders_data:
            await loading_msg.edit_text("📋 No active stop orders found.")
            return
        
        message = "<b>📋 Active Stop Orders</b>\n\n"
        for i, order in enumerate(orders_data[:10], 1):
            product_symbol = order.get('product_symbol', 'Unknown')
            side = order.get('side', 'Unknown')
            size = order.get('size', 0)
            stop_price = order.get('stop_price', 'N/A')
            
            message += f"<b>{i}. {product_symbol}</b>\n"
            message += f"   Side: {side.upper()}\n"
            message += f"   Size: {size}\n"
            message += f"   Stop: ${stop_price}\n\n"
        
        await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in orders_command: {e}")
        await update.message.reply_text("❌ Error")

async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Portfolio command"""
    await update.message.reply_text("Use /start to see portfolio summary")

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command"""
    account_id = context.application.bot_data.get('account_id', 'unknown')
    account_name = context.application.bot_data.get('account_name', 'Unknown')
    
    from telegram.constants import ParseMode
    
    message = f"""<b>🐛 Debug Info</b>

<b>Account:</b> {account_name}
<b>Account ID:</b> {account_id}
<b>User ID:</b> {update.effective_user.id}
<b>Chat ID:</b> {update.effective_chat.id}"""
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def stoploss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stoploss command"""
    await update.message.reply_text("Use the /start menu to access stop-loss features")

async def cancelstops_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel stops command"""
    await update.message.reply_text("Use the /start menu to manage stop orders")

# Callback handler
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main callback handler"""
    try:
        query = update.callback_query
        data = query.data
        
        delta_client = context.application.bot_data.get('delta_client')
        
        # Initialize handlers if not done
        global expiry_handler, options_handler, multi_stoploss_handler
        if not expiry_handler:
            init_handlers(delta_client)
        
        logger.info(f"Processing callback: {data}")
        
        if data == "select_expiry":
            await expiry_handler.show_expiry_selection(update, context)
        elif data.startswith("expiry_"):
            await expiry_handler.handle_expiry_selection(update, context)
        elif data.startswith("strategy_"):
            await options_handler.handle_strategy_selection(update, context)
        elif data == "show_positions":
            await show_positions_callback(update, context)
        elif data == "multi_strike_stoploss" and multi_stoploss_handler:
            await multi_stoploss_handler.show_multi_strike_menu(update, context)
        elif data.startswith("ms_") and multi_stoploss_handler:
            if data.startswith("ms_toggle_"):
                await multi_stoploss_handler.handle_position_toggle(update, context)
            elif data == "ms_proceed":
                await multi_stoploss_handler.handle_proceed_to_prices(update, context)
            elif data == "ms_clear":
                await multi_stoploss_handler.handle_clear_selection(update, context)
            elif data == "ms_cancel":
                await multi_stoploss_handler.handle_cancel(update, context)
        elif data == "portfolio_summary":
            await portfolio_summary_callback(update, context)
        elif data == "back_to_main":
            await back_to_main_callback(update, context)
        else:
            await query.answer("Unknown option")
        
    except Exception as e:
        logger.error(f"Error in callback_handler: {e}", exc_info=True)

async def show_positions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show positions callback"""
    try:
        query = update.callback_query
        await query.answer()
        
        delta_client = context.application.bot_data.get('delta_client')
        account_name = context.application.bot_data.get('account_name', 'Trading Account')
        
        from utils.helpers import format_enhanced_positions_with_live_data
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.constants import ParseMode
        
        positions = delta_client.force_enhance_positions()
        
        if not positions.get('success'):
            await query.edit_message_text("❌ Failed to fetch positions.")
            return
        
        positions_data = positions.get('result', [])
        
        if not positions_data:
            message = f"<b>🏦 {account_name}</b>\n\n📊 No Open Positions"
        else:
            header = f"<b>🏦 {account_name}</b>\n\n"
            positions_message = format_enhanced_positions_with_live_data(positions_data, delta_client)
            message = header + positions_message
        
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error: {e}")

async def portfolio_summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Portfolio summary"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Portfolio summary - under construction")

async def back_to_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Back to main"""
    query = update.callback_query
    await query.answer()
    # Simulate start command
    update.message = query.message
    await start_command(update, context)

# Message handler
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    try:
        delta_client = context.application.bot_data.get('delta_client')
        
        global expiry_handler, options_handler, multi_stoploss_handler
        if not expiry_handler:
            init_handlers(delta_client)
        
        if context.user_data.get('waiting_for_multi_trigger_percentage') and multi_stoploss_handler:
            await multi_stoploss_handler.handle_trigger_percentage_input(update, context)
        elif context.user_data.get('waiting_for_multi_limit_percentage') and multi_stoploss_handler:
            await multi_stoploss_handler.handle_limit_percentage_input(update, context)
        elif context.user_data.get('waiting_for_lot_size'):
            await options_handler.handle_lot_size_input(update, context)
        else:
            await update.message.reply_text("Use /start to see available options")
            
    except Exception as e:
        logger.error(f"Error in message_handler: {e}")

# ==================== END OF HANDLER FUNCTIONS ===================

# ==================== INITIALIZE BOTS ====================

async def initialize_bots():
    """Initialize bot(s)"""
    try:
        if MULTI_ACCOUNT_MODE:
            accounts = get_enabled_accounts()
            
            if not accounts:
                raise ValueError("No enabled accounts found")
            
            logger.info(f"🔧 Initializing {len(accounts)} bot(s)...")
            
            tasks = []
            for account_id, config in accounts.items():
                task = initialize_single_bot(
                    account_id=account_id,
                    bot_token=config['bot_token'],
                    api_key=config['delta_api_key'],
                    api_secret=config['delta_api_secret'],
                    account_name=config.get('account_name', account_id)
                )
                tasks.append(task)
            
            await asyncio.gather(*tasks)
            logger.info(f"✅ All {len(accounts)} bot(s) initialized!")
            
        else:
            # Single account mode
            bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
            api_key = os.getenv('DELTA_API_KEY')
            api_secret = os.getenv('DELTA_API_SECRET')
            
            if not all([bot_token, api_key, api_secret]):
                raise ValueError("Missing required environment variables")
            
            await initialize_single_bot(
                account_id='default',
                bot_token=bot_token,
                api_key=api_key,
                api_secret=api_secret,
                account_name='Main Account'
            )
            logger.info("✅ Single bot initialized!")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize bots: {e}", exc_info=True)
        raise

async def initialize_single_bot(account_id: str, bot_token: str, api_key: str, api_secret: str, account_name: str):
    """Initialize a single bot instance"""
    try:
        logger.info(f"🔧 Initializing: {account_name}")
        
        # Create Delta client
        delta_client = DeltaClient(api_key=api_key, api_secret=api_secret)
        delta_clients[account_id] = delta_client
        
        # Calculate pool size
        if MULTI_ACCOUNT_MODE:
            num_accounts = len(get_enabled_accounts())
            pool_size = max(5, 15 // num_accounts)
        else:
            pool_size = 20
        
        # Configure HTTP request
        request = HTTPXRequest(
            connection_pool_size=pool_size,
            pool_timeout=20.0,
            read_timeout=20.0,
            write_timeout=20.0,
            connect_timeout=20.0
        )
        
        # Create application
        application = (
            Application.builder()
            .token(bot_token)
            .request(request)
            .concurrent_updates(True)
            .build()
        )
        
        # Store context data
        application.bot_data['delta_client'] = delta_client
        application.bot_data['account_id'] = account_id
        application.bot_data['account_name'] = account_name
        
        # Also store in global for easy access
        import builtins
        builtins.delta_client = delta_client
        
        # Add handlers - dynamically find handler functions
        add_handlers_to_application(application)
        
        # Error handler
        application.add_error_handler(create_error_handler(account_id))
        
        # Initialize and start
        await application.initialize()
        await application.start()
        
        bot_applications[account_id] = application
        logger.info(f"✅ {account_name} ready!")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize {account_name}: {e}", exc_info=True)
        raise

def add_handlers_to_application(application):
    """Add all handlers to application - works with your current structure"""
    
    # Get the module where your handlers are defined
    # This will be your current main.py or wherever they actually are
    import importlib
    import inspect
    
    # Try different possible locations for handlers
    handler_modules = []
    
    # Try to import from current globals (if handlers are in this file)
    current_globals = globals()
    
    # Try to find handler functions
    handler_functions = {}
    
    # Common handler function names
    handler_names = [
        'start_command',
        'positions_command', 
        'orders_command',
        'portfolio_command',
        'stoploss_command',
        'cancelstops_command',
        'debug_command',
        'callback_handler',
        'message_handler',
        'show_positions_callback',
        'portfolio_summary_callback',
        'back_to_main_callback'
    ]
    
    # Search for handlers in current module
    for name in handler_names:
        if name in current_globals and callable(current_globals[name]):
            handler_functions[name] = current_globals[name]
    
    # If we found handlers, add them
    if handler_functions:
        logger.info(f"✅ Found {len(handler_functions)} handler functions")
        
        # Add command handlers if they exist
        if 'start_command' in handler_functions:
            application.add_handler(CommandHandler("start", handler_functions['start_command']))
        if 'positions_command' in handler_functions:
            application.add_handler(CommandHandler("positions", handler_functions['positions_command']))
        if 'orders_command' in handler_functions:
            application.add_handler(CommandHandler("orders", handler_functions['orders_command']))
        if 'portfolio_command' in handler_functions:
            application.add_handler(CommandHandler("portfolio", handler_functions['portfolio_command']))
        if 'debug_command' in handler_functions:
            application.add_handler(CommandHandler("debug", handler_functions['debug_command']))
        if 'stoploss_command' in handler_functions:
            application.add_handler(CommandHandler("stoploss", handler_functions['stoploss_command']))
        if 'cancelstops_command' in handler_functions:
            application.add_handler(CommandHandler("cancelstops", handler_functions['cancelstops_command']))
        
        # Add callback and message handlers
        if 'callback_handler' in handler_functions:
            application.add_handler(CallbackQueryHandler(handler_functions['callback_handler']))
        if 'message_handler' in handler_functions:
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler_functions['message_handler']))
        
        logger.info("✅ Handlers registered successfully")
    else:
        logger.warning("⚠️ No handler functions found - bot will not respond to commands")

def create_error_handler(account_id: str):
    """Create error handler"""
    
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            logger.error(f"[{account_id}] Error: {context.error}")
            
            if isinstance(context.error, (TimedOut, NetworkError, RetryAfter)):
                return
            
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text("❌ An error occurred.")
                except:
                    pass
        except:
            pass
    
    return error_handler

# ==================== WEBHOOK SETUP ====================

async def setup_webhooks():
    """Setup webhooks"""
    if not WEBHOOK_ENABLED or not WEBHOOK_BASE_URL:
        return
    
    logger.info("🌐 Setting up webhooks...")
    
    if MULTI_ACCOUNT_MODE:
        accounts = get_enabled_accounts()
        for account_id, config in accounts.items():
            try:
                bot = bot_applications[account_id]
                webhook_url = f"{WEBHOOK_BASE_URL}{config['webhook_path']}"
                await bot.bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
                logger.info(f"✅ Webhook: {config['account_name']}")
            except Exception as e:
                logger.error(f"Webhook failed for {account_id}: {e}")
    else:
        bot = bot_applications['default']
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        webhook_url = f"{WEBHOOK_BASE_URL}/{bot_token}"
        await bot.bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
        logger.info(f"✅ Webhook set")

async def start_webhook_server():
    """Start webhook server"""
    import tornado.web
    import json
    
    class WebhookHandler(tornado.web.RequestHandler):
        async def post(self, bot_token):
            try:
                bot_app = None
                
                if MULTI_ACCOUNT_MODE:
                    for account_id, config in get_enabled_accounts().items():
                        if config['bot_token'] == bot_token:
                            bot_app = bot_applications.get(account_id)
                            break
                else:
                    if bot_token == os.getenv('TELEGRAM_BOT_TOKEN'):
                        bot_app = bot_applications.get('default')
                
                if not bot_app:
                    self.set_status(404)
                    return
                
                update_data = json.loads(self.request.body)
                update = Update.de_json(update_data, bot_app.bot)
                asyncio.create_task(bot_app.process_update(update))
                
                self.set_status(200)
            except Exception as e:
                logger.error(f"Webhook error: {e}")
                self.set_status(500)
    
    class MainHandler(tornado.web.RequestHandler):
        def get(self):
            self.write(f"<html><body><h1>Bot Running</h1><p>{len(bot_applications)} account(s)</p></body></html>")
    
    class HealthHandler(tornado.web.RequestHandler):
        def get(self):
            self.write({"status": "healthy"})
        def head(self):
            self.set_status(200)
    
    routes = [
        (r"/", MainHandler),
        (r"/health", HealthHandler),
        (r"/uptime", HealthHandler),
        (r"/([^/]+)", WebhookHandler),
    ]
    
    app = tornado.web.Application(routes)
    app.listen(SERVER_PORT, SERVER_HOST)
    logger.info(f"🌐 Server: {SERVER_HOST}:{SERVER_PORT}")

# ==================== MAIN ====================

async def main():
    """Main function"""
    try:
        await initialize_bots()
        await setup_webhooks()
        
        if WEBHOOK_ENABLED and WEBHOOK_BASE_URL:
            await start_webhook_server()
            logger.info("✅ Bot ready!")
            while True:
                await asyncio.sleep(60)
        else:
            logger.info("🚀 Running")
            while True:
                await asyncio.sleep(60)
    
    except KeyboardInterrupt:
        logger.info("🛑 Stopping...")
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
    finally:
        for account_id, bot in bot_applications.items():
            try:
                await bot.stop()
                await bot.shutdown()
            except:
                pass
        logger.info("👋 Goodbye!")

if __name__ == "__main__":
    asyncio.run(main())
  
