import asyncio
import logging
from typing import Dict
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.request import HTTPXRequest
from config.accounts_config import ACCOUNTS
from api.delta_client import DeltaClient

logger = logging.getLogger(__name__)

class BotInstance:
    """Represents a single bot instance with its associated Delta client"""
    
    def __init__(self, account_id: str, config: dict):
        self.account_id = account_id
        self.config = config
        self.application = None
        self.delta_client = None
        self.account_name = config.get('account_name', account_id)
    
    async def initialize(self):
        """Initialize bot and Delta client"""
        try:
            logger.info(f"🔄 Initializing bot for {self.account_name}...")
            
            # Create Delta client with account-specific credentials
            self.delta_client = DeltaClient(
                api_key=self.config['delta_api_key'],
                api_secret=self.config['delta_api_secret']
            )
            
            # Create bot application with optimized settings
            request = HTTPXRequest(
                connection_pool_size=8,  # Reduced for multiple bots
                pool_timeout=20.0,
                read_timeout=20.0,
                write_timeout=20.0,
                connect_timeout=20.0
            )
            
            self.application = (
                Application.builder()
                .token(self.config['bot_token'])
                .request(request)
                .concurrent_updates(True)
                .build()
            )
            
            # Add handlers
            self._add_handlers()
            
            # Initialize and start
            await self.application.initialize()
            await self.application.start()
            
            logger.info(f"✅ Bot initialized for {self.account_name}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize bot for {self.account_name}: {e}")
            raise
    
    def _add_handlers(self):
        """Add all command and callback handlers"""
        # Import your existing handler functions
        from main import (
            start_command, positions_command, orders_command, 
            portfolio_command, callback_handler, message_handler,
            error_handler
        )
        
        # Create wrapper functions that inject delta_client
        def create_command_wrapper(handler_func):
            async def wrapper(update, context):
                # Inject delta_client into context for this account
                context.bot_data['delta_client'] = self.delta_client
                context.bot_data['account_name'] = self.account_name
                context.bot_data['account_id'] = self.account_id
                return await handler_func(update, context)
            return wrapper
        
        # Add command handlers
        self.application.add_handler(CommandHandler("start", create_command_wrapper(start_command)))
        self.application.add_handler(CommandHandler("positions", create_command_wrapper(positions_command)))
        self.application.add_handler(CommandHandler("orders", create_command_wrapper(orders_command)))
        self.application.add_handler(CommandHandler("portfolio", create_command_wrapper(portfolio_command)))
        
        # Add callback and message handlers
        self.application.add_handler(CallbackQueryHandler(create_command_wrapper(callback_handler)))
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            create_command_wrapper(message_handler)
        ))
        
        # Add error handler
        self.application.add_error_handler(error_handler)
    
    async def stop(self):
        """Stop bot gracefully"""
        if self.application:
            await self.application.stop()
            await self.application.shutdown()
            logger.info(f"✅ Bot stopped for {self.account_name}")


class BotManager:
    """Manages multiple bot instances"""
    
    def __init__(self):
        self.bots: Dict[str, BotInstance] = {}
    
    async def start_all(self):
        """Start all configured bots"""
        try:
            logger.info(f"🚀 Starting {len(ACCOUNTS)} bot(s)...")
            
            # Create bot instances
            for account_id, config in ACCOUNTS.items():
                bot_instance = BotInstance(account_id, config)
                self.bots[account_id] = bot_instance
            
            # Initialize all bots concurrently
            init_tasks = [bot.initialize() for bot in self.bots.values()]
            await asyncio.gather(*init_tasks)
            
            logger.info(f"✅ All {len(self.bots)} bot(s) running successfully!")
            
            # Log which accounts are active
            for account_id, bot in self.bots.items():
                logger.info(f"  • {bot.account_name} (ID: {account_id})")
            
        except Exception as e:
            logger.error(f"❌ Error starting bots: {e}")
            raise
    
    async def stop_all(self):
        """Stop all bots gracefully"""
        logger.info("🛑 Stopping all bots...")
        
        stop_tasks = [bot.stop() for bot in self.bots.values()]
        await asyncio.gather(*stop_tasks, return_exceptions=True)
        
        logger.info("✅ All bots stopped")
    
    def get_bot(self, account_id: str) -> BotInstance:
        """Get specific bot instance"""
        return self.bots.get(account_id)
      
