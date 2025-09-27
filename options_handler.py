from delta_client import DeltaExchangeClient
from config import LOT_SIZE

class OptionsHandler:
    def __init__(self):
        self.delta_client = DeltaExchangeClient()
        self.selected_expiry = None
        self.selected_atm_call = None
        self.selected_atm_put = None
        self.spot_price = None
    
    async def get_expiry_dates(self):
        """Get available expiry dates"""
        return self.delta_client.get_available_expiry_dates()
    
    async def set_expiry_and_get_atm_options(self, expiry_date):
        """Set expiry date and get ATM options"""
        self.selected_expiry = expiry_date
        self.spot_price = self.delta_client.get_btc_spot_price()
        
        if not self.spot_price:
            return None
        
        self.selected_atm_call, self.selected_atm_put = self.delta_client.get_atm_options(
            expiry_date, self.spot_price
        )
        
        return {
            'spot_price': self.spot_price,
            'atm_call': self.selected_atm_call,
            'atm_put': self.selected_atm_put
        }
    
    async def execute_straddle_order(self):
        """Execute both CE and PE orders"""
        if not self.selected_atm_call or not self.selected_atm_put:
            return {'success': False, 'error': 'No ATM options selected'}
        
        results = {
            'call_order': None,
            'put_order': None,
            'success': True,
            'errors': []
        }
        
        # Place Call Option Order
        call_result = self.delta_client.place_market_order(
            self.selected_atm_call['product_id'], 
            'buy', 
            LOT_SIZE
        )
        
        if call_result and call_result.get('success'):
            results['call_order'] = call_result['result']
        else:
            results['success'] = False
            results['errors'].append(f"Call order failed: {call_result}")
        
        # Place Put Option Order
        put_result = self.delta_client.place_market_order(
            self.selected_atm_put['product_id'], 
            'buy', 
            LOT_SIZE
        )
        
        if put_result and put_result.get('success'):
            results['put_order'] = put_result['result']
        else:
            results['success'] = False
            results['errors'].append(f"Put order failed: {put_result}")
        
        return results
      
