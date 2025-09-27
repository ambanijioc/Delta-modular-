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

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)
    
    # Try to inform user about the error
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An error occurred. Please try again or use /start to restart."
            )
    except Exception as e:
        logger.error(f"Failed to send error message: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        logger.info(f"Start command from user: {update.effective_user.id}")
        
        # Clear any existing user data
        context.user_data.clear()
        
        reply_markup = telegram_client.create_main_menu_keyboard()
        await update.message.reply_text(
            START_MESSAGE,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in start_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to start bot. Please try again.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    try:
        logger.info(f"Help command from user: {update.effective_user.id}")
        await update.message.reply_text(
            HELP_MESSAGE,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error in help_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to show help. Please try again.")

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /positions command"""
    try:
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
        
    except Exception as e:
        logger.error(f"Error in positions_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to fetch positions. Please try again.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    try:
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
        else:
            await query.answer("Unknown option")
            
    except Exception as e:
        logger.error(f"Error in callback_handler: {e}", exc_info=True)
        try:
            await update.callback_query.answer("❌ An error occurred")
        except:
            pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    try:
        logger.info(f"Text message from user {update.effective_user.id}: {update.message.text}")
        
        if context.user_data.get('waiting_for_lot_size'):
            await options_handler.handle_lot_size_input(update, context)
        else:
            # Provide helpful guidance
            await update.message.reply_text(
                "👋 Hi! Use /start to begin trading or choose an option from the menu.",
                reply_markup=telegram_client.create_main_menu_keyboard()
            )
            
    except Exception as e:
        logger.error(f"Error in message_handler: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ An error occurred. Please try /start")
        except:
            pass

# Add handlers to application
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("positions", positions_command))
application.add_handler(CallbackQueryHandler(callback_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

# Add error handler
application.add_error_handler(error_handler)

class RootHandler(tornado.web.RequestHandler):
    """Handle root path requests"""
    def get(self):
        self.set_status(200)
        self.set_header("Content-Type", "application/json")
        self.write({
            "status": "active",
            "service": "BTC Options Trading Bot",
            "version": "1.0.0"
        })

class WebhookHandler(tornado.web.RequestHandler):
    """Handle incoming webhook updates"""
    async def post(self):
        try:
            body = self.request.body.decode('utf-8')
            logger.info(f"📨 Received webhook: {len(body)} bytes")
            
            if not body:
                self.set_status(400)
                self.write("Bad Request: Empty body")
                return
            
            update_data = json.loads(body)
            update = Update.de_json(update_data, application.bot)
            
            if not hasattr(WebhookHandler, '_initialized'):
                await application.initialize()
                WebhookHandler._initialized = True
            
            await application.process_update(update)
            
            self.set_status(200)
            self.write("OK")
            
        except Exception as e:
            logger.error(f"❌ Webhook error: {e}", exc_info=True)
            self.set_status(500)
            self.write("Internal Server Error")

class HealthHandler(tornado.web.RequestHandler):
    """Health check endpoint"""
    def get(self):
        self.set_status(200)
        self.set_header("Content-Type", "application/json")
        self.write({"status": "healthy", "service": "btc-options-bot"})

def make_app():
    return tornado.web.Application([
        (r"/", RootHandler),
        (rf"/{TELEGRAM_BOT_TOKEN}", WebhookHandler),
        (r"/health", HealthHandler),
    ])

async def setup_webhook():
    """Set up webhook"""
    webhook_url = os.getenv('WEBHOOK_URL')
    if not webhook_url:
        app_name = os.getenv('RENDER_SERVICE_NAME', 'your-app-name')
        webhook_url = f"https://{app_name}.onrender.com/{TELEGRAM_BOT_TOKEN}"
    
    try:
        await application.bot.delete_webhook()
        success = await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=['message', 'callback_query']
        )
        if success:
            logger.info("✅ Webhook set successfully")
        return success
    except Exception as e:
        logger.error(f"❌ Webhook setup failed: {e}")
        return False

def main():
    """Main function"""
    logger.info("🤖 Starting BTC Options Trading Bot")
    
    app = make_app()
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(PORT, HOST)
    
    loop = asyncio.get_event_loop()
    
    try:
        loop.run_until_complete(application.initialize())
        loop.run_until_complete(setup_webhook())
        
        logger.info("✅ Bot ready!")
        tornado.ioloop.IOLoop.current().start()
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        loop.run_until_complete(application.stop())
        loop.run_until_complete(application.shutdown())

if __name__ == '__main__':
    main()
    
