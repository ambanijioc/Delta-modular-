# main.py
"""
Multi-Account Delta Options Bot - Compatible with existing structure
"""

import asyncio
import logging
import os
import sys
import signal

# Configure logging first
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Check for required environment variables (for backwards compatibility)
required_vars = ['TELEGRAM_BOT_TOKEN', 'DELTA_API_KEY', 'DELTA_API_SECRET']
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    logger.warning(f"⚠️ Missing environment variables: {', '.join(missing_vars)}")
    logger.info("ℹ️ Will look for multi-account configuration...")

# Import Telegram components
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
from telegram.request import HTTPXRequest
from telegram.error import TimedOut, NetworkError, RetryAfter

# Import your existing components
from api.delta_client import DeltaClient

# Try to import multi-account config, fallback to single account
try:
    from config.accounts_config import get_enabled_accounts, WEBHOOK_ENABLED, WEBHOOK_BASE_URL, SERVER_HOST, SERVER_PORT
    MULTI_ACCOUNT_MODE = True
    logger.info("✅ Multi-account configuration found")
except ImportError:
    MULTI_ACCOUNT_MODE = False
    logger.info("ℹ️ Running in single-account mode (backwards compatible)")
    
    # Single account configuration (backwards compatible)
    WEBHOOK_ENABLED = os.getenv('WEBHOOK_ENABLED', 'true').lower() == 'true'
    WEBHOOK_BASE_URL = os.getenv('WEBHOOK_URL', '')
    SERVER_HOST = os.getenv('HOST', '0.0.0.0')
    SERVER_PORT = int(os.getenv('PORT', 10000))

# Global variables
bot_applications = {}
delta_clients = {}

# ==================== SINGLE ACCOUNT MODE ====================

async def initialize_single_bot():
    """Initialize bot in single-account mode (backwards compatible)"""
    try:
        logger.info("🔧 Initializing bot in single-account mode...")
        
        # Get credentials from environment
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        api_key = os.getenv('DELTA_API_KEY')
        api_secret = os.getenv('DELTA_API_SECRET')
        
        if not all([bot_token, api_key, api_secret]):
            raise ValueError("Missing required environment variables for single-account mode")
        
        # Create Delta client
        delta_client = DeltaClient(api_key=api_key, api_secret=api_secret)
        delta_clients['default'] = delta_client
        
        # Configure HTTP request
        request = HTTPXRequest(
            connection_pool_size=20,
            pool_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            connect_timeout=30.0
        )
        
        # Create application
        application = (
            Application.builder()
            .token(bot_token)
            .request(request)
            .concurrent_updates(True)
            .build()
        )
        
        # Add handlers
        add_single_account_handlers(application, delta_client)
        
        # Add error handler
        application.add_error_handler(create_error_handler('default'))
        
        # Initialize and start
        await application.initialize()
        await application.start()
        
        bot_applications['default'] = application
        
        logger.info("✅ Single bot initialized successfully")
        return application
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize single bot: {e}", exc_info=True)
        raise

def add_single_account_handlers(application, delta_client):
    """Add handlers for single-account mode"""
    
    # Import your existing handlers
    try:
        from handlers.expiry_handler import ExpiryHandler
        from handlers.options_handler import OptionsHandler
        from handlers.stoploss_handler import StoplossHandler
        from handlers.multi_stoploss_handler import MultiStrikeStopl0ssHandler
        
        # Initialize handlers
        expiry_handler = ExpiryHandler(delta_client)
        options_handler = OptionsHandler(delta_client)
        stoploss_handler = StoplossHandler(delta_client)
        multi_stoploss_handler = MultiStrikeStopl0ssHandler(delta_client)
        
    except ImportError as e:
        logger.error(f"Failed to import handlers: {e}")
        raise
    
    # Create command handlers
    from handlers.command_handlers import (
        start_command,
        positions_command,
        orders_command,
        portfolio_command,
        stoploss_command,
        cancelstops_command,
        debug_command,
        callback_handler,
        message_handler
    )
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("orders", orders_command))
    application.add_handler(CommandHandler("portfolio", portfolio_command))
    application.add_handler(CommandHandler("stoploss", stoploss_command))
    application.add_handler(CommandHandler("cancelstops", cancelstops_command))
    application.add_handler(CommandHandler("debug", debug_command))
    
    # Add callback and message handlers
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    logger.info("✅ Single-account handlers added")

# ==================== MULTI ACCOUNT MODE ====================

