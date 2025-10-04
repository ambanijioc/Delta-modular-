# main.py
"""
Multi-Account Delta Options Bot - Compatible with existing handler structure
"""

import asyncio
import logging
import os
import sys

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

# Import your existing components
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

# ==================== INITIALIZE BOTS ====================

async def initialize_bots():
    """Initialize bot(s) based on mode"""
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
        
        # Make delta_client accessible to handlers
        application.bot_data['delta_client'] = delta_client
        application.bot_data['account_id'] = account_id
        application.bot_data['account_name'] = account_name
        
        # Add handlers - import your ACTUAL command handlers
        from handlers import command_handlers
        
        # Command handlers
        application.add_handler(CommandHandler("start", command_handlers.start_command))
        application.add_handler(CommandHandler("positions", command_handlers.positions_command))
        application.add_handler(CommandHandler("orders", command_handlers.orders_command))
        application.add_handler(CommandHandler("portfolio", command_handlers.portfolio_command))
        application.add_handler(CommandHandler("debug", command_handlers.debug_command))
        
        # Optional commands (if they exist)
        try:
            application.add_handler(CommandHandler("stoploss", command_handlers.stoploss_command))
            application.add_handler(CommandHandler("cancelstops", command_handlers.cancelstops_command))
        except AttributeError:
            logger.warning(f"Some commands not available for {account_name}")
        
        # Callback and message handlers
        application.add_handler(CallbackQueryHandler(command_handlers.callback_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, command_handlers.message_handler))
        
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

def create_error_handler(account_id: str):
    """Create error handler"""
    
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            logger.error(f"[{account_id}] Error: {context.error}")
            
            if isinstance(context.error, (TimedOut, NetworkError, RetryAfter)):
                logger.warning(f"[{account_id}] ⚠️ Telegram error (non-critical)")
                return
            
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text("❌ An error occurred. Please try again.")
                except:
                    pass
        except Exception as e:
            logger.error(f"Error in error_handler: {e}")
    
    return error_handler

# ==================== WEBHOOK SETUP ====================

async def setup_webhooks():
    """Setup webhooks for all bots"""
    if not WEBHOOK_ENABLED or not WEBHOOK_BASE_URL:
        logger.info("Webhooks disabled")
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
                
                logger.info(f"✅ Webhook set: {config['account_name']}")
            except Exception as e:
                logger.error(f"Failed to set webhook for {account_id}: {e}")
    else:
        bot = bot_applications['default']
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        webhook_url = f"{WEBHOOK_BASE_URL}/{bot_token}"
        
        await bot.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query"]
        )
        
        logger.info(f"✅ Webhook set: {webhook_url}")

async def start_webhook_server():
    """Start webhook server"""
    import tornado.web
    import json
    
    class WebhookHandler(tornado.web.RequestHandler):
        async def post(self, bot_token):
            try:
                logger.info(f"📨 Webhook: {len(self.request.body)} bytes")
                
                # Find bot
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
                
                # Process update
                update_data = json.loads(self.request.body)
                update = Update.de_json(update_data, bot_app.bot)
                asyncio.create_task(bot_app.process_update(update))
                
                self.set_status(200)
            except Exception as e:
                logger.error(f"Webhook error: {e}")
                self.set_status(500)
    
    class MainHandler(tornado.web.RequestHandler):
        def get(self):
            logger.info(f"Root request from {self.request.remote_ip}")
            self.write(f"""
                <html><body>
                <h1>🤖 Delta Options Bot</h1>
                <p>✅ Running with {len(bot_applications)} account(s)</p>
                </body></html>
            """)
    
    class HealthHandler(tornado.web.RequestHandler):
        def get(self):
            self.write({"status": "healthy", "accounts": len(bot_applications)})
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
    
    logger.info(f"🌐 Server listening on {SERVER_HOST}:{SERVER_PORT}")

# ==================== MAIN ====================

async def main():
    """Main function"""
    try:
        # Initialize bots
        await initialize_bots()
        
        # Setup webhooks
        await setup_webhooks()
        
        # Start server
        if WEBHOOK_ENABLED and WEBHOOK_BASE_URL:
            await start_webhook_server()
            logger.info("✅ Bot ready!")
            
            while True:
                await asyncio.sleep(60)
        else:
            logger.info("🚀 Bot running in polling mode")
            while True:
                await asyncio.sleep(60)
    
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
    except Exception as e:
        logger.error(f"❌ Critical error: {e}", exc_info=True)
    finally:
        for account_id, bot in bot_applications.items():
            try:
                await bot.stop()
                await bot.shutdown()
                logger.info(f"✅ {account_id} stopped")
            except:
                pass
        logger.info("👋 Goodbye!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
