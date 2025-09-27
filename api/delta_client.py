import requests
import json
import time
import hashlib
import hmac
from typing import List, Dict, Optional
from config.config import DELTA_API_KEY, DELTA_API_SECRET, DELTA_BASE_URL

class DeltaClient:
    def __init__(self):
        self.api_key = DELTA_API_KEY
        self.api_secret = DELTA_API_SECRET
        self.base_url = DELTA_BASE_URL
        
    def _generate_signature(self, secret: str, message: str) -> str:
        """Generate HMAC SHA256 signature"""
        message = bytes(message, 'utf-8')
        secret = bytes(secret, 'utf-8')
        hash_obj = hmac.new(secret, message, hashlib.sha256)
        return hash_obj.hexdigest()
    
    def _make_request(self, method: str, endpoint: str, params: Dict = None, payload: str = '') -> Dict:
        """Make authenticated request to Delta Exchange API"""
        timestamp = str(int(time.time()))
        path = f"/v2{endpoint}"
        url = f"{self.base_url}{path}"
        
        query_string = ''
        if params and method == 'GET':
            query_string = '?' + '&'.join([f"{k}={v}" for k, v in params.items()])
        
        signature_data = method + timestamp + path + query_string + payload
        signature = self._generate_signature(self.api_secret, signature_data)
        
        headers = {
            'api-key': self.api_key,
            'timestamp': timestamp,
            'signature': signature,
            'User-Agent': 'python-telegram-bot',
            'Content-Type': 'application/json'
        }
        
        try:
            if method == 'GET':
                response = requests.get(url, params=params, headers=headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, data=payload, headers=headers, timeout=10)
            
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"API request failed: {e}")
            return {"success": False, "error": str(e)}
    
    def get_products(self, contract_types: str = None) -> Dict:
        """Get list of products with optional filtering"""
        params = {}
        if contract_types:
            params['contract_types'] = contract_types
        return self._make_request('GET', '/products', params)
    
    def get_ticker(self, symbol: str) -> Dict:
        """Get ticker data for a specific symbol"""
        return self._make_request('GET', f'/tickers/{symbol}')
    
    def get_btc_spot_price(self) -> Optional[float]:
        """Get BTC spot price from ticker"""
        try:
            response = self.get_ticker('BTCUSD')
            if response.get('success'):
                return float(response['result']['spot_price'])
        except Exception as e:
            print(f"Error getting BTC spot price: {e}")
        return None
    
    def get_option_chain(self, underlying: str, expiry_date: str) -> Dict:
        """Get option chain for specific underlying and expiry"""
        params = {
            'contract_types': 'call_options,put_options',
            'underlying_asset_symbols': underlying,
            'expiry_date': expiry_date
        }
        return self._make_request('GET', '/tickers', params)
    
    def place_order(self, product_id: int, side: str, size: int, order_type: str = 'market_order') -> Dict:
        """Place an order"""
        payload = {
            "product_id": product_id,
            "size": size,
            "side": side,
            "order_type": order_type
        }
        return self._make_request('POST', '/orders', payload=json.dumps(payload))
    
    def get_positions(self) -> Dict:
        """Get all open positions"""
        return self._make_request('GET', '/positions')
    
    def get_available_expiry_dates(self, underlying: str = 'BTC') -> List[str]:
        """Get available expiry dates for BTC options"""
        try:
            response = self.get_products('call_options,put_options')
            if not response.get('success'):
                return []
            
            expiry_dates = set()
            for product in response.get('result', []):
                if product.get('underlying_asset', {}).get('symbol') == underlying:
                    # Extract expiry date from symbol (format: C-BTC-STRIKE-DDMMYY)
                    symbol_parts = product.get('symbol', '').split('-')
                    if len(symbol_parts) >= 4:
                        date_str = symbol_parts[-1]  # DDMMYY format
                        if len(date_str) == 6:
                            # Convert DDMMYY to DD-MM-YYYY
                            day = date_str[:2]
                            month = date_str[2:4]
                            year = '20' + date_str[4:6]
                            formatted_date = f"{day}-{month}-{year}"
                            expiry_dates.add(formatted_date)
            
            return sorted(list(expiry_dates))
        except Exception as e:
            print(f"Error getting expiry dates: {e}")
            return []
