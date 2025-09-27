import asyncio
import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import tornado.web
import tornado.ioloop
import tornado.httpserver
import json

from config.config import TELEGRAM_BOT_TOKEN, HOST, PORT
from api.delta_client import DeltaClient
from api.telegram_client import TelegramClient
from handlers.expiry_handler import ExpiryHandler
from handlers.options_handler import OptionsHandler
from handlers.position_handler import PositionHandler
from utils.constants import START_MESSAGE, HELP_MESSAGE

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize clients and handlers
delta_client = DeltaClient()
telegram_client = TelegramClient(TELEGRAM_BOT_TOKEN)
expiry_handler = ExpiryHandler(delta_client)
options_handler = OptionsHandler(delta_client)
position_handler = PositionHandler(delta_client)

# Initialize bot application
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    logger.info(f"Start command from user: {update.effective_user.id}")
    reply_markup = telegram_client.create_main_menu_keyboard()
    await update.message.reply_text(
        START_MESSAGE,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    logger.info(f"Help command from user: {update.effective_user.id}")
    await update.message.reply_text(
        HELP_MESSAGE,
        parse_mode=ParseMode.HTML
    )

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /positions command"""
    logger.info(f"Positions command from user: {update.effective_user.id}")
    positions = delta_client.get_positions()
    
    if not positions.get('success'):
        await update.message.reply_text("❌ Unable to fetch positions. Please try again.")
        return
    
    positions_data = positions.get('result', [])
    
    if not positions_data:
        await update.message.reply_text("📊 No open positions found.")
        return
    
    from utils.helpers import format_positions_message
    message = format_positions_message(positions_data)
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    logger.info(f"Callback query: {update.callback_query.data}")
    query = update.callback_query
    data = query.data
    
    if data == "select_expiry":
        await expiry_handler.show_expiry_selection(update, context)
    elif data.startswith("expiry_"):
        await expiry_handler.handle_expiry_selection(update, context)
    elif data.startswith("strategy_"):
        await options_handler.handle_strategy_selection(update, context)
    elif data == "show_positions":
        await position_handler.show_positions(update, context)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    logger.info(f"Text message from user {update.effective_user.id}: {update.message.text}")
    
    if context.user_data.get('waiting_for_lot_size'):
        await options_handler.handle_lot_size_input(update, context)
    else:
        # Echo message for testing
        await update.message.reply_text(f"Echo: {update.message.text}")

# Add handlers to application
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("positions", positions_command))
application.add_handler(CallbackQueryHandler(callback_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

class RootHandler(tornado.web.RequestHandler):
    """Handle root path requests"""
    def get(self):
        self.set_status(200)
        self.set_header("Content-Type", "application/json")
        self.write({
            "status": "active",
            "service": "BTC Options Trading Bot",
            "version": "1.0.0",
            "bot_username": "@your_bot_username",
            "endpoints": {
                "webhook": f"/{TELEGRAM_BOT_TOKEN}",
                "health": "/health",
                "status": "/"
            }
        })

class WebhookHandler(tornado.web.RequestHandler):
    """Handle incoming webhook updates"""
    async def post(self):
        try:
            body = self.request.body.decode('utf-8')
            logger.info(f"📨 Received webhook: {len(body)} bytes from {self.request.remote_ip}")
            
            if not body:
                logger.warning("Empty webhook body received")
                self.set_status(400)
                self.write("Bad Request: Empty body")
                return
            
            update_data = json.loads(body)
            logger.info(f"📊 Update data: {json.dumps(update_data, indent=2)}")
            
            update = Update.de_json(update_data, application.bot)
            
            if not hasattr(WebhookHandler, '_initialized'):
                await application.initialize()
                WebhookHandler._initialized = True
                logger.info("✅ Application initialized")
            
            # Process the update
            await application.process_update(update)
            logger.info("✅ Update processed successfully")
            
            self.set_status(200)
            self.write("OK")
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in webhook: {e}")
            self.set_status(400)
            self.write("Bad Request: Invalid JSON")
        except Exception as e:
            logger.error(f"❌ Error processing update: {e}", exc_info=True)
            self.set_status(500)
            self.write("Internal Server Error")

class HealthHandler(tornado.web.RequestHandler):
    """Health check endpoint"""
    def get(self):
        try:
            health_status = {
                "status": "healthy",
                "service": "btc-options-bot",
                "version": "1.0.0",
                "webhook_configured": bool(TELEGRAM_BOT_TOKEN)
            }
            
            self.set_status(200)
            self.set_header("Content-Type", "application/json")
            self.write(health_status)
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self.set_status(503)
            self.write({"status": "unhealthy", "error": str(e)})

def make_app():
    """Create Tornado application with all routes"""
    return tornado.web.Application([
        (r"/", RootHandler),
        (rf"/{TELEGRAM_BOT_TOKEN}", WebhookHandler),
        (r"/health", HealthHandler),
    ], debug=False)

async def setup_webhook():
    """Set up webhook with proper allowed_updates"""
    # Get webhook URL from environment or construct it
    webhook_url = os.getenv('WEBHOOK_URL')
    if not webhook_url:
        app_name = os.getenv('RENDER_SERVICE_NAME', 'your-app-name')
        webhook_url = f"https://{app_name}.onrender.com/{TELEGRAM_BOT_TOKEN}"
    
    logger.info(f"🔗 Setting webhook to: {webhook_url}")
    
    try:
        # Clear existing webhook first
        await application.bot.delete_webhook()
        logger.info("🧹 Cleared existing webhook")
        
        # Set new webhook with allowed_updates
        success = await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=['message', 'callback_query']  # Key fix!
        )
        
        if success:
            logger.info("✅ Webhook set successfully")
            
            # Verify webhook setup
            webhook_info = await application.bot.get_webhook_info()
            logger.info(f"📊 Webhook info: URL={webhook_info.url}, Pending={webhook_info.pending_update_count}")
            
            return True
        else:
            logger.error("❌ Failed to set webhook")
            return False
            
    except Exception as e:
        logger.error(f"❌ Webhook setup failed: {e}")
        return False

async def initialize_services():
    """Initialize all services"""
    try:
        logger.info("🚀 Initializing services...")
        
        # Initialize Telegram bot
        await application.initialize()
        logger.info("✅ Telegram bot initialized")
        
        # Set webhook
        webhook_success = await setup_webhook()
        if not webhook_success:
            logger.warning("⚠️ Webhook setup failed")
            return False
        
        # Test bot
        me = await application.bot.get_me()
        logger.info(f"✅ Bot info: @{me.username} ({me.first_name})")
        
        logger.info("🎉 All services initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Service initialization failed: {e}")
        return False

def main():
    """Main function to run the bot"""
    logger.info("🤖 Starting BTC Options Trading Bot")
    
    # Create Tornado app
    app = make_app()
    
    # Set up HTTP server
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(PORT, HOST)
    
    logger.info(f"🌐 Server listening on {HOST}:{PORT}")
    
    # Initialize services
    loop = asyncio.get_event_loop()
    
    try:
        initialization_success = loop.run_until_complete(initialize_services())
        
        if not initialization_success:
            logger.error("❌ Failed to initialize services")
            return
        
        logger.info("✅ Bot ready! Send /start to test.")
        
        # Start event loop
        tornado.ioloop.IOLoop.current().start()
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        loop.run_until_complete(application.stop())
        loop.run_until_complete(application.shutdown())

if __name__ == '__main__':
    main()
        
