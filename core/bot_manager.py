# core/bot_manager.py
"""
Multi-bot manager for handling multiple Telegram bots with different Delta accounts.
"""

import asyncio
import logging
from typing import Dict
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.request import HTTPXRequest

from config.accounts_config import get_enabled_accounts
from api.delta_client import DeltaClient

logger = logging.getLogger(__name__)

class BotManager:
    """Manage multiple bot instances for different accounts"""
    
    def __init__(self):
        self.bots: Dict[str, Application] = {}
        self.delta_clients: Dict[str, DeltaClient] = {}
        self.accounts = get_enabled_accounts()
        
        logger.info(f"🤖 BotManager initialized with {len(self.accounts)} accounts")
    
    async def initialize_bot(self, account_id: str, config: dict):
        """Initialize a single bot instance with its Delta client"""
        try:
            logger.info(f"🔧 Initializing bot for account: {config['account_name']}")
            
            # Create Delta client for this account
            delta_client = DeltaClient(
                api_key=config['delta_api_key'],
                api_secret=config['delta_api_secret']
            )
            self.delta_clients[account_id] = delta_client
            
            # Configure HTTP request with optimized pool size
            num_accounts = len(self.accounts)
            pool_size = max(5, 15 // num_accounts)  # Distribute pool size
            
            request = HTTPXRequest(
                connection_pool_size=pool_size,
                pool_timeout=20.0,
                read_timeout=20.0,
                write_timeout=20.0,
                connect_timeout=20.0
            )
            
            # Create bot application
            application = (
                Application.builder()
                .token(config['bot_token'])
                .request(request)
                .concurrent_updates(True)
                .build()
            )
            
            # Add handlers with account-specific context
            self._add_handlers(application, delta_client, account_id, config['account_name'])
            
            # Add error handler
            application.add_error_handler(self._create_error_handler(account_id))
            
            # Initialize and start
            await application.initialize()
            await application.start()
            
            self.bots[account_id] = application
            logger.info(f"✅ Bot initialized for {config['account_name']}")
            
            return application
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize bot for {account_id}: {e}", exc_info=True)
            raise
    
    def _add_handlers(self, application: Application, delta_client: DeltaClient, 
                     account_id: str, account_name: str):
        """Add all command and callback handlers to the bot"""
        
        # Import handlers
        from handlers.command_factory import CommandHandlerFactory
        
        # Create handler factory with account-specific context
        handler_factory = CommandHandlerFactory(delta_client, account_id, account_name)
        
        # Add command handlers
        application.add_handler(CommandHandler("start", handler_factory.start_command))
        application.add_handler(CommandHandler("positions", handler_factory.positions_command))
        application.add_handler(CommandHandler("orders", handler_factory.orders_command))
        application.add_handler(CommandHandler("portfolio", handler_factory.portfolio_command))
        application.add_handler(CommandHandler("stoploss", handler_factory.stoploss_command))
        application.add_handler(CommandHandler("cancelstops", handler_factory.cancelstops_command))
        application.add_handler(CommandHandler("debug", handler_factory.debug_command))
        
        # Test commands (optional)
        application.add_handler(CommandHandler("testticker", handler_factory.test_ticker_command))
        application.add_handler(CommandHandler("testformat", handler_factory.test_format_command))
        
        # Callback query handler
        application.add_handler(CallbackQueryHandler(handler_factory.callback_handler))
        
        # Message handler for text inputs
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handler_factory.message_handler)
        )
        
        logger.info(f"✅ Handlers added for {account_name}")
    
    def _create_error_handler(self, account_id: str):
        """Create account-specific error handler"""
        
        async def error_handler(update, context):
            from telegram.error import TimedOut, NetworkError, RetryAfter
            
            logger.error(f"[{account_id}] Error: {context.error}")
            
            if isinstance(context.error, TimedOut):
                logger.warning(f"[{account_id}] ⚠️ Telegram API timeout")
                return
            elif isinstance(context.error, NetworkError):
                logger.warning(f"[{account_id}] ⚠️ Network error")
                return
            elif isinstance(context.error, RetryAfter):
                logger.warning(f"[{account_id}] ⚠️ Rate limited")
                return
            
            # Try to notify user of error
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text(
                        f"❌ An error occurred in {account_id}. Please try again."
                    )
                except Exception as e:
                    logger.error(f"Failed to send error message: {e}")
        
        return error_handler
    
    async def start_all_bots(self):
        """Initialize and start all enabled bots concurrently"""
        if not self.accounts:
            logger.error("❌ No enabled accounts found!")
            return
        
        logger.info(f"🚀 Starting {len(self.accounts)} bot(s)...")
        
        # Create initialization tasks for all bots
        tasks = []
        for account_id, config in self.accounts.items():
            task = self.initialize_bot(account_id, config)
            tasks.append(task)
        
        # Initialize all bots concurrently
        try:
            await asyncio.gather(*tasks)
            logger.info(f"✅ All {len(self.accounts)} bot(s) started successfully!")
            
            # Log account details
            for account_id, config in self.accounts.items():
                logger.info(f"  • {account_id}: {config['account_name']}")
        
        except Exception as e:
            logger.error(f"❌ Error starting bots: {e}")
            raise
    
    async def stop_all_bots(self):
        """Gracefully stop all bots"""
        logger.info("🛑 Stopping all bots...")
        
        for account_id, bot in self.bots.items():
            try:
                await bot.stop()
                await bot.shutdown()
                logger.info(f"✅ Bot {account_id} stopped")
            except Exception as e:
                logger.error(f"Error stopping bot {account_id}: {e}")
        
        logger.info("✅ All bots stopped")
    
    def get_bot(self, account_id: str) -> Application:
        """Get bot application by account ID"""
        return self.bots.get(account_id)
    
    def get_delta_client(self, account_id: str) -> DeltaClient:
        """Get Delta client by account ID"""
        return self.delta_clients.get(account_id)
    
    def get_all_bots(self) -> Dict[str, Application]:
        """Get all bot applications"""
        return self.bots
