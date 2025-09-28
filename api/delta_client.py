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
    
    def get_positions_enhanced(self) -> Dict:
        """Enhanced positions fetching with product details"""
        logger.info("📊 Fetching enhanced positions with product details...")
        
        try:
            # First try to get positions by underlying asset
            response = self.get_positions_by_underlying('BTC')
            
            if not response.get('success') or not response.get('result'):
                # Fallback: Try to get all positions and filter
                logger.info("🔄 Fallback: Trying alternative position fetch...")
                response = self._get_positions_alternative()
            
            if response.get('success'):
                positions = response.get('result', [])
                # Enhance positions with product details
                enhanced_positions = []
                
                for position in positions:
                    enhanced_position = self._enhance_position_data(position)
                    if enhanced_position:
                        enhanced_positions.append(enhanced_position)
                
                logger.info(f"✅ Enhanced {len(enhanced_positions)} positions")
                return {"success": True, "result": enhanced_positions}
            
            return response
            
        except Exception as e:
            logger.error(f"❌ Error in get_positions_enhanced: {e}")
            return {"success": False, "error": str(e)}
    
    def _get_positions_alternative(self) -> Dict:
        """Alternative method to get positions"""
        try:
            # Try different API endpoints
            endpoints_to_try = [
                ('/positions/margined', {}),
                ('/portfolio/positions', {}),
                ('/positions', {'underlying_asset_symbol': 'BTC'})
            ]
            
            for endpoint, params in endpoints_to_try:
                try:
                    logger.info(f"🔄 Trying endpoint: {endpoint}")
                    response = self._make_request('GET', endpoint, params)
                    
                    if response.get('success') and response.get('result'):
                        logger.info(f"✅ Success with {endpoint}")
                        return response
                        
                except Exception as e:
                    logger.warning(f"⚠️ Endpoint {endpoint} failed: {e}")
                    continue
            
            # If all endpoints fail, return empty but successful response
            logger.warning("⚠️ All position endpoints failed, returning empty")
            return {"success": True, "result": []}
            
        except Exception as e:
            logger.error(f"❌ Alternative position fetch failed: {e}")
            return {"success": False, "error": str(e)}
    
    def force_enhance_positions(self) -> Dict:
        """Force-fetch complete product data for positions"""
        try:
            logger.info("🔄 Force-fetching complete product data for positions...")
        
            # Get all BTC products first
            all_products = self.get_products('call_options,put_options,futures')
            if not all_products.get('success'):
                logger.error("Failed to fetch products for enhancement")
                return {"success": False, "error": "Failed to fetch products"}
        
            # Get positions with required parameter
            positions = self._make_request('GET', '/positions', {'underlying_asset_symbol': 'BTC'})
            if not positions.get('success'):
                logger.error("Failed to fetch basic positions with BTC filter")
                # Try alternative approach - get positions for each product
                return self._get_positions_by_product_scan(all_products['result'])
        
            products_list = all_products['result']
            positions_list = positions['result']
        
            logger.info(f"Got {len(products_list)} products and {len(positions_list)} positions")
        
            # Create product lookup by ID
            product_map = {p['id']: p for p in products_list if p.get('id')}
            logger.info(f"Created product map with {len(product_map)} entries")
        
            # Match positions with full product data
            enhanced_positions = []
            for pos in positions_list:
                position_size = float(pos.get('size', 0))
                if position_size == 0:
                    continue  # Skip zero positions
            
                product_id = pos.get('product_id') or pos.get('product', {}).get('id')
                logger.info(f"Processing position with product_id: {product_id}, size: {position_size}")
            
                if product_id and product_id in product_map:
                    full_product = product_map[product_id]
                    pos['product'] = full_product
                    symbol = full_product.get('symbol', 'Unknown')
                    logger.info(f"✅ Matched position to product: {symbol}")
                else:
                    logger.warning(f"⚠️ No product match found for position with product_id: {product_id}")
            
                enhanced_positions.append(pos)
        
            logger.info(f"✅ Enhanced {len(enhanced_positions)} positions")
            return {"success": True, "result": enhanced_positions}
        
        except Exception as e:
            logger.error(f"❌ Force enhance failed: {e}")
            return {"success": False, "error": str(e)}

    def _get_positions_by_product_scan(self, products_list: List[Dict]) -> Dict:
        """Alternative: Scan each product for positions"""
        try:
            logger.info("🔄 Scanning individual products for positions...")
        
            all_positions = []
        
            # Check positions for each BTC product (limit to prevent rate limiting)
            btc_products = [p for p in products_list if 'BTC' in p.get('symbol', '')][:50]  # Limit to 50
        
            for product in btc_products:
                product_id = product.get('id')
                if not product_id:
                    continue
                
                try:
                    # Get positions for specific product
                    pos_response = self._make_request('GET', '/positions', {'product_id': product_id})
                
                    if pos_response.get('success'):
                        positions = pos_response.get('result', [])
                        for pos in positions:
                            if float(pos.get('size', 0)) != 0:  # Only non-zero positions
                                pos['product'] = product  # Attach full product info
                                all_positions.append(pos)
                                logger.info(f"✅ Found position: {product.get('symbol')} - Size: {pos.get('size')}")
                
                except Exception as e:
                    logger.warning(f"Failed to check product {product_id}: {e}")
                    continue
        
            logger.info(f"✅ Product scan found {len(all_positions)} positions")
            return {"success": True, "result": all_positions}
        
        except Exception as e:
            logger.error(f"❌ Product scan failed: {e}")
            return {"success": False, "error": str(e)}
    
    def _enhance_position_data(self, position: dict) -> dict:
        """Enhanced position data extraction with better symbol detection"""
        try:
            # Get product details if missing or incomplete
            product = position.get('product', {})
            product_id = product.get('id') or position.get('product_id')
            
            # If we don't have a proper symbol, try to fetch product details
            current_symbol = product.get('symbol', '')
            
            if not current_symbol or current_symbol == 'Unknown' or not self._is_valid_symbol(current_symbol):
                if product_id:
                    # Try to fetch full product details from API
                    logger.info(f"Fetching product details for ID: {product_id}")
                    product_response = self.get_product_by_id(product_id)
                    
                    if product_response.get('success'):
                        full_product = product_response['result']
                        # Update the position with full product data
                        position['product'] = full_product
                        logger.info(f"Enhanced product data: {full_product.get('symbol', 'Still Unknown')}")
            
            # Ensure numeric fields are properly formatted
            position['size'] = float(position.get('size', 0))
            position['entry_price'] = float(position.get('entry_price', 0))
            position['mark_price'] = float(position.get('mark_price', 0))
            position['unrealized_pnl'] = float(position.get('unrealized_pnl', 0))
            
            return position
            
        except Exception as e:
            logger.error(f"❌ Error enhancing position data: {e}")
            return position
    
    def _is_valid_symbol(self, symbol: str) -> bool:
        """Check if symbol contains meaningful information"""
        if not symbol or symbol == 'Unknown':
            return False
        # Valid symbols should have more specific format
        valid_patterns = ['BTC-', 'ETH-', '-CE-', '-PE-', '-C-', '-P-']
        return any(pattern in symbol for pattern in valid_patterns)
    
    def get_positions_with_product_details(self) -> Dict:
        """Get positions with full product details via separate API calls"""
        try:
            logger.info("📊 Fetching positions with enhanced product details...")
            
            # Get basic positions first
            positions_response = self._make_request('GET', '/positions', {'underlying_asset_symbol': 'BTC'})
            
            if not positions_response.get('success'):
                logger.warning("Direct positions call failed, trying alternative...")
                positions_response = self._make_request('GET', '/positions')
            
            if not positions_response.get('success'):
                return {"success": False, "error": "Failed to fetch positions"}
            
            positions = positions_response.get('result', [])
            enhanced_positions = []
            
            # Enhance each position with full product data
            for position in positions:
                if float(position.get('size', 0)) == 0:
                    continue  # Skip zero positions
                
                product = position.get('product', {})
                product_id = product.get('id') or position.get('product_id')
                
                if product_id:
                    # Get full product details
                    try:
                        product_response = self.get_product_by_id(product_id)
                        if product_response.get('success'):
                            full_product_data = product_response['result']
                            position['product'] = full_product_data
                            logger.info(f"Enhanced position with symbol: {full_product_data.get('symbol', 'Unknown')}")
                    except Exception as e:
                        logger.warning(f"Failed to get product details for {product_id}: {e}")
                
                enhanced_positions.append(position)
            
            logger.info(f"✅ Enhanced {len(enhanced_positions)} positions")
            return {"success": True, "result": enhanced_positions}
            
        except Exception as e:
            logger.error(f"❌ Error in get_positions_with_product_details: {e}")
            return {"success": False, "error": str(e)}
    
    def get_positions(self) -> Dict:
        """Main positions method - now uses force enhancement first"""
        logger.info("📊 Fetching positions with complete product information...")
    
        # Try force enhancement first (most reliable for getting real symbols)
        try:
            logger.info("🔄 Attempting force enhancement...")
            force_response = self.force_enhance_positions()
        
            if force_response.get('success'):
                positions = force_response.get('result', [])
                logger.info(f"✅ Force enhancement returned {len(positions)} positions")
            
                # Log the first position's symbol
                if positions:
                    first_pos_symbol = positions[0].get('product', {}).get('symbol', 'Still Unknown')
                    logger.info(f"📋 First position symbol after enhancement: '{first_pos_symbol}'")
            
                if positions:
                    return force_response
            else:
                logger.error(f"❌ Force enhancement failed: {force_response.get('error')}")
        except Exception as e:
            logger.error(f"❌ Force enhancement exception: {e}")
    
        # Fallback to existing method
        logger.info("🔄 Using fallback position fetch...")
        return self.get_positions_by_underlying('BTC')

    def get_product_by_id(self, product_id: int) -> Dict:
        """Get product details by product ID"""
        logger.info(f"📊 Fetching product details for ID: {product_id}")
        return self._make_request('GET', f'/products/{product_id}')
    
    def get_all_products_with_positions(self) -> Dict:
        """Get all products and match with positions"""
        try:
            logger.info("📊 Fetching all products to match positions...")
            
            # Get all products
            products_response = self.get_products()
            if not products_response.get('success'):
                return {"success": False, "error": "Failed to fetch products"}
            
            # Get basic positions
            positions_response = self._make_request('GET', '/positions')
            if not positions_response.get('success'):
                return {"success": False, "error": "Failed to fetch positions"}
            
            products = products_response.get('result', [])
            positions = positions_response.get('result', [])
            
            # Create product lookup
            product_lookup = {p.get('id'): p for p in products}
            
            # Enhance positions with product data
            enhanced_positions = []
            for position in positions:
                product_id = position.get('product_id') or position.get('product', {}).get('id')
                
                if product_id and product_id in product_lookup:
                    position['product'] = product_lookup[product_id]
                    enhanced_positions.append(position)
                elif position.get('size', 0) != 0:  # Include non-zero positions even without product details
                    enhanced_positions.append(position)
            
            logger.info(f"✅ Enhanced {len(enhanced_positions)} positions with product details")
            return {"success": True, "result": enhanced_positions}
            
        except Exception as e:
            logger.error(f"❌ Error in get_all_products_with_positions: {e}")
            return {"success": False, "error": str(e)}
    
    def get_positions(self) -> Dict:
        """Updated main positions method with enhanced data"""
        logger.info("📊 Fetching positions with enhanced data...")
        
        # Try enhanced method first
        try:
            enhanced_response = self.get_positions_enhanced()
            if enhanced_response.get('success') and enhanced_response.get('result'):
                return enhanced_response
        except Exception as e:
            logger.warning(f"⚠️ Enhanced positions failed: {e}")
        
        # Try products matching method
        try:
            products_response = self.get_all_products_with_positions()
            if products_response.get('success') and products_response.get('result'):
                return products_response
        except Exception as e:
            logger.warning(f"⚠️ Products matching failed: {e}")
        
        # Final fallback to original method
        try:
            return self.get_positions_by_underlying('BTC')
        except Exception as e:
            logger.error(f"❌ All position methods failed: {e}")
            return {"success": False, "error": "Unable to fetch positions"}
    
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
                    trail_amount: str = None, order_type: str = "limit_order",
                    isTrailingStopLoss: bool = False, reduce_only: bool = True) -> Dict:
        """Place a real stop-loss order with enhanced debugging"""
        try:
            logger.info(f"🔄 Starting stop order placement...")
            logger.info(f"📋 Parameters: product_id={product_id}, size={size}, side={side}")
            logger.info(f"📋 Stop price={stop_price}, limit_price={limit_price}")
            logger.info(f"📋 Order type={order_type}, reduce_only={reduce_only}")
        
        # Validate required parameters
            if not product_id:
                error_msg = "Product ID is required"
                logger.error(f"❌ {error_msg}")
                return {"success": False, "error": error_msg}
        
            if not size or size <= 0:
                error_msg = "Size must be greater than 0"
                logger.error(f"❌ {error_msg}")
                return {"success": False, "error": error_msg}
        
            if not side or side not in ['buy', 'sell']:
                error_msg = "Side must be 'buy' or 'sell'"
                logger.error(f"❌ {error_msg}")
                return {"success": False, "error": error_msg}
        
        # Prepare the order payload
            payload = {
                "product_id": int(product_id),
                "size": int(size),
                "side": side,
                "reduce_only": reduce_only,
                "time_in_force": "gtc"  # Good till cancelled
            }
        
            if isTrailingStopLoss:
                # Trailing stop order
                if not trail_amount:
                    error_msg = "Trail amount is required for trailing stops"
                    logger.error(f"❌ {error_msg}")
                    return {"success": False, "error": error_msg}
            
                payload.update({
                    "trail_amount": str(trail_amount),
                    "order_type": "market_order"
            })
                logger.info(f"📋 Trailing stop payload prepared")
            else:
            # Regular stop order
                if not stop_price:
                    error_msg = "Stop price is required"
                    logger.error(f"❌ {error_msg}")
                    return {"success": False, "error": error_msg}
            
                payload.update({
                    "stop_price": str(stop_price),
                    "order_type": order_type
            })
            
                if order_type == "limit_order":
                    if not limit_price:
                        error_msg = "Limit price is required for limit orders"
                        logger.error(f"❌ {error_msg}")
                        return {"success": False, "error": error_msg}
                    payload["limit_price"] = str(limit_price)
            
                logger.info(f"📋 Stop order payload prepared")
        
            logger.info(f"📤 Final payload: {json.dumps(payload, indent=2)}")
        
        # Make the API call
            logger.info(f"🌐 Making API call to /orders/stop")
            response = self._make_request('POST', '/orders/stop', payload=json.dumps(payload))
        
            logger.info(f"📥 API response received: {response}")
        
            if response.get('success'):
                result = response.get('result', {})
                order_id = result.get('id', 'Missing ID')
                order_state = result.get('state', 'Unknown state')
                logger.info(f"✅ Stop order placed successfully: ID={order_id}, State={order_state}")
            else:
                error = response.get('error', 'Unknown error')
                logger.error(f"❌ Stop order failed: {error}")
        
            return response
        
        except Exception as e:
            logger.error(f"❌ Exception in place_stop_order: {e}", exc_info=True)
            return {"success": False, "error": f"Exception: {str(e)}"}
    
    def get_margined_position(self, product_id: int) -> Dict:
        """Get margined position for a specific product"""
        logger.info(f"📊 Fetching margined position for product: {product_id}")
        return self._make_request('GET', f'/positions/margined/{product_id}')
    
    def get_position(self, product_id: int) -> Dict:
        """Get position for a specific product"""
        logger.info(f"📊 Fetching position for product: {product_id}")
        return self._make_request('GET', f'/positions', {'product_id': product_id})
    
    def cancel_all_stop_orders(self, product_id: int = None) -> Dict:
        """Cancel all stop orders for a product or all products"""
        params = {}
        if product_id:
            params['product_id'] = product_id
        
        logger.info(f"❌ Cancelling stop orders for product: {product_id or 'ALL'}")
        return self._make_request('DELETE', '/orders/stop/all', params)
    
    def get_order_status(self, order_id: str) -> Dict:
        """Get status of a specific order"""
        logger.info(f"📊 Checking order status: {order_id}")
        return self._make_request('GET', f'/orders/{order_id}')

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
        
