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
import signal
import sys

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

# Global application instance
application = None
webhook_health_check_interval = 300  # 5 minutes

async def periodic_webhook_check():
    """Periodically check and fix webhook if needed"""
    global application
    
    while True:
        try:
            await asyncio.sleep(webhook_health_check_interval)
            logger.info("🔍 Checking webhook health...")
            
            # Get webhook info
            webhook_info = await application.bot.get_webhook_info()
            
            if not webhook_info.url:
                logger.warning("⚠️ Webhook not set, attempting to fix...")
                success = await setup_webhook()
                if success:
                    logger.info("✅ Webhook restored successfully")
                else:
                    logger.error("❌ Failed to restore webhook")
            elif webhook_info.pending_update_count > 50:
                logger.warning(f"⚠️ High pending updates: {webhook_info.pending_update_count}")
                # Consider clearing and resetting webhook if too many pending updates
                if webhook_info.pending_update_count > 100:
                    logger.warning("🔄 Resetting webhook due to high pending updates...")
                    await setup_webhook()
            else:
                logger.info(f"✅ Webhook healthy - URL: {webhook_info.url[:50]}...")
                
        except Exception as e:
            logger.error(f"❌ Webhook health check failed: {e}")

async def setup_webhook():
    """Enhanced webhook setup with retry logic"""
    global application
    
    # Construct webhook URL
    webhook_url = os.getenv('WEBHOOK_URL')
    if not webhook_url:
        # Try to get from Render environment
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
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Clear existing webhook first
            await application.bot.delete_webhook(drop_pending_updates=True)
            logger.info("🧹 Cleared existing webhook and pending updates")
            
            # Wait a moment
            await asyncio.sleep(2)
            
            # Set new webhook
            success = await application.bot.set_webhook(
                url=webhook_url,
                allowed_updates=['message', 'callback_query'],
                drop_pending_updates=True,
                max_connections=10  # Reduce load
            )
            
            if success:
                # Verify webhook was set
                webhook_info = await application.bot.get_webhook_info()
                if webhook_info.url == webhook_url:
                    logger.info("✅ Webhook verified successfully")
                    return True
                else:
                    logger.error(f"❌ Webhook verification failed: expected {webhook_url}, got {webhook_info.url}")
            
        except Exception as e:
            logger.error(f"❌ Webhook setup attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(5)  # Wait before retry
    
    logger.error("❌ All webhook setup attempts failed")
    return False

# Initialize clients and handlers
delta_client = DeltaClient()
telegram_client = TelegramClient(TELEGRAM_BOT_TOKEN)
expiry_handler = ExpiryHandler(delta_client)
options_handler = OptionsHandler(delta_client)
position_handler = PositionHandler(delta_client)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced error handler"""
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)
    
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

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command to check system status"""
    try:
        logger.info(f"Debug command from user: {update.effective_user.id}")
        
        # Test Delta API
        connection_test = delta_client.test_connection()
        api_status = "✅ Connected" if connection_test.get('success') else f"❌ Failed: {connection_test.get('error')}"
        
        # Get webhook info
        webhook_info = await application.bot.get_webhook_info()
        webhook_status = f"✅ Set to: {webhook_info.url[:50]}..." if webhook_info.url else "❌ Not set"
        
        # Get BTC price
        btc_price = delta_client.get_btc_spot_price()
        price_status = f"✅ ${btc_price:,.2f}" if btc_price else "❌ Failed to fetch"
        
        debug_message = f"""
<b>🔧 System Debug Info</b>

<b>Delta API:</b> {api_status}
<b>BTC Price:</b> {price_status}
<b>Webhook:</b> {webhook_status}
<b>Pending Updates:</b> {webhook_info.pending_update_count}

<b>Last Error:</b> {webhook_info.last_error_message or 'None'}
        """
        
        await update.message.reply_text(debug_message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in debug_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Debug command failed.")

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced positions command with better error handling"""
    try:
        logger.info(f"Positions command from user: {update.effective_user.id}")
        
        # Show loading message
        loading_msg = await update.message.reply_text("🔄 Fetching positions...")
        
        positions = delta_client.get_positions()
        
        if not positions.get('success'):
            error_msg = positions.get('error', 'Unknown error')
            await loading_msg.edit_text(f"❌ {error_msg}")
            return
        
        positions_data = positions.get('result', [])
        
        if not positions_data:
            await loading_msg.edit_text("📊 No open positions found.")
            return
        
        from utils.helpers import format_positions_message
        message = format_positions_message(positions_data)
        await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in positions_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to fetch positions. Use /debug for more info.")

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
            await update.message.reply_text(
                "👋 Hi! Use /start to begin trading, /debug for system status, or /positions to view positions.",
                reply_markup=telegram_client.create_main_menu_keyboard()
            )
            
    except Exception as e:
        logger.error(f"Error in message_handler: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ An error occurred. Please try /start")
        except:
            pass

class WebhookHandler(tornado.web.RequestHandler):
    """Enhanced webhook handler with better error tracking"""
    async def post(self):
        try:
            body = self.request.body.decode('utf-8')
            logger.info(f"📨 Webhook received: {len(body)} bytes from {self.request.remote_ip}")
            
            if not body:
                logger.warning("Empty webhook body")
                self.set_status(400)
                self.write("Bad Request")
                return
            
            update_data = json.loads(body)
            update = Update.de_json(update_data, application.bot)
            
            # Process update with timeout
            try:
                await asyncio.wait_for(
                    application.process_update(update),
                    timeout=25.0  # Telegram expects response within 30s
                )
                logger.info("✅ Update processed successfully")
            except asyncio.TimeoutError:
                logger.error("❌ Update processing timeout")
                self.set_status(200)  # Still return 200 to prevent retries
                self.write("Timeout")
                return
            
            self.set_status(200)
            self.write("OK")
            
        except Exception as e:
            logger.error(f"❌ Webhook error: {e}", exc_info=True)
            self.set_status(200)  # Return 200 to prevent Telegram retries
            self.write("Error")

class HealthHandler(tornado.web.RequestHandler):
    """Enhanced health check"""
    async def get(self):
        try:
            # Quick health checks
            health_data = {
                "status": "healthy",
                "service": "btc-options-bot",
                "webhook_configured": bool(TELEGRAM_BOT_TOKEN)
            }
            
            # Test Delta API if requested
            if self.get_argument('test_api', 'false').lower() == 'true':
                api_test = delta_client.test_connection()
                health_data['delta_api'] = api_test.get('success', False)
            
            self.set_status(200)
            self.set_header("Content-Type", "application/json")
            self.write(health_data)
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self.set_status(503)
            self.write({"status": "unhealthy", "error": str(e)})

def make_app():
    return tornado.web.Application([
        (r"/", tornado.web.RequestHandler),
        (rf"/{TELEGRAM_BOT_TOKEN}", WebhookHandler),
        (r"/health", HealthHandler),
    ])

async def graceful_shutdown(sig, loop):
    """Handle graceful shutdown"""
    logger.info(f"🛑 Received signal {sig}, shutting down gracefully...")
    
    # Cancel webhook health check
    for task in asyncio.all_tasks(loop):
        if 'webhook_check' in str(task):
            task.cancel()
    
    # Stop application
    if application:
        await application.stop()
        await application.shutdown()
    
    # Stop tornado
    tornado.ioloop.IOLoop.current().stop()

def main():
    """Enhanced main function"""
    global application
    
    logger.info("🤖 Starting BTC Options Trading Bot v2.0")
    
    # Initialize application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("debug", debug_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    application.add_error_handler(error_handler)
    
    # Setup signal handlers
    loop = asyncio.get_event_loop()
    for sig in [signal.SIGTERM, signal.SIGINT]:
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(graceful_shutdown(s, loop)))
    
    # Create Tornado app
    app = make_app()
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(PORT, HOST)
    
    try:
        # Initialize services
        loop.run_until_complete(application.initialize())
        loop.run_until_complete(setup_webhook())
        
        # Start periodic webhook health check
        asyncio.create_task(periodic_webhook_check())
        
        logger.info("✅ Bot ready! Use /debug to check system status.")
        
        # Start event loop
        tornado.ioloop.IOLoop.current().start()
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        if application:
            loop.run_until_complete(application.stop())
            loop.run_until_complete(application.shutdown())

if __name__ == '__main__':
    main()
            
