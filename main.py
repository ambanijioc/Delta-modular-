import asyncio
import logging
from aiohttp import web
from telegram_bot import TelegramOptionsBot
from config import HOST, PORT

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def health_check(request):
    """Health check endpoint for Render.com"""
    return web.Response(text="BTC Options Bot is running!")

async def main():
    """Main function to run the bot"""
    bot = TelegramOptionsBot()
    
    # Create web server for Render.com
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    
    logger.info(f"Starting web server on {HOST}:{PORT}")
    await site.start()
    
    logger.info("Starting Telegram bot...")
    await bot.run_polling()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
      
