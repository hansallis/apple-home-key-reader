import asyncio
import logging
import json
from typing import Optional, Callable, Dict, Any
import aiohttp
from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

log = logging.getLogger(__name__)


class BLELockClient:
    """BLE client for communicating with lock devices"""
    
    # Service and characteristic UUIDs (matching TypeScript)
    SESAME_SERVICE_UUID = "0000fd30-0000-1000-8000-00805f9b34fb"
    UART_TX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # Write to this
    UART_RX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # Notifications from this
    
    # Company ID for manufacturer data filtering
    COMPANY_ID = 0x065B
    
    def __init__(self, api_base_url: str = "http://localhost:8080"):
        self.client: Optional[BleakClient] = None
        self.api_base_url = api_base_url
        self.door_serial: Optional[int] = None
        self.disconnect_callback: Optional[Callable] = None
        
    @staticmethod
    def _u64_to_lsb_uint8_array4(value: int) -> bytes:
        """Convert 64-bit integer to 4-byte LSB array (matching TypeScript)"""
        if value < 0 or value > 0xFFFFFFFFFFFFFFFF:
            raise ValueError("Value must be an unsigned 64-bit integer")
        
        return value.to_bytes(4, byteorder='little')
    
    async def connect(self, serial: int, disconnect_callback: Optional[Callable] = None):
        """Connect to BLE device with given serial number using manufacturer data filtering"""
        self.door_serial = serial
        self.disconnect_callback = disconnect_callback
        
        # Create manufacturer data filter (matching TypeScript logic)
        dfu_flag = 0x08
        installable_flag = 0x01
        flag_mask = dfu_flag | installable_flag
        
        # Build data prefix: [0x00,0x00,0x00] + 4 bytes serial + [0x00,0x00,0x00,0x00,0x00]
        serial_bytes = self._u64_to_lsb_uint8_array4(serial)
        data_prefix = bytes([0x00, 0x00, 0x00]) + serial_bytes + bytes([0x00, 0x00, 0x00, 0x00, 0x00])
        mask = bytes([0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0x00, flag_mask])
        
        log.info(f"Scanning for BLE device with serial {serial}")
        log.info(f"Looking for manufacturer data: {data_prefix.hex()}")
        log.info(f"Using mask: {mask.hex()}")
        
        # Create filter function for manufacturer data matching
        def device_filter(device, advertisement_data):
            # Check if device has our company ID in manufacturer data
            if self.COMPANY_ID in advertisement_data.manufacturer_data:
                mfg_data = advertisement_data.manufacturer_data[self.COMPANY_ID]
                log.info(f"Found device {device.name} ({device.address}) with manufacturer data: {mfg_data.hex()}")
                
                # Check if manufacturer data matches our filter
                if len(mfg_data) >= len(data_prefix):
                    # Apply mask to check if serial number matches
                    for i in range(len(mask)):
                        if i < len(mfg_data) and mask[i] != 0:
                            if (mfg_data[i] & mask[i]) != (data_prefix[i] & mask[i]):
                                return False
                    
                    log.info(f"Device {device.name} matches serial {serial}")
                    return True
            return False
        
        # Find device using filter
        target_device = await BleakScanner.find_device_by_filter(device_filter, timeout=15.0)
             
        if not target_device:
            raise ConnectionError(f"Could not find BLE device with serial {serial} using manufacturer data filtering")
            
        log.info(f"Connecting to device: {target_device.name} ({target_device.address})")
        
        self.client = BleakClient(target_device, disconnected_callback=self._on_disconnect)
        await self.client.connect()
        
        # Start notifications for RX characteristic
        await self.client.start_notify(self.UART_RX_UUID, self._on_data_received)
        
        log.info(f"Connected to BLE device {target_device.name}")
        
    async def disconnect(self):
        """Disconnect from BLE device"""
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            
    async def write_tx(self, data: bytes):
        """Write data to TX characteristic"""
        if not self.client or not self.client.is_connected:
            raise ConnectionError("Not connected to BLE device")
            
        await self.client.write_gatt_char(self.UART_TX_UUID, data)
        log.info(f"🛜 Sent: 0x{data.hex().upper()}")
        
    def _on_disconnect(self, client: BleakClient):
        """Called when device disconnects"""
        log.info("BLE device disconnected")
        if self.disconnect_callback:
            self.disconnect_callback()
            
    def _on_data_received(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Called when data is received from device"""
        log.info(f"🛜 Received: 0x{data.hex().upper()}")
        
        # Send data to REST API
        asyncio.create_task(self._handle_received_data(list(data)))
        
    async def _handle_received_data(self, message: list[int]):
        """Handle received data by posting to REST API"""
        if not self.door_serial:
            log.error("No door serial set")
            return
            
        payload = {
            "message": message
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_base_url}/_r/homekey_ble_message_received",
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        await self._handle_api_response(data)
                    else:
                        log.error(f"API request failed with status {response.status}")
                        
        except Exception as e:
            log.error(f"Error posting to API: {e}")
            
    async def _handle_api_response(self, data: Dict[str, Any]):
        """Handle response from REST API"""
        try:
            await self.handle_bluetooth_operation(data)
        except Exception as e:
            log.error(f"Error handling API response: {e}")
            
    async def handle_bluetooth_operation(self, operation: Dict[str, Any]):
        """Handle Bluetooth operation based on API response"""
        tag = operation.get("tag")
        
        if tag == "send_bluetooth_message":
            data = operation.get("data", [])
            await self.write_tx(bytes(data))
            
        elif tag == "close_bluetooth_connection":
            await self.disconnect()
                            
        else:
            log.warning(f"Unknown operation tag: {tag}")


class BLELockManager:
    """Manager for multiple BLE lock connections"""
    
    def __init__(self, api_base_url: str = "http://localhost:8080"):
        self.api_base_url = api_base_url
        self.connections: Dict[int, BLELockClient] = {}
        
    async def initiate_connection(self, serial: int, initial_message: list[int]):
        """Initiate connection to lock and send initial message"""
        if serial in self.connections:
            log.info(f"Already connected to device {serial}")
            client = self.connections[serial]
        else:
            client = BLELockClient(self.api_base_url)
            
            def on_disconnect():
                if serial in self.connections:
                    del self.connections[serial]
                    
            await client.connect(serial, on_disconnect)
            self.connections[serial] = client
            
        if initial_message:
            await client.write_tx(bytes(initial_message))
            
        return client
        
    async def disconnect_all(self):
        """Disconnect all active connections"""
        for client in list(self.connections.values()):
            await client.disconnect()
        self.connections.clear()
        
    async def get_connection(self, serial: int) -> Optional[BLELockClient]:
        """Get existing connection for serial number"""
        return self.connections.get(serial) 