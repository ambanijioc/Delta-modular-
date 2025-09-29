from typing import Dict, List  # Add List import here
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from api.delta_client import DeltaClient
from utils.helpers import format_expiry_message

class ExpiryHandler:
    def __init__(self, delta_client: DeltaClient):
        self.delta_client = delta_client
    
    async def show_expiry_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show available expiry dates in ascending order by days to expiry"""
        try:
            query = update.callback_query
            await query.answer()
        
            logger.info("📅 Fetching available expiry dates...")
        
            # Get BTC options products
            products = self.delta_client.get_products('call_options,put_options')
        
            if not products.get('success'):
                await query.edit_message_text("❌ Unable to fetch expiry dates. Please try again.")
                return
        
            products_list = products.get('result', [])
        
            # Filter for BTC options only
            btc_products = [p for p in products_list if p.get('underlying_asset', {}).get('symbol') == 'BTC']
        
            if not btc_products:
                await query.edit_message_text("📅 No BTC options available.")
                return
        
            # Extract and sort expiry dates
            expiry_data = self._extract_and_sort_expiries(btc_products)
        
            if not expiry_data:
                await query.edit_message_text("📅 No valid expiry dates found.")
                return
        
            # Create message and keyboard
            message = self._create_expiry_message(expiry_data)
            reply_markup = self._create_expiry_keyboard(expiry_data)
        
            await query.edit_message_text(
                message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        
        except Exception as e:
            logger.error(f"Error in show_expiry_selection: {e}", exc_info=True)
            await query.edit_message_text("❌ An error occurred fetching expiry dates.")

    def _extract_and_sort_expiries(self, btc_products: List[Dict]) -> List[Dict]:
        """Extract expiry dates and sort by days to expiry (ascending)"""
        try:
            import datetime
        
            expiry_dict = {}
            current_date = datetime.datetime.now().date()
        
            for product in btc_products:
                # Get expiry date string (format: "2025-09-29" or similar)
                expiry_date_str = product.get('settlement_time', '')
                if not expiry_date_str:
                    continue
            
                try:
                    # Parse the expiry date (assuming ISO format YYYY-MM-DD or datetime)
                    if 'T' in expiry_date_str:
                        # Full datetime format
                        expiry_date = datetime.datetime.fromisoformat(expiry_date_str.replace('Z', '+00:00')).date()
                    else:
                        # Date only format
                        expiry_date = datetime.datetime.fromisoformat(expiry_date_str).date()
                
                    # Skip expired options
                    if expiry_date <= current_date:
                        continue
                
                    # Calculate days to expiry
                    days_to_expiry = (expiry_date - current_date).days
                
                    # Create expiry key
                    expiry_key = expiry_date.strftime('%Y-%m-%d')
                
                    if expiry_key not in expiry_dict:
                        expiry_dict[expiry_key] = {
                            'date': expiry_date,
                            'days_to_expiry': days_to_expiry,
                            'display_date': expiry_date.strftime('%d %b %Y'),
                            'short_date': expiry_date.strftime('%d/%m'),
                            'count': 0
                        }
                
                    # Count options for this expiry
                    expiry_dict[expiry_key]['count'] += 1
                
                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not parse expiry date '{expiry_date_str}': {e}")
                    continue
        
            # Convert to list and sort by days to expiry (ascending)
            expiry_list = list(expiry_dict.values())
            expiry_list.sort(key=lambda x: x['days_to_expiry'])
        
            logger.info(f"📊 Found {len(expiry_list)} expiry dates, sorted by nearest first")
        
            return expiry_list
        
        except Exception as e:
            logger.error(f"Error extracting and sorting expiries: {e}")
            return []

    def _create_expiry_message(self, expiry_data: List[Dict]) -> str:
        """Create expiry selection message with days to expiry"""
        message = """<b>📅 Select Options Expiry Date</b>

    <b>Available Expiry Dates (Nearest First):</b>

    """
    
        for i, expiry in enumerate(expiry_data[:8], 1):  # Show first 8 expiries
            days = expiry['days_to_expiry']
            display_date = expiry['display_date']
            count = expiry['count']
        
            # Add urgency indicators
            if days <= 1:
                urgency = "🔴 EXPIRES TODAY/TOMORROW"
            elif days <= 3:
                urgency = "🟠 Expires Very Soon"
            elif days <= 7:
                urgency = "🟡 Expires This Week"
            elif days <= 14:
                urgency = "🟢 Expires Soon"
            else:
                urgency = "🔵 Further Out"
        
            message += f"<b>{i}. {display_date}</b>\n"
            message += f"   📊 {count} options | ⏱ {days} day{'s' if days != 1 else ''} remaining\n"
            message += f"   {urgency}\n\n"
    
        if len(expiry_data) > 8:
            message += f"<i>... and {len(expiry_data) - 8} more expiry dates</i>\n\n"
    
        message += "<i>Select an expiry date to view available strikes:</i>"
    
        return message

    def _create_expiry_keyboard(self, expiry_data: List[Dict]) -> InlineKeyboardMarkup:
        """Create expiry keyboard with sorted dates"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
        keyboard = []
    
        # Create buttons for each expiry (limit to 10 for usability)
        for expiry in expiry_data[:10]:
            expiry_date = expiry['date']
            short_date = expiry['short_date']
            days = expiry['days_to_expiry']
            count = expiry['count']
        
            # Create button text with days info
            if days <= 1:
                button_text = f"🔴 {short_date} (TODAY/TMR)"
            elif days <= 7:
                button_text = f"🟡 {short_date} ({days}d)"
            else:
                button_text = f"🟢 {short_date} ({days} days)"
        
            # Use ISO date format for callback data
            callback_data = f"expiry_{expiry_date.strftime('%Y-%m-%d')}"
        
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
        # Add back button
        keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main")])
    
        return InlineKeyboardMarkup(keyboard)
    
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
        
