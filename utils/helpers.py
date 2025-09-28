from typing import Dict, List, Optional

def format_expiry_message(expiry_date: str, spot_price: float, atm_strike: float, 
                         ce_option: Optional[Dict], pe_option: Optional[Dict]) -> str:
    """Format expiry selection message with option details"""
    message = f"<b>📅 Selected Expiry:</b> {expiry_date}\n"
    message += f"<b>💰 BTC Spot Price:</b> ${spot_price:,.2f}\n"
    message += f"<b>🎯 ATM Strike:</b> ${atm_strike:,.0f}\n\n"
    
    if ce_option:
        message += f"<b>📈 Call Option (CE):</b>\n"
        message += f"   Symbol: {ce_option.get('symbol', 'N/A')}\n"
        message += f"   Mark Price: ${ce_option.get('mark_price', '0'):>8}\n"
        message += f"   Bid: ${ce_option.get('quotes', {}).get('best_bid', '0'):>8}\n"
        message += f"   Ask: ${ce_option.get('quotes', {}).get('best_ask', '0'):>8}\n\n"
    
    if pe_option:
        message += f"<b>📉 Put Option (PE):</b>\n"
        message += f"   Symbol: {pe_option.get('symbol', 'N/A')}\n"
        message += f"   Mark Price: ${pe_option.get('mark_price', '0'):>8}\n"
        message += f"   Bid: ${pe_option.get('quotes', {}).get('best_bid', '0'):>8}\n"
        message += f"   Ask: ${pe_option.get('quotes', {}).get('best_ask', '0'):>8}\n\n"
    
    return message

def format_positions_message(positions: List[Dict]) -> str:
    """Enhanced format positions display message"""
    message = "<b>📊 Open Positions</b>\n\n"
    
    if not positions:
        return "<b>📊 No Open Positions</b>\n\nYou currently have no active positions."
    
    for i, position in enumerate(positions[:10], 1):  # Limit to 10 positions
        # Enhanced symbol extraction
        product = position.get('product', {})
        symbol = product.get('symbol', 'Unknown')
        
        # Try alternative symbol extraction if still unknown
        if symbol == 'Unknown' or not symbol:
            # Try to build symbol from components
            underlying = product.get('underlying_asset', {})
            if isinstance(underlying, dict):
                base_symbol = underlying.get('symbol', 'BTC')
            else:
                base_symbol = 'BTC'
            
            contract_type = product.get('contract_type', '')
            strike_price = product.get('strike_price', '')
            
            if contract_type and 'option' in contract_type:
                option_type = 'CE' if 'call' in contract_type else 'PE'
                if strike_price:
                    symbol = f"{base_symbol} {strike_price} {option_type}"
                else:
                    symbol = f"{base_symbol} {option_type}"
            else:
                symbol = f"{base_symbol} Future"
        
        # Position details
        size = float(position.get('size', 0))
        entry_price = float(position.get('entry_price', 0))
        mark_price = float(position.get('mark_price', 0))
        pnl = float(position.get('unrealized_pnl', 0))
        
        # Determine position type
        if size > 0:
            side = "LONG"
            side_emoji = "📈"
        elif size < 0:
            side = "SHORT"
            side_emoji = "📉"
        else:
            continue  # Skip zero positions
        
        # PnL formatting
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        pnl_text = f"{pnl_emoji} ${pnl:,.2f}"
        
        # Price formatting
        entry_text = f"${entry_price:,.4f}" if entry_price > 0 else "N/A"
        mark_text = f"${mark_price:,.4f}" if mark_price > 0 else "N/A"
        
        message += f"<b>{i}. {symbol}</b> {side_emoji}\n"
        message += f"   Side: {side}\n"
        message += f"   Size: {abs(size):,.0f} contracts\n"
        message += f"   Entry: {entry_text}\n"
        message += f"   Mark: {mark_text}\n"
        message += f"   PnL: {pnl_text}\n"
        
        # Add product ID for debugging if available
        product_id = product.get('id')
        if product_id:
            message += f"   ID: {product_id}\n"
        
        message += "\n"
    
    return message

def format_position_summary(position: Dict) -> str:
    """Format single position for selection display"""
    product = position.get('product', {})
    symbol = product.get('symbol', 'Unknown')
    
    # Enhanced symbol extraction for display
    if symbol == 'Unknown' or not symbol:
        underlying = product.get('underlying_asset', {})
        base_symbol = underlying.get('symbol', 'BTC') if isinstance(underlying, dict) else 'BTC'
        contract_type = product.get('contract_type', '')
        strike_price = product.get('strike_price', '')
        
        if contract_type and 'option' in contract_type:
            option_type = 'CE' if 'call' in contract_type else 'PE'
            symbol = f"{base_symbol} {strike_price} {option_type}" if strike_price else f"{base_symbol} {option_type}"
        else:
            symbol = f"{base_symbol} Future"
    
    size = float(position.get('size', 0))
    pnl = float(position.get('unrealized_pnl', 0))
    
    side = "LONG" if size > 0 else "SHORT"
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    
    return f"{symbol} {side} ({pnl_emoji}${pnl:,.2f})"

