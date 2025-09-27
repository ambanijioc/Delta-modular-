import hashlib
import hmac
import time
import json
import requests
from datetime import datetime, timedelta
from config import DELTA_API_KEY, DELTA_API_SECRET, DELTA_BASE_URL, BTC_SPOT_SYMBOL

class DeltaExchangeClient:
    def __init__(self):
        self.api_key = DELTA_API_KEY
        self.api_secret = DELTA_API_SECRET
        self.base_url = DELTA_BASE_URL
        
    def generate_signature(self, secret, message):
        """Generate HMAC signature for API authentication"""
        message = bytes(message, 'utf-8')
        secret = bytes(secret, 'utf-8')
        hash = hmac.new(secret, message, hashlib.sha256)
        return hash.hexdigest()
    
    def make_request(self, method, path, query_params=None, payload=None):
        """Make authenticated request to Delta Exchange API"""
        timestamp = str(int(time.time()))
        url = f"{self.base_url}{path}"
        
        query_string = ''
        if query_params:
            query_string = '?' + '&'.join([f"{k}={v}" for k, v in query_params.items()])
            
        body = json.dumps(payload) if payload else ''
        signature_data = method + timestamp + path + query_string + body
        signature = self.generate_signature(self.api_secret, signature_data)
        
        headers = {
            'api-key': self.api_key,
            'timestamp': timestamp,
            'signature': signature,
            'User-Agent': 'python-rest-client',
            'Content-Type': 'application/json'
        }
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, params=query_params, timeout=30)
            elif method == 'POST':
                response = requests.post(url, headers=headers, data=body, timeout=30)
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"API Request Error: {e}")
            return None
    
    def get_btc_spot_price(self):
        """Get current BTC spot price"""
        response = self.make_request('GET', f'/v2/tickers/{BTC_SPOT_SYMBOL}')
        if response and response.get('success'):
            return float(response['result']['mark_price'])
        return None
    
    def get_available_expiry_dates(self):
        """Get available BTC options expiry dates"""
        params = {
            'contract_types': 'call_options,put_options',
            'underlying_asset_symbols': 'BTC'
        }
        response = self.make_request('GET', '/v2/tickers', query_params=params)
        
        if response and response.get('success'):
            expiry_dates = set()
            for ticker in response['result']:
                if 'symbol' in ticker:
                    # Extract expiry date from symbol like C-BTC-90000-310125
                    symbol_parts = ticker['symbol'].split('-')
                    if len(symbol_parts) >= 4:
                        expiry_str = symbol_parts[3]  # 310125
                        # Convert to readable format
                        try:
                            expiry_date = datetime.strptime(expiry_str, '%d%m%y').strftime('%d-%m-%Y')
                            expiry_dates.add(expiry_date)
                        except ValueError:
                            continue
            return sorted(list(expiry_dates))
        return []
    
    def get_atm_options(self, expiry_date, spot_price):
        """Get ATM call and put options for given expiry date"""
        params = {
            'contract_types': 'call_options,put_options',
            'underlying_asset_symbols': 'BTC',
            'expiry_date': expiry_date
        }
        response = self.make_request('GET', '/v2/tickers', query_params=params)
        
        if not response or not response.get('success'):
            return None, None
        
        call_options = []
        put_options = []
        
        for ticker in response['result']:
            if 'strike_price' in ticker and ticker['strike_price']:
                strike_price = float(ticker['strike_price'])
                if ticker['symbol'].startswith('C-BTC'):
                    call_options.append({
                        'symbol': ticker['symbol'],
                        'product_id': ticker['product_id'],
                        'strike_price': strike_price,
                        'mark_price': ticker.get('mark_price', '0'),
                        'best_bid': ticker.get('quotes', {}).get('best_bid', '0'),
                        'best_ask': ticker.get('quotes', {}).get('best_ask', '0')
                    })
                elif ticker['symbol'].startswith('P-BTC'):
                    put_options.append({
                        'symbol': ticker['symbol'],
                        'product_id': ticker['product_id'],
                        'strike_price': strike_price,
                        'mark_price': ticker.get('mark_price', '0'),
                        'best_bid': ticker.get('quotes', {}).get('best_bid', '0'),
                        'best_ask': ticker.get('quotes', {}).get('best_ask', '0')
                    })
        
        # Find ATM options (closest to spot price)
        if call_options:
            atm_call = min(call_options, key=lambda x: abs(x['strike_price'] - spot_price))
        else:
            atm_call = None
            
        if put_options:
            atm_put = min(put_options, key=lambda x: abs(x['strike_price'] - spot_price))
        else:
            atm_put = None
        
        return atm_call, atm_put
    
    def place_market_order(self, product_id, side, size=1):
        """Place market order for options"""
        payload = {
            'product_id': product_id,
            'order_type': 'market_order',
            'side': side,
            'size': size
        }
        
        response = self.make_request('POST', '/v2/orders', payload=payload)
        return response
  