async def initialize_multi_bots():
    """Initialize multiple bots for multi-account mode"""
    try:
        accounts = get_enabled_accounts()
        
        if not accounts:
            raise ValueError("No enabled accounts found in configuration")
        
        logger.info(f"🔧 Initializing {len(accounts)} bot(s)...")
        
        tasks = []
        for account_id, config in accounts.items():
            task = initialize_account_bot(account_id, config)
            tasks.append(task)
        
        # Initialize all bots concurrently
        await asyncio.gather(*tasks)
        
        logger.info(f"✅ All {len(accounts)} bot(s) initialized successfully!")
        
        return bot_applications
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize multi-bots: {e}", exc_info=True)
        raise

async def initialize_account_bot(account_id: str, config: dict):
    """Initialize a single bot for a specific account"""
    try:
        logger.info(f"🔧 Initializing bot for: {config['account_name']}")
        
        # Create Delta client
        delta_client = DeltaClient(
            api_key=config['delta_api_key'],
            api_secret=config['delta_api_secret']
        )
        delta_clients[account_id] = delta_client
        
        # Calculate pool size based on number of accounts
        num_accounts = len(get_enabled_accounts())
        pool_size = max(5, 15 // num_accounts)
        
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
            .token(config['bot_token'])
            .request(request)
            .concurrent_updates(True)
            .build()
        )
        
        # Add handlers
        add_multi_account_handlers(application, delta_client, account_id, config['account_name'])
        
        # Add error handler
        application.add_error_handler(create_error_handler(account_id))
        
        # Initialize and start
        await application.initialize()
        await application.start()
        
        bot_applications[account_id] = application
        
        logger.info(f"✅ Bot initialized: {config['account_name']}")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize bot {account_id}: {e}", exc_info=True)
        raise

def add_multi_account_handlers(application, delta_client, account_id, account_name):
    """Add handlers for multi-account mode"""
    
    # Import your existing handlers
    try:
        from handlers.expiry_handler import ExpiryHandler
        from handlers.options_handler import OptionsHandler
        from handlers.stoploss_handler import StoplossHandler
        from handlers.multi_stoploss_handler import MultiStrikeStopl0ssHandler
        
        # Initialize handlers
        expiry_handler = ExpiryHandler(delta_client)
        options_handler = OptionsHandler(delta_client)
        stoploss_handler = StoplossHandler(delta_client)
        multi_stoploss_handler = MultiStrikeStopl0ssHandler(delta_client)
        
    except ImportError as e:
        logger.error(f"Failed to import handlers: {e}")
        raise
    
    # Import command handlers (they should already exist in your handlers/command_handlers.py)
    try:
        from handlers.command_handlers import (
            start_command,
            positions_command,
            orders_command,
            portfolio_command,
            stoploss_command,
            cancelstops_command,
            debug_command,
            callback_handler,
            message_handler
        )
    except ImportError:
        logger.error("Could not import command_handlers. Make sure handlers/command_handlers.py exists")
        raise
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("orders", orders_command))
    application.add_handler(CommandHandler("portfolio", portfolio_command))
    application.add_handler(CommandHandler("stoploss", stoploss_command))
    application.add_handler(CommandHandler("cancelstops", cancelstops_command))
    application.add_handler(CommandHandler("debug", debug_command))
    
    # Add callback and message handlers
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    logger.info(f"✅ Handlers added for: {account_name}")

# ==================== ERROR HANDLER ====================

def create_error_handler(account_id: str):
    """Create error handler for a specific account"""
    
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            logger.error(f"[{account_id}] Error: {context.error}")
            
            if isinstance(context.error, TimedOut):
                logger.warning(f"[{account_id}] ⚠️ Telegram API timeout")
                return
            elif isinstance(context.error, NetworkError):
                logger.warning(f"[{account_id}] ⚠️ Network error")
                return
            elif isinstance(context.error, RetryAfter):
                logger.warning(f"[{account_id}] ⚠️ Rate limited")
                return
            
            # Try to notify user
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text(
                        "❌ An error occurred. Please try again."
                    )
                except Exception as e:
                    logger.error(f"Failed to send error message: {e}")
        
        except Exception as e:
            logger.error(f"Error in error_handler: {e}")
    
    return error_handler

# ==================== WEBHOOK SERVER ====================

