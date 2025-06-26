#!/usr/bin/env python3
"""
Test script for BLE lock functionality.
This can be used to test BLE connectivity without running the full HomeKey application.
"""

import asyncio
import logging
import sys
from ble_client import BLELockManager
from api_client import LockAPIClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)8s] %(module)-18s:%(lineno)-4d %(message)s'
)
log = logging.getLogger(__name__)


async def test_api_client():
    """Test API client functionality"""
    log.info("Testing API client...")
    
    api_client = LockAPIClient("http://localhost:8080")
    
    # Test lock activation initiation
    result = await api_client.initiate_lock_activation(12345, "test_endpoint_123")
    if result:
        serial, message = result
        log.info(f"API returned: serial={serial}, message={message}")
    else:
        log.error("API initiation failed")
        
    # Test status reporting
    await api_client.report_lock_status(12345, "test_status", "test_endpoint_123")


async def test_ble_scan():
    """Test BLE device scanning"""
    log.info("Testing BLE device scanning...")
    
    try:
        from bleak import BleakScanner
        
        log.info("Scanning for BLE devices...")
        devices = await BleakScanner.discover(timeout=5.0)
        
        log.info(f"Found {len(devices)} BLE devices:")
        for device in devices:
            log.info(f"  - {device.name or 'Unknown'} ({device.address})")
            
        # Look for Nordic UART devices
        nordic_devices = [d for d in devices if d.name and "nordic" in d.name.lower()]
        if nordic_devices:
            log.info(f"Found {len(nordic_devices)} potential Nordic UART devices")
        else:
            log.info("No Nordic UART devices found")
            
    except Exception as e:
        log.error(f"BLE scanning failed: {e}")


async def test_ble_manager():
    """Test BLE manager functionality"""
    log.info("Testing BLE manager...")
    
    ble_manager = BLELockManager("http://localhost:8080")
    
    # This will fail unless you have a real BLE device, but tests the code path
    try:
        await ble_manager.initiate_connection(12345, [0x01, 0x02, 0x03])
        log.info("BLE connection test passed")
    except Exception as e:
        log.info(f"BLE connection test failed (expected): {e}")
        
    await ble_manager.disconnect_all()


async def main():
    """Run all tests"""
    log.info("Starting BLE functionality tests...")
    
    # Test API client (will fail if server not running)
    try:
        await test_api_client()
    except Exception as e:
        log.info(f"API test failed (expected if server not running): {e}")
    
    # Test BLE scanning
    await test_ble_scan()
    
    # Test BLE manager
    await test_ble_manager()
    
    log.info("BLE functionality tests completed")


if __name__ == "__main__":
    if sys.platform == "win32":
        # Windows requires ProactorEventLoop for BLE
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    asyncio.run(main()) 