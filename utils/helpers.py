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
    """Format positions display message"""
    message = "<b>📊 Open Positions</b>\n\n"
    
    if not positions:
        return "<b>📊 No Open Positions</b>\n\nYou currently have no active positions."
    
    for i, position in enumerate(positions[:10], 1):  # Limit to 10 positions
        symbol = position.get('product', {}).get('symbol', 'Unknown')
        size = position.get('size', 0)
        entry_price = position.get('entry_price', 0)
        mark_price = position.get('mark_price', 0)
        pnl = position.get('unrealized_pnl', 0)
        
        pnl_emoji = "🟢" if float(pnl) >= 0 else "🔴"
        
        message += f"<b>{i}. {symbol}</b>\n"
        message += f"   Size: {size}\n"
        message += f"   Entry: ${entry_price}\n"
        message += f"   Mark: ${mark_price}\n"
        message += f"   PnL: {pnl_emoji} ${pnl}\n\n"
    
    return message

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
