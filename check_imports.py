#!/usr/bin/env python3
"""
Import verification script to check all modules load correctly
"""

def check_imports():
    """Check all imports work correctly"""
    try:
        print("Checking core imports...")
        import config.config
        print("✅ config.config imported successfully")
        
        import api.delta_client
        print("✅ api.delta_client imported successfully")
        
        import api.telegram_client
        print("✅ api.telegram_client imported successfully")
        
        import handlers.expiry_handler
        print("✅ handlers.expiry_handler imported successfully")
        
        import handlers.options_handler
        print("✅ handlers.options_handler imported successfully")
        
        import handlers.position_handler
        print("✅ handlers.position_handler imported successfully")
        
        import utils.helpers
        print("✅ utils.helpers imported successfully")
        
        import utils.constants
        print("✅ utils.constants imported successfully")
        
        import models.option_data
        print("✅ models.option_data imported successfully")
        
        print("\n🎉 All imports successful!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    check_imports()
  