async def setup_webhooks():
    """Setup webhooks for all bots"""
    if not WEBHOOK_ENABLED or not WEBHOOK_BASE_URL:
        logger.info("Webhooks disabled - running in polling mode")
        return
    
    logger.info("🌐 Setting up webhooks...")
    
    if MULTI_ACCOUNT_MODE:
        accounts = get_enabled_accounts()
        for account_id, config in accounts.items():
            try:
                bot = bot_applications[account_id]
                webhook_url = f"{WEBHOOK_BASE_URL}{config['webhook_path']}"
                
                await bot.bot.set_webhook(
                    url=webhook_url,
                    allowed_updates=["message", "callback_query"]
                )
                
                logger.info(f"✅ Webhook set for {config['account_name']}: {webhook_url}")
            except Exception as e:
                logger.error(f"Failed to set webhook for {account_id}: {e}")
    else:
        # Single account webhook
        bot = bot_applications['default']
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        webhook_url = f"{WEBHOOK_BASE_URL}/{bot_token}"
        
        await bot.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query"]
        )
        
        logger.info(f"✅ Webhook set: {webhook_url}")

async def start_webhook_server():
    """Start webhook server using Tornado"""
    import tornado.web
    import tornado.ioloop
    import json
    
    class WebhookHandler(tornado.web.RequestHandler):
        """Handle webhook requests"""
        
        async def post(self, bot_token):
            try:
                content_length = len(self.request.body)
                logger.info(f"📨 Webhook: {content_length} bytes")
                
                # Find the bot
                bot_app = None
                
                if MULTI_ACCOUNT_MODE:
                    accounts = get_enabled_accounts()
                    for account_id, config in accounts.items():
                        if config['bot_token'] == bot_token:
                            bot_app = bot_applications.get(account_id)
                            break
                else:
                    if bot_token == os.getenv('TELEGRAM_BOT_TOKEN'):
                        bot_app = bot_applications.get('default')
                
                if not bot_app:
                    logger.error(f"❌ Unknown bot token")
                    self.set_status(404)
                    return
                
                # Process update
                update_data = json.loads(self.request.body)
                update = Update.de_json(update_data, bot_app.bot)
                asyncio.create_task(bot_app.process_update(update))
                
                self.set_status(200)
                
            except Exception as e:
                logger.error(f"❌ Webhook error: {e}", exc_info=True)
                self.set_status(500)
    
    class MainHandler(tornado.web.RequestHandler):
        def get(self):
            user_agent = self.request.headers.get('User-Agent', 'Unknown')
            logger.info(f"Root request from {self.request.remote_ip} - User-Agent: {user_agent}")
            
            num_accounts = len(bot_applications)
            self.write(f"""
                <html>
                <head><title>Delta Options Bot</title></head>
                <body>
                    <h1>🤖 Delta Options Bot</h1>
                    <p>✅ Bot is running with {num_accounts} account(s)</p>
                    <p><em>Send commands to your Telegram bot.</em></p>
                </body>
                </html>
            """)
    
    class HealthHandler(tornado.web.RequestHandler):
        def get(self):
            self.write({"status": "healthy", "accounts": len(bot_applications)})
        
        def head(self):
            self.set_status(200)
    
    # Create routes
    routes = [
        (r"/", MainHandler),
        (r"/health", HealthHandler),
        (r"/uptime", HealthHandler),
        (r"/([^/]+)", WebhookHandler),  # Catch-all for bot tokens
    ]
    
    app = tornado.web.Application(routes)
    app.listen(SERVER_PORT, SERVER_HOST)
    
    logger.info(f"🌐 Server listening on {SERVER_HOST}:{SERVER_PORT}")
    logger.info("✅ Bot ready!")

# ==================== MAIN FUNCTION ====================

async def main():
    """Main function"""
    try:
        # Initialize bots
        if MULTI_ACCOUNT_MODE:
            await initialize_multi_bots()
        else:
            await initialize_single_bot()
        
        # Setup webhooks
        await setup_webhooks()
        
        # Start webhook server
        if WEBHOOK_ENABLED and WEBHOOK_BASE_URL:
            await start_webhook_server()
            
            # Keep running
            while True:
                await asyncio.sleep(60)
        else:
            logger.warning("⚠️ Running in polling mode")
            logger.info("🚀 Bot running. Press Ctrl+C to stop.")
            
            while True:
                await asyncio.sleep(60)
    
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
    except Exception as e:
        logger.error(f"❌ Critical error: {e}", exc_info=True)
    finally:
        # Shutdown all bots
        for account_id, bot in bot_applications.items():
            try:
                await bot.stop()
                await bot.shutdown()
                logger.info(f"✅ Bot {account_id} stopped")
            except Exception as e:
                logger.error(f"Error stopping bot {account_id}: {e}")
        
        logger.info("👋 Goodbye!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        
