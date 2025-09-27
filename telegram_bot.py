import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from options_handler import OptionsHandler
from config import TELEGRAM_BOT_TOKEN

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramOptionsBot:
    def __init__(self):
        self.options_handler = OptionsHandler()
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup command and callback handlers"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help))
        self.application.add_handler(CommandHandler("expiry", self.show_expiry_dates))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        welcome_text = (
            "🚀 Welcome to BTC Options Trading Bot!\n\n"
            "This bot helps you trade BTC options on Delta Exchange India.\n\n"
            "Commands:\n"
            "/expiry - Select expiry date for BTC options\n"
            "/help - Show this help message\n\n"
            "Click /expiry to start trading!"
        )
        await update.message.reply_text(welcome_text)
    
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command handler"""
        help_text = (
            "📖 BTC Options Trading Bot Help\n\n"
            "Steps to trade:\n"
            "1. Use /expiry to select an expiry date\n"
            "2. Bot will show ATM Call and Put options\n"
            "3. Confirm to execute both CE and PE orders\n\n"
            "Features:\n"
            "• Automatic ATM strike selection\n"
            "• Real-time BTC spot price\n"
            "• Market order execution\n"
            "• 1 lot each for CE and PE\n\n"
            "Note: Ensure your Delta Exchange account has sufficient balance."
        )
        await update.message.reply_text(help_text)
    
    async def show_expiry_dates(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show available expiry dates"""
        await update.message.reply_text("📅 Fetching available expiry dates...")
        
        expiry_dates = await self.options_handler.get_expiry_dates()
        
        if not expiry_dates:
            await update.message.reply_text("❌ No expiry dates available. Please try again later.")
            return
        
        # Create inline keyboard with expiry dates
        keyboard = []
        for i, date in enumerate(expiry_dates[:10]):  # Limit to 10 dates
            keyboard.append([InlineKeyboardButton(f"📅 {date}", callback_data=f"expiry_{date}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "📅 Select BTC Options Expiry Date:",
            reply_markup=reply_markup
        )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries from inline keyboards"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith("expiry_"):
            expiry_date = data.replace("expiry_", "")
            await self.handle_expiry_selection(query, expiry_date)
        elif data == "confirm_trade":
            await self.handle_trade_confirmation(query)
        elif data == "cancel_trade":
            await query.edit_message_text("❌ Trade cancelled.")
    
    async def handle_expiry_selection(self, query, expiry_date):
        """Handle expiry date selection"""
        await query.edit_message_text(f"🔄 Processing expiry date: {expiry_date}...")
        
        options_data = await self.options_handler.set_expiry_and_get_atm_options(expiry_date)
        
        if not options_data:
            await query.edit_message_text("❌ Failed to fetch options data. Please try again.")
            return
        
        spot_price = options_data['spot_price']
        atm_call = options_data['atm_call']
        atm_put = options_data['atm_put']
        
        if not atm_call or not atm_put:
            await query.edit_message_text("❌ ATM options not found for this expiry date.")
            return
        
        # Format option details
        message = (
            f"📊 BTC Options Details\n\n"
            f"📅 Expiry: {expiry_date}\n"
            f"💰 BTC Spot Price: ${spot_price:,.2f}\n\n"
            f"📈 ATM Call Option (CE):\n"
            f"   Symbol: {atm_call['symbol']}\n"
            f"   Strike: ${atm_call['strike_price']:,.0f}\n"
            f"   Mark Price: ${float(atm_call['mark_price']):,.2f}\n\n"
            f"📉 ATM Put Option (PE):\n"
            f"   Symbol: {atm_put['symbol']}\n"
            f"   Strike: ${atm_put['strike_price']:,.0f}\n"
            f"   Mark Price: ${float(atm_put['mark_price']):,.2f}\n\n"
            f"🔥 Ready to execute 1 lot each at market price!"
        )
        
        # Confirmation buttons
        keyboard = [
            [InlineKeyboardButton("✅ Confirm Trade", callback_data="confirm_trade")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_trade")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup)
    
    async def handle_trade_confirmation(self, query):
        """Handle trade confirmation and execution"""
        await query.edit_message_text("🔄 Executing orders...")
        
        result = await self.options_handler.execute_straddle_order()
        
        if result['success']:
            call_order = result['call_order']
            put_order = result['put_order']
            
            message = (
                f"✅ Orders Executed Successfully!\n\n"
                f"📈 Call Order:\n"
                f"   Order ID: {call_order.get('id', 'N/A')}\n"
                f"   Size: {call_order.get('size', 'N/A')}\n"
                f"   Status: {call_order.get('state', 'N/A')}\n\n"
                f"📉 Put Order:\n"
                f"   Order ID: {put_order.get('id', 'N/A')}\n"
                f"   Size: {put_order.get('size', 'N/A')}\n"
                f"   Status: {put_order.get('state', 'N/A')}\n\n"
                f"🎉 BTC Straddle position created!"
            )
        else:
            message = (
                f"❌ Order Execution Failed!\n\n"
                f"Errors:\n" + 
                "\n".join(result['errors'])
            )
        
        await query.edit_message_text(message)
    
    async def run_polling(self):
        """Run the bot in polling mode"""
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        # Keep the bot running
        import asyncio
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
          
