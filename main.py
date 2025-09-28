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
from handlers.stoploss_handler import StopLossHandler

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
    """Enhanced positions command"""
    try:
        logger.info(f"Positions command from user: {update.effective_user.id}")
        
        loading_msg = await update.message.reply_text("🔄 Fetching positions...")
        
        positions = delta_client.get_positions()
        portfolio = delta_client.get_portfolio_summary()
        
        if not positions.get('success'):
            error_msg = positions.get('error', 'Unknown error')
            if 'bad_schema' in str(error_msg):
                error_text = "❌ API schema error. Check API permissions."
            else:
                error_text = f"❌ {error_msg}"
            
            await loading_msg.edit_text(error_text)
            return
        
        positions_data = positions.get('result', [])
        
        if not positions_data:
            message = "📊 <b>No Open Positions Found</b>\n\n"
            
            if portfolio.get('success'):
                balances = portfolio.get('result', [])
                if balances:
                    message += "<b>💰 Wallet Balances:</b>\n"
                    for balance in balances[:5]:
                        asset = balance.get('asset_symbol', 'Unknown')
                        available = balance.get('available_balance', 0)
                        if float(available) > 0:
                            message += f"• {asset}: {available}\n"
                    message += "\n"
            
            message += "<i>Start trading by selecting an expiry date!</i>"
            await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
            return
        
        from utils.helpers import format_positions_message
        message = format_positions_message(positions_data)
        
        if portfolio.get('success'):
            balances = portfolio.get('result', [])
            total_balance = sum(float(b.get('available_balance', 0)) for b in balances)
            if total_balance > 0:
                message += f"\n<b>💰 Total Portfolio Value:</b> ₹{total_balance:,.2f}"
        
        await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error in positions_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to fetch positions. Use /debug for more info.")

async def stoploss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stoploss command"""
    try:
        logger.info(f"Stop-loss command from user: {update.effective_user.id}")
        
        # Check if order ID is provided
        if context.args:
            order_id = context.args[0]
            await stoploss_handler.show_stoploss_selection(update, context, order_id)
        else:
            await update.message.reply_text(
                "📋 <b>Stop-Loss Command Usage:</b>\n\n"
                "/stoploss [order_id] - Add stop-loss to specific order\n\n"
                "<b>Example:</b> /stoploss 12345\n\n"
                "Get order IDs from trade confirmations or /positions",
                parse_mode=ParseMode.HTML
            )
            
    except Exception as e:
        logger.error(f"Error in stoploss_command: {e}", exc_info=True)
        await update.message.reply_text("❌ Failed to process stop-loss command.")

async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show portfolio summary"""
    try:
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

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced callback handler with stop-loss support"""
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
        elif data.startswith("add_stoploss_"):
            order_id = data.replace("add_stoploss_", "")
            await stoploss_handler.show_stoploss_selection(update, context, order_id)
        elif data.startswith("sl_type_"):
            await stoploss_handler.handle_stoploss_type_selection(update, context)
        elif data.startswith("sl_limit_"):
            await stoploss_handler.handle_limit_price_selection(update, context)
        elif data == "sl_cancel":
            await query.edit_message_text("❌ Stop-loss setup cancelled.")
        else:
            await query.answer("Unknown option")
            
    except Exception as e:
        logger.error(f"Error in callback_handler: {e}", exc_info=True)
        try:
            await update.callback_query.answer("❌ An error occurred")
        except:
            pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced message handler with stop-loss inputs"""
    try:
        logger.info(f"Text message from user {update.effective_user.id}: {update.message.text}")
        
        if context.user_data.get('waiting_for_lot_size'):
            await options_handler.handle_lot_size_input(update, context)
        elif context.user_data.get('waiting_for_trigger_price'):
            await stoploss_handler.handle_trigger_price_input(update, context)
        elif context.user_data.get('waiting_for_limit_price'):
            await stoploss_handler.handle_limit_price_input(update, context)
        elif context.user_data.get('waiting_for_trail_amount'):
            await stoploss_handler.handle_trail_amount_input(update, context)
        else:
            await update.message.reply_text(
                "👋 Hi! Available commands:\n"
                "/start - Main menu\n"
                "/debug - System status\n"
                "/webhook - Webhook status\n"
                "/positions - View positions\n"
                "/portfolio - Portfolio summary\n"
                "/stoploss [order_id] - Add stop-loss protection",
                reply_markup=telegram_client.create_main_menu_keyboard()
            )
            
    except Exception as e:
        logger.error(f"Error in message_handler: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ An error occurred. Please try /start")
        except:
            pass

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
        
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Add all handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("debug", debug_command))
        application.add_handler(CommandHandler("webhook", webhook_command))
        application.add_handler(CommandHandler("positions", positions_command))
        application.add_handler(CommandHandler("portfolio", portfolio_command))
        application.add_handler(CallbackQueryHandler(callback_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        application.add_error_handler(error_handler)
        
        logger.info("✅ All handlers registered")
        
        await application.initialize()
        logger.info("✅ Bot application initialized")
        
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
