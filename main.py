import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from config.config import TELEGRAM_BOT_TOKEN, HOST, PORT
from api.delta_client import DeltaClient
from api.telegram_client import TelegramClient
from handlers.expiry_handler import ExpiryHandler
from handlers.options_handler import OptionsHandler
from handlers.position_handler import PositionHandler
from utils.constants import START_MESSAGE, HELP_MESSAGE

# Initialize clients and handlers
delta_client = DeltaClient()
telegram_client = TelegramClient(TELEGRAM_BOT_TOKEN)
expiry_handler = ExpiryHandler(delta_client)
options_handler = OptionsHandler(delta_client)
position_handler = PositionHandler(delta_client)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    reply_markup = telegram_client.create_main_menu_keyboard()
    await update.message.reply_text(
        START_MESSAGE,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    await update.message.reply_text(
        HELP_MESSAGE,
        parse_mode=ParseMode.HTML
    )

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /positions command"""
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
    if context.user_data.get('waiting_for_lot_size'):
        await options_handler.handle_lot_size_input(update, context)

def main():
    """Main function to run the bot"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    # Set up webhook for Render.com deployment
    print(f"Starting bot on {HOST}:{PORT}")
    application.run_webhook(
        listen=HOST,
        port=PORT,
        webhook_url=f"https://your-app-name.onrender.com/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == '__main__':
    main()
    