def format_enhanced_positions_message(positions: List[Dict]) -> str:
    """Enhanced format positions with proper symbols from force enhancement"""
    message = "<b>📊 Open Positions</b>\n\n"
    
    if not positions:
        return "<b>📊 No Open Positions</b>\n\nYou currently have no active positions."
    
    for i, position in enumerate(positions[:10], 1):  # Limit to 10 positions
        # Get enhanced product data (should be populated by force_enhance_positions)
        product = position.get('product', {})
        
        # Use the actual symbol from enhanced data
        symbol = product.get('symbol', 'Unknown')
        
        # Format the symbol for better display
        display_symbol = format_option_symbol_for_display(symbol)
        
        # Position details
        size = float(position.get('size', 0))
        entry_price = float(position.get('entry_price', 0))
        mark_price = float(position.get('mark_price', 0))
        pnl = float(position.get('unrealized_pnl', 0))
        
        # Determine position type and emoji
        if size > 0:
            side = "LONG"
            side_emoji = "📈"
        elif size < 0:
            side = "SHORT"
            side_emoji = "📉"
        else:
            continue  # Skip zero positions
        
        # PnL formatting
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        pnl_text = f"{pnl_emoji} ${pnl:,.2f}"
        
        # Price formatting
        entry_text = f"${entry_price:,.4f}" if entry_price > 0 else "N/A"
        mark_text = f"${mark_price:,.4f}" if mark_price > 0 else "N/A"
        
        message += f"<b>{i}. {display_symbol}</b> {side_emoji}\n"
        message += f"   Side: {side}\n"
        message += f"   Size: {abs(size):,.0f} contracts\n"
        message += f"   Entry: {entry_text}\n"
        message += f"   Mark: {mark_text}\n"
        message += f"   PnL: {pnl_text}\n"
        
        message += "\n"
    
    return message

def format_option_symbol_for_display(symbol: str) -> str:
    """Format option symbol for better readability"""
    if not symbol or symbol == 'Unknown':
        return 'Unknown Position'
    
    # Handle Delta Exchange format: C-BTC-112000-290925
    if '-' in symbol:
        parts = symbol.split('-')
        if len(parts) >= 4:
            option_type = parts[0]  # C or P
            underlying = parts[1]   # BTC
            strike = parts[2]       # 112000
            expiry = parts[3]       # 290925
            
            # Convert option type
            if option_type == 'C':
                option_name = 'CE'
            elif option_type == 'P':
                option_name = 'PE'
            else:
                option_name = option_type
            
            # Format expiry date if needed
            if len(expiry) == 6:  # DDMMYY format
                day = expiry[:2]
                month = expiry[2:4] 
                year = expiry[4:6]
                formatted_expiry = f"{day}/{month}/{year}"
            else:
                formatted_expiry = expiry
            
            return f"{underlying} {strike} {option_name}"
    
    # Return original symbol if not in expected format
    return symbol

def format_position_message(position: Dict) -> str:
    """Format single position message"""
    symbol = position.get('product', {}).get('symbol', 'Unknown')
    size = position.get('size', 0)
    entry_price = position.get('entry_price', 0)
    mark_price = position.get('mark_price', 0)
    pnl = position.get('unrealized_pnl', 0)
    
    pnl_emoji = "🟢" if float(pnl) >= 0 else "🔴"
    
    message = f"<b>Position: {symbol}</b>\n"
    message += f"Size: {size}\n"
    message += f"Entry Price: ${entry_price}\n"
    message += f"Mark Price: ${mark_price}\n"
    message += f"PnL: {pnl_emoji} ${pnl}\n"
    
    return message

def round_to_strike(price: float, strike_interval: float = 100) -> float:
    """Round price to nearest strike price interval"""
    return round(price / strike_interval) * strike_interval

def validate_lot_size(lot_size_str: str) -> tuple:
    """Validate and return lot size with success status"""
    try:
        lot_size = int(lot_size_str)
        if lot_size <= 0:
            return False, "Please enter a positive number for lot size."
        if lot_size > 1000:
            return False, "Lot size cannot exceed 1000 contracts."
        return True, lot_size
    except ValueError:
        return False, "Please enter a valid number for lot size."

def format_option_details(option: Dict) -> str:
    """Format option details for display"""
    if not option:
        return "Option data not available"
    
    symbol = option.get('symbol', 'N/A')
    mark_price = option.get('mark_price', 0)
    bid = option.get('quotes', {}).get('best_bid', 0)
    ask = option.get('quotes', {}).get('best_ask', 0)
    
    return f"Symbol: {symbol}\nMark: ${mark_price}\nBid: ${bid}\nAsk: ${ask}"

def calculate_straddle_cost(ce_option: Dict, pe_option: Dict, lot_size: int, strategy: str) -> float:
    """Calculate total cost/credit for straddle strategy"""
    if not ce_option or not pe_option:
        return 0.0
    
    ce_price = float(ce_option.get('mark_price', 0))
    pe_price = float(pe_option.get('mark_price', 0))
    
    total_premium = (ce_price + pe_price) * lot_size
    
    # For long straddle, it's a cost (debit)
    # For short straddle, it's a credit
    return total_premium if strategy == "long" else -total_premium
