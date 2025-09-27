from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from api.delta_client import DeltaClient
from utils.helpers import format_expiry_message

class ExpiryHandler:
    def __init__(self, delta_client: DeltaClient):
        self.delta_client = delta_client
    
    async def show_expiry_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show available expiry dates for selection"""
        query = update.callback_query
        await query.answer()
        
        expiry_dates = self.delta_client.get_available_expiry_dates()
        
        if not expiry_dates:
            await query.edit_message_text("No expiry dates available at the moment.")
            return
        
        keyboard = []
        for date in expiry_dates[:10]:  # Limit to 10 dates
            keyboard.append([InlineKeyboardButton(date, callback_data=f"expiry_{date}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📅 Select an expiry date:",
            reply_markup=reply_markup
        )
    
    async def handle_expiry_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle expiry date selection"""
        query = update.callback_query
        await query.answer()
        
        selected_date = query.data.replace("expiry_", "")
        context.user_data['selected_expiry'] = selected_date
        
        # Get BTC spot price and find ATM strike
        spot_price = self.delta_client.get_btc_spot_price()
        
        if not spot_price:
            await query.edit_message_text("❌ Unable to fetch BTC spot price. Please try again.")
            return
        
        # Get option chain for selected expiry
        option_chain = self.delta_client.get_option_chain('BTC', selected_date)
        
        if not option_chain.get('success'):
            await query.edit_message_text("❌ Unable to fetch option chain. Please try again.")
            return
        
        # Find ATM strike price
        atm_strike = self._find_atm_strike(option_chain['result'], spot_price)
        context.user_data['atm_strike'] = atm_strike
        context.user_data['spot_price'] = spot_price
        
        # Get ATM CE and PE details
        ce_option, pe_option = self._get_atm_options(option_chain['result'], atm_strike)
        context.user_data['ce_option'] = ce_option
        context.user_data['pe_option'] = pe_option
        
        message = format_expiry_message(selected_date, spot_price, atm_strike, ce_option, pe_option)
        
        await query.edit_message_text(
            message,
            parse_mode='HTML'
        )
        
        # Ask for lot size
        await query.message.reply_text("💰 Enter the lot size (number of contracts):")
        context.user_data['waiting_for_lot_size'] = True
    
    def _find_atm_strike(self, options_data: list, spot_price: float) -> float:
        """Find the ATM (At-The-Money) strike price"""
        strikes = []
        for option in options_data:
            if option.get('strike_price'):
                strikes.append(float(option['strike_price']))
        
        if not strikes:
            return round(spot_price, -2)  # Round to nearest 100
        
        # Find closest strike to spot price
        closest_strike = min(strikes, key=lambda x: abs(x - spot_price))
        return closest_strike
    
    def _get_atm_options(self, options_data: list, atm_strike: float) -> tuple:
        """Get ATM CE and PE option details"""
        ce_option = None
        pe_option = None
        
        for option in options_data:
            if float(option.get('strike_price', 0)) == atm_strike:
                if option.get('contract_type') == 'call_options':
                    ce_option = option
                elif option.get('contract_type') == 'put_options':
                    pe_option = option
        
        return ce_option, pe_option
        
