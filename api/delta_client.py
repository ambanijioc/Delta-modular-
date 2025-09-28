import requests
import json
import time
import hashlib
import hmac
import logging
from typing import List, Dict, Optional
from config.config import DELTA_API_KEY, DELTA_API_SECRET, DELTA_BASE_URL

logger = logging.getLogger(__name__)

class DeltaClient:
    def __init__(self):
        self.api_key = DELTA_API_KEY
        self.api_secret = DELTA_API_SECRET
        self.base_url = DELTA_BASE_URL
        self.session = requests.Session()
        
        if not self.api_key or not self.api_secret:
            logger.error("❌ Delta API credentials not configured")
            raise ValueError("Delta API credentials are required")
    
    def _generate_signature(self, secret: str, message: str) -> str:
        """Generate HMAC SHA256 signature"""
        try:
            message = bytes(message, 'utf-8')
            secret = bytes(secret, 'utf-8')
            hash_obj = hmac.new(secret, message, hashlib.sha256)
            return hash_obj.hexdigest()
        except Exception as e:
            logger.error(f"❌ Signature generation failed: {e}")
            raise
    
    def _make_request(self, method: str, endpoint: str, params: Dict = None, payload: str = '') -> Dict:
        """Make authenticated request to Delta Exchange API"""
        try:
            timestamp = str(int(time.time()))
            path = f"/v2{endpoint}"
            url = f"{self.base_url}{path}"
            
            # Build query string for GET requests
            query_string = ''
            if params and method == 'GET':
                query_string = '?' + '&'.join([f"{k}={v}" for k, v in params.items()])
            
            # Create signature string
            signature_data = method + timestamp + path + query_string + payload
            signature = self._generate_signature(self.api_secret, signature_data)
            
            headers = {
                'api-key': self.api_key,
                'timestamp': timestamp,
                'signature': signature,
                'User-Agent': 'BTC-Options-Bot/1.0',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            logger.info(f"🔗 Making {method} request to {endpoint}")
            if params:
                logger.info(f"📋 Parameters: {params}")
            
            # Make the request
            if method == 'GET':
                response = self.session.get(url, params=params, headers=headers, timeout=30)
            elif method == 'POST':
                response = self.session.post(url, data=payload, headers=headers, timeout=30)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            logger.info(f"📈 Response status: {response.status_code}")
            
            # Handle response
            response.raise_for_status()
            result = response.json()
            
            # Check if response indicates success
            if isinstance(result, dict) and 'success' in result:
                if not result.get('success'):
                    logger.error(f"❌ API returned success=false: {result}")
                    return result
            
            # For responses without success field, assume success if status is 200
            if not isinstance(result, dict):
                result = {'success': True, 'result': result}
            elif 'success' not in result:
                result = {'success': True, 'result': result}
            
            logger.info("✅ Request successful")
            return result
            
        except requests.exceptions.Timeout as e:
            logger.error(f"❌ Request timeout: {e}")
            return {"success": False, "error": "Request timeout"}
        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ HTTP error {e.response.status_code}: {e}")
            try:
                error_detail = e.response.json()
                logger.error(f"❌ Error details: {error_detail}")
                return {"success": False, "error": error_detail}
            except:
                return {"success": False, "error": f"HTTP {e.response.status_code}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Request failed: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def test_connection(self) -> Dict:
        """Test API connection"""
        logger.info("🧪 Testing Delta Exchange API connection...")
        try:
            response = self.session.get(f"{self.base_url}/v2/products", timeout=10)
            if response.status_code == 200:
                logger.info("✅ Connection test successful")
                return {"success": True, "message": "Connection OK"}
            else:
                logger.error(f"❌ Connection test failed: {response.status_code}")
                return {"success": False, "error": f"Status: {response.status_code}"}
        except Exception as e:
            logger.error(f"❌ Connection test failed: {e}")
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
            logger.info("💰 Fetching BTC spot price...")
            response = self.get_ticker('BTCUSD')
            
            if response.get('success'):
                spot_price = float(response['result']['spot_price'])
                logger.info(f"✅ BTC spot price: ${spot_price:,.2f}")
                return spot_price
            else:
                logger.error(f"❌ Failed to get BTC price: {response}")
                return None
        except Exception as e:
            logger.error(f"❌ Error getting BTC spot price: {e}")
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
        logger.info(f"📋 Placing {side} order: {size} contracts of product {product_id}")
        return self._make_request('POST', '/orders', payload=json.dumps(payload))
    
    def get_margined_position(self, product_id: int) -> Dict:
        """Get position for a specific product ID"""
        logger.info(f"📊 Fetching position for product {product_id}...")
        params = {'product_id': product_id}
        return self._make_request('GET', '/positions/margined', params)
    
    def get_position(self, product_id: int) -> Dict:
        """Get position for a specific product ID (alternative endpoint)"""
        logger.info(f"📊 Fetching position for product {product_id}...")
        params = {'product_id': product_id}
        return self._make_request('GET', '/positions', params)
    
    def get_positions_by_underlying(self, underlying_symbol: str = 'BTC') -> Dict:
        """Get all positions for a specific underlying asset"""
        logger.info(f"📊 Fetching positions for {underlying_symbol}...")
        params = {'underlying_asset_symbol': underlying_symbol}
        return self._make_request('GET', '/positions', params)
    
    def get_all_btc_positions(self) -> Dict:
        """Get all BTC-related positions (futures and options)"""
        logger.info("📊 Fetching all BTC positions...")
        
        try:
            # Get all BTC products first
            products_response = self.get_products()
            if not products_response.get('success'):
                return {"success": False, "error": "Failed to fetch products"}
            
            all_positions = []
            btc_products = []
            
            # Filter BTC products
            for product in products_response.get('result', []):
                underlying = product.get('underlying_asset', {})
                if underlying.get('symbol') == 'BTC':
                    btc_products.append(product)
            
            logger.info(f"Found {len(btc_products)} BTC products")
            
            # Get positions for each BTC product
            for product in btc_products[:10]:  # Limit to first 10 to avoid rate limits
                product_id = product.get('id')
                if product_id:
                    try:
                        pos_response = self.get_position(product_id)
                        if pos_response.get('success') and pos_response.get('result'):
                            position = pos_response['result']
                            # Only include positions with non-zero size
                            if position.get('size', 0) != 0:
                                all_positions.append(position)
                    except Exception as e:
                        logger.warning(f"Failed to get position for product {product_id}: {e}")
                        continue
            
            logger.info(f"✅ Found {len(all_positions)} active BTC positions")
            return {"success": True, "result": all_positions}
            
        except Exception as e:
            logger.error(f"❌ Error getting all BTC positions: {e}")
            return {"success": False, "error": str(e)}
    
    def get_positions(self) -> Dict:
        """Get all positions - enhanced method with multiple approaches"""
        logger.info("📊 Fetching positions...")
        
        # Try multiple approaches to get positions
        approaches = [
            ("BTC positions", self.get_positions_by_underlying, 'BTC'),
            ("All BTC positions", self.get_all_btc_positions, None),
        ]
        
        for approach_name, method, param in approaches:
            try:
                logger.info(f"🔄 Trying {approach_name}...")
                
                if param:
                    response = method(param)
                else:
                    response = method()
                
                if response.get('success'):
                    positions = response.get('result', [])
                    if positions:
                        logger.info(f"✅ Found {len(positions)} positions using {approach_name}")
                        return response
                    else:
                        logger.info(f"ℹ️ No positions found using {approach_name}")
                else:
                    logger.warning(f"⚠️ {approach_name} failed: {response.get('error')}")
                    
            except Exception as e:
                logger.warning(f"⚠️ {approach_name} threw exception: {e}")
                continue
        
        # If all approaches fail, return empty but successful response
        logger.info("ℹ️ No positions found using any method")
        return {"success": True, "result": []}
    
    def get_available_expiry_dates(self, underlying: str = 'BTC') -> List[str]:
        """Get available expiry dates for BTC options"""
        try:
            logger.info(f"📅 Fetching expiry dates for {underlying}...")
            response = self.get_products('call_options,put_options')
            
            if not response.get('success'):
                logger.error(f"❌ Failed to get products: {response}")
                return []
            
            expiry_dates = set()
            products = response.get('result', [])
            
            for product in products:
                if product.get('underlying_asset', {}).get('symbol') == underlying:
                    # Extract expiry date from settlement_time or symbol
                    if 'settlement_time' in product:
                        # Use settlement_time if available
                        settlement_time = product['settlement_time']
                        # Convert to readable format
                        import datetime
                        dt = datetime.datetime.fromisoformat(settlement_time.replace('Z', '+00:00'))
                        formatted_date = dt.strftime('%d-%m-%Y')
                        expiry_dates.add(formatted_date)
                    else:
                        # Fallback to parsing from symbol
                        symbol_parts = product.get('symbol', '').split('-')
                        if len(symbol_parts) >= 4:
                            date_str = symbol_parts[-1]  # DDMMYY format
                            if len(date_str) == 6:
                                day, month, year = date_str[:2], date_str[2:4], '20' + date_str[4:6]
                                formatted_date = f"{day}-{month}-{year}"
                                expiry_dates.add(formatted_date)
            
            sorted_dates = sorted(list(expiry_dates))
            logger.info(f"✅ Found {len(sorted_dates)} expiry dates")
            return sorted_dates
            
        except Exception as e:
            logger.error(f"❌ Error getting expiry dates: {e}")
            return []
    
    def get_portfolio_summary(self) -> Dict:
        """Get portfolio summary"""
        logger.info("📊 Fetching portfolio summary...")
        return self._make_request('GET', '/wallet/balances')
    
    def get_trade_history(self, product_id: int = None, limit: int = 50) -> Dict:
        """Get trade history"""
        logger.info("📊 Fetching trade history...")
        params = {'limit': limit}
        if product_id:
            params['product_id'] = product_id
        return self._make_request('GET', '/fills', params)
            
    def place_stop_order(self, product_id: int, size: int, side: str, 
                    stop_price: str = None, limit_price: str = None,
                    trail_amount: str = None, order_type: str = "market_order",
                    isTrailingStopLoss: bool = False) -> Dict:
        """Place a stop-loss order"""
        payload = {
            "product_id": product_id,
            "size": size,
            "side": side,
            "order_type": order_type
        }
    
        if isTrailingStopLoss:
            payload["trail_amount"] = trail_amount
            payload["isTrailingStopLoss"] = True
        else:
            payload["stop_price"] = stop_price
            if order_type == "limit_order" and limit_price:
                payload["limit_price"] = limit_price
    
        logger.info(f"📋 Placing stop order: {side} {size} contracts, product {product_id}")
        return self._make_request('POST', '/orders/stop', payload=json.dumps(payload))

    def get_order_by_id(self, order_id: str) -> Dict:
        """Get order details by order ID"""
        logger.info(f"📊 Fetching order details for ID: {order_id}")
        return self._make_request('GET', f'/orders/{order_id}')

    def get_stop_orders(self, product_id: int = None) -> Dict:
        """Get all stop orders"""
        params = {}
        if product_id:
            params['product_id'] = product_id
    
        logger.info("📊 Fetching stop orders...")
        return self._make_request('GET', '/orders/stop', params)

    def cancel_stop_order(self, order_id: str) -> Dict:
        """Cancel a stop order"""
        logger.info(f"❌ Cancelling stop order: {order_id}")
        return self._make_request('DELETE', f'/orders/stop/{order_id}')
        
