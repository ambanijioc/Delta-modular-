from dataclasses import dataclass
from typing import Optional

@dataclass
class OptionQuote:
    """Option quote data structure"""
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None

@dataclass
class OptionData:
    """Option data structure"""
    symbol: str
    product_id: int
    strike_price: float
    contract_type: str  # 'call_options' or 'put_options'
    mark_price: Optional[float] = None
    quotes: Optional[OptionQuote] = None
    expiry_date: Optional[str] = None
    underlying: Optional[str] = None
    
    @classmethod
    def from_api_response(cls, data: dict):
        """Create OptionData from API response"""
        quotes_data = data.get('quotes', {})
        quotes = OptionQuote(
            best_bid=quotes_data.get('best_bid'),
            best_ask=quotes_data.get('best_ask'),
            bid_size=quotes_data.get('bid_size'),
            ask_size=quotes_data.get('ask_size')
        ) if quotes_data else None
        
        return cls(
            symbol=data.get('symbol', ''),
            product_id=data.get('product_id', 0),
            strike_price=float(data.get('strike_price', 0)),
            contract_type=data.get('contract_type', ''),
            mark_price=data.get('mark_price'),
            quotes=quotes,
            expiry_date=data.get('expiry_date'),
            underlying=data.get('underlying_asset', {}).get('symbol')
        )
      
