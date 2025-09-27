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
import threading
import time

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
webhook_monitor_active = False

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
    """Enhanced webhook setup"""
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
        # Clear existing webhook
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("🧹 Cleared existing webhook")
        
        # Wait before setting new webhook
        await asyncio.sleep(2)
        
        # Set new webhook
        success = await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=['message', 'callback_query'],
            drop_pending_updates=True,
            max_connections=5  # Reduce to prevent overload
        )
        
        if success:
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

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced positions command with multiple data sources"""
    try:
        logger.info(f"Positions command from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Fetching positions and portfolio data...")
        
        # Try to get positions
        positions = delta_client.get_positions()
        
        # Also try to get portfolio summary for additional context
        portfolio = delta_client.get_portfolio_summary()
        
        if not positions.get('success'):
            error_msg = positions.get('error', 'Unknown error')
            
            # Provide helpful error messages
            if 'bad_schema' in str(error_msg):
                error_text = "❌ API schema error. This might be due to:\n\n"
                error_text += "• Missing required permissions (enable 'Read Data' on your API key)\n"
                error_text += "• API key configuration issues\n"
                error_text += "• Try refreshing your API credentials\n\n"
                error_text += f"Technical details: {error_msg}"
            else:
                error_text = f"❌ {error_msg}"
            
            await loading_msg.edit_text(error_text)
            return
        
        positions_data = positions.get('result', [])
        
        # Build response message
        if not positions_data:
            message = "📊 <b>No Open Positions Found</b>\n\n"
            
            # Try to show portfolio info if available
            if portfolio.get('success'):
                balances = portfolio.get('result', [])
                if balances:
                    message += "<b>💰 Wallet Balances:</b>\n"
                    for balance in balances[:5]:  # Show first 5 balances
                        asset = balance.get('asset_symbol', 'Unknown')
                        available = balance.get('available_balance', 0)
                        if float(available) > 0:
                            message += f"• {asset}: {available}\n"
                    message += "\n"
            
            message += "<i>Start trading by selecting an expiry date!</i>"
            
            await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
            return
        
        # Format positions message
        from utils.helpers import format_positions_message
        message = format_positions_message(positions_data)
        
        # Add portfolio summary if available
        if portfolio.get('success'):
            balances = portfolio.get('result', [])
            total_balance = sum(float(b.get('available_balance', 0)) for b in balances)
            if total_balance > 0:
                message += f"\n<b>💰 Total Portfolio Value:</b> ₹{total_balance:,.2f}"
        
        await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in positions_command: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Failed to fetch positions. Possible issues:\n\n"
            "• API credentials need 'Read Data' permission\n"
            "• Network connectivity issues\n"
            "• Rate limiting\n\n"
            "Use /debug for more information."
        )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
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
    """Handle incoming webhook updates"""
    async def post(self):
        try:
            body = self.request.body.decode('utf-8')
            logger.info(f"📨 Webhook: {len(body)} bytes from {self.request.remote_ip}")
            
            if not body:
                self.set_status(400)
                self.write("Bad Request")
                return
            
            update_data = json.loads(body)
            update = Update.de_json(update_data, application.bot)
            
            # Process update with timeout
            try:
                await asyncio.wait_for(
                    application.process_update(update),
                    timeout=25.0
                )
                logger.info("✅ Update processed")
            except asyncio.TimeoutError:
                logger.error("❌ Update timeout")
            
            self.set_status(200)
            self.write("OK")
            
        except Exception as e:
            logger.error(f"❌ Webhook error: {e}")
            self.set_status(200)  # Return 200 to prevent retries
            self.write("Error")

class HealthHandler(tornado.web.RequestHandler):
    """Health check endpoint"""
    def get(self):
        try:
            health_data = {
                "status": "healthy",
                "service": "btc-options-bot",
                "version": "2.0"
            }
            
            self.set_status(200)
            self.set_header("Content-Type", "application/json")
            self.write(health_data)
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self.set_status(503)
            self.write({"status": "unhealthy"})

class RootHandler(tornado.web.RequestHandler):
    """Root handler"""
    def get(self):
        self.set_status(200)
        self.write({
            "service": "BTC Options Trading Bot",
            "status": "running",
            "version": "2.0"
        })

def make_app():
    """Create Tornado application"""
    return tornado.web.Application([
        (r"/", RootHandler),
        (rf"/{TELEGRAM_BOT_TOKEN}", WebhookHandler),
        (r"/health", HealthHandler),
    ])

async def initialize_bot():
    """Initialize the bot application"""
    global application
    
    try:
        logger.info("🚀 Initializing bot application...")
        
        # Create application
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("debug", debug_command))
        application.add_handler(CommandHandler("positions", positions_command))
        application.add_handler(CallbackQueryHandler(callback_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        application.add_error_handler(error_handler)
        
        # Initialize application
        await application.initialize()
        logger.info("✅ Bot application initialized")
        
        # Setup webhook
        webhook_success = await setup_webhook()
        if webhook_success:
            logger.info("✅ Webhook configured successfully")
        else:
            logger.warning("⚠️ Webhook setup failed, but continuing...")
        
        # Test bot
        me = await application.bot.get_me()
        logger.info(f"✅ Bot ready: @{me.username} ({me.first_name})")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Bot initialization failed: {e}")
        return False

def main():
    """Main function - simplified event loop handling"""
    global webhook_monitor_active
    
    logger.info("🤖 Starting BTC Options Trading Bot v2.0")
    
    try:
        # Initialize bot with new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Initialize bot application
        initialization_success = loop.run_until_complete(initialize_bot())
        
        if not initialization_success:
            logger.error("❌ Failed to initialize bot")
            return
        
        # Start webhook health monitor in background thread
        monitor_thread = threading.Thread(target=webhook_health_monitor, daemon=True)
        monitor_thread.start()
        logger.info("✅ Webhook monitor started")
        
        # Create and start Tornado server
        app = make_app()
        http_server = tornado.httpserver.HTTPServer(app)
        http_server.listen(PORT, HOST)
        
        logger.info(f"🌐 Server listening on {HOST}:{PORT}")
        logger.info("✅ Bot ready! Send /start to test.")
        
        # Start Tornado event loop
        tornado.ioloop.IOLoop.current().start()
        
    except KeyboardInterrupt:
        logger.info("🛑 Received shutdown signal")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        # Cleanup
        webhook_monitor_active = False
        
        if application:
            try:
                # Use the current event loop for cleanup
                current_loop = asyncio.get_event_loop()
                if not current_loop.is_closed():
                    current_loop.run_until_complete(application.stop())
                    current_loop.run_until_complete(application.shutdown())
                    logger.info("✅ Bot application stopped")
            except Exception as e:
                logger.error(f"❌ Cleanup error: {e}")

if __name__ == '__main__':
    main()
