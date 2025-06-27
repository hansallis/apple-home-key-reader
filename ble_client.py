import asyncio
import logging
import json
import time
from typing import Optional, Callable, Dict, Any, List, Union
import aiohttp
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic

log = logging.getLogger(__name__)


class DeviceInfo:
    """Information about a discovered BLE device"""
    def __init__(self, device: BLEDevice, serial: int, last_seen: float):
        self.device = device
        self.serial = serial
        self.last_seen = last_seen
        
    def is_stale(self, max_age_seconds: float = 300) -> bool:
        """Check if device info is stale (older than max_age_seconds)"""
        return time.time() - self.last_seen > max_age_seconds


class BLEDeviceRegistry:
    """Registry for discovered BLE devices to reduce connection times"""
    
    # Company ID for manufacturer data filtering
    COMPANY_ID = 0x065B
    
    def __init__(self, scan_interval: float = 30.0, device_ttl: float = 300.0):
        self.devices: Dict[int, DeviceInfo] = {}  # serial -> DeviceInfo
        self.scan_interval = scan_interval
        self.device_ttl = device_ttl
        self._scanning = False
        self._scan_task: Optional[asyncio.Task] = None
        
    @staticmethod
    def _u64_to_lsb_uint8_array4(value: int) -> bytes:
        """Convert 64-bit integer to 4-byte LSB array (matching TypeScript)"""
        if value < 0 or value > 0xFFFFFFFFFFFFFFFF:
            raise ValueError("Value must be an unsigned 64-bit integer")
        
        return value.to_bytes(4, byteorder='little')
        
    def _extract_serial_from_manufacturer_data(self, mfg_data: bytes) -> Optional[int]:
        """Extract serial number from manufacturer data"""
        if len(mfg_data) < 7:  # Need at least 3 + 4 bytes for serial
            return None
            
        # Serial is in bytes 3-6 (4 bytes, little endian)
        serial_bytes = mfg_data[3:7]
        serial = int.from_bytes(serial_bytes, byteorder='little')
        
        # Debug logging for development
        log.debug(f"Extracted serial {serial} from bytes {serial_bytes.hex().upper()}")
        
        return serial
        
    def _matches_lock_device(self, mfg_data: bytes) -> bool:
        """Check if manufacturer data indicates this is a lock device"""
        if len(mfg_data) < 7:  # Need at least 3 prefix + 4 serial bytes
            return False
            
        # For now, let's be more permissive and just check if we can extract a serial
        # The original TypeScript logic might have been more specific than needed
        # We'll validate the pattern based on having a reasonable serial number structure
        
        # Check if bytes 3-6 look like a valid serial (not all zeros)
        serial_bytes = mfg_data[3:7] if len(mfg_data) >= 7 else b'\x00\x00\x00\x00'
        serial = int.from_bytes(serial_bytes, byteorder='little')
        
        # Accept devices that have a non-zero serial number
        # This is more permissive than the original flag checking
        is_valid = serial != 0
        
        log.debug(f"Lock device validation: serial={serial}, valid={is_valid}")
        
        return is_valid
        
    async def start_scanning(self):
        """Start continuous background scanning for devices"""
        if self._scanning:
            return
            
        log.info("🚀 Starting BLE device registry")
        
        self._scanning = True
        self._scan_task = asyncio.create_task(self._scan_loop())
        
    async def stop_scanning(self):
        """Stop background scanning"""
        self._scanning = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
        log.info("🛑 Stopped BLE device registry")
        
    async def _scan_loop(self):
        """Continuous scanning loop"""
        while self._scanning:
            try:
                await self._perform_scan()
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"BLE scan error: {e}")
                await asyncio.sleep(5)  # Short delay before retrying
                
    async def _perform_scan(self):
        """Perform a single scan for devices"""
        def detection_callback(device: BLEDevice, advertisement_data):
            # Check if device has our company ID in manufacturer data
            if self.COMPANY_ID in advertisement_data.manufacturer_data:
                mfg_data = advertisement_data.manufacturer_data[self.COMPANY_ID]
                
                # Check if this looks like a lock device
                if self._matches_lock_device(mfg_data):
                    serial = self._extract_serial_from_manufacturer_data(mfg_data)
                    
                    if serial is not None:
                        # Only log if this is a new device
                        if serial not in self.devices:
                            log.info(f"🔐 Discovered lock device: {device.name or 'Unknown'} (serial {serial})")
                        
                        current_time = time.time()
                        self.devices[serial] = DeviceInfo(device, serial, current_time)
        
        # Scan for 5 seconds
        async with BleakScanner(detection_callback=detection_callback) as scanner:
            await asyncio.sleep(5.0)
            
        # Clean up stale devices
        self._cleanup_stale_devices()
        
    def _cleanup_stale_devices(self):
        """Remove devices that haven't been seen recently"""
        stale_serials = [
            serial for serial, info in self.devices.items() 
            if info.is_stale(self.device_ttl)
        ]
        
        for serial in stale_serials:
            device_info = self.devices[serial]
            del self.devices[serial]
            log.info(f"🗑️ Pruned stale device: {device_info.device.name or 'Unknown'} (serial {serial})")
            
    def get_device(self, serial: int) -> Optional[BLEDevice]:
        """Get a cached device by serial number"""
        device_info = self.devices.get(serial)
        if device_info and not device_info.is_stale(self.device_ttl):
            return device_info.device
        return None
        
    def list_available_devices(self) -> List[int]:
        """Get list of available device serial numbers"""
        return [
            serial for serial, info in self.devices.items()
            if not info.is_stale(self.device_ttl)
        ]
        
    async def force_refresh(self, serial: int) -> Optional[BLEDevice]:
        """Force a refresh scan for a specific device"""
        await self._perform_scan()
        return self.get_device(serial)


class BLELockClient:
    """BLE client for communicating with lock devices"""
    
    # Service and characteristic UUIDs (matching TypeScript)
    SESAME_SERVICE_UUID = "0000fd30-0000-1000-8000-00805f9b34fb"
    UART_TX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # Write to this
    UART_RX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # Notifications from this
    
    def __init__(self, api_base_url: str = "http://localhost:8080", device_registry: Optional[BLEDeviceRegistry] = None, issuer_id: Optional[str] = None):
        self.client: Optional[BleakClient] = None
        self.api_base_url = api_base_url
        self.door_serial: Optional[int] = None
        self.disconnect_callback: Optional[Callable] = None
        self.device_registry = device_registry
        self.issuer_id = issuer_id
        
    async def connect(self, serial: int, disconnect_callback: Optional[Callable] = None):
        """Connect to BLE device with given serial number"""
        self.door_serial = serial
        self.disconnect_callback = disconnect_callback
        
        # Try to get device from registry first
        target_device = None
        if self.device_registry:
            target_device = self.device_registry.get_device(serial)
            if not target_device:
                target_device = await self.device_registry.force_refresh(serial)
        
        # Fall back to manual scanning if not found in registry
        if not target_device:
            target_device = await self._manual_scan_for_device(serial)
             
        if not target_device:
            raise ConnectionError(f"Could not find BLE device with serial {serial}")
            
        log.info(f"Connecting to device: {target_device.name} ({target_device.address})")
        
        self.client = BleakClient(target_device, disconnected_callback=self._on_disconnect)
        await self.client.connect()
        
        # Start notifications for RX characteristic
        await self.client.start_notify(self.UART_RX_UUID, self._on_data_received)
        
        log.info(f"Connected to BLE device {target_device.name}")
        
    async def _manual_scan_for_device(self, serial: int) -> Optional[BLEDevice]:
        """Manual scan for a specific device (fallback when registry doesn't have it)"""
        # Create manufacturer data filter (matching TypeScript logic)
        dfu_flag = 0x08
        installable_flag = 0x01
        flag_mask = dfu_flag | installable_flag
        
        # Build data prefix: [0x00,0x00,0x00] + 4 bytes serial + [0x00,0x00,0x00,0x00,0x00]
        serial_bytes = BLEDeviceRegistry._u64_to_lsb_uint8_array4(serial)
        data_prefix = bytes([0x00, 0x00, 0x00]) + serial_bytes + bytes([0x00, 0x00, 0x00, 0x00, 0x00])
        mask = bytes([0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0x00, flag_mask])
        
        log.debug(f"Manual scanning for BLE device with serial {serial}")
        
        # Create filter function for manufacturer data matching
        def device_filter(device, advertisement_data):
            # Check if device has our company ID in manufacturer data
            if BLEDeviceRegistry.COMPANY_ID in advertisement_data.manufacturer_data:
                mfg_data = advertisement_data.manufacturer_data[BLEDeviceRegistry.COMPANY_ID]
                
                # Check if manufacturer data matches our filter
                if len(mfg_data) >= len(data_prefix):
                    # Apply mask to check if serial number matches
                    for i in range(len(mask)):
                        if i < len(mfg_data) and mask[i] != 0:
                            if (mfg_data[i] & mask[i]) != (data_prefix[i] & mask[i]):
                                return False
                    
                    log.debug(f"Device {device.name} matches serial {serial}")
                    return True
            return False
        
        # Use detection callback approach for scanning  
        target_device = None
        found_event = asyncio.Event()
        
        def detection_callback(device: BLEDevice, advertisement_data):
            nonlocal target_device
            if device_filter(device, advertisement_data):
                target_device = device
                found_event.set()
        
        scanner = BleakScanner(detection_callback=detection_callback)
        await scanner.start()
        
        try:
            # Wait up to 15 seconds for device to be found
            await asyncio.wait_for(found_event.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            pass  # target_device will remain None
        finally:
            await scanner.stop()
        
        return target_device
        
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
            
        payload: Dict[str, Union[list[int], str]] = {
            "message": message
        }
        
        # Include issuer_id if available
        if self.issuer_id:
            payload["issuerId"] = self.issuer_id
        
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
    """Manager for multiple BLE lock connections with device registry"""
    
    def __init__(self, api_base_url: str = "http://localhost:8080", enable_registry: bool = True):
        self.api_base_url = api_base_url
        self.connections: Dict[int, BLELockClient] = {}
        self.device_registry = BLEDeviceRegistry() if enable_registry else None
        
    async def start(self):
        """Start the manager and begin device scanning"""
        if self.device_registry:
            await self.device_registry.start_scanning()
            log.info("BLE Lock Manager started with device registry")
        else:
            log.info("BLE Lock Manager started without device registry")
            
    async def stop(self):
        """Stop the manager and all connections"""
        if self.device_registry:
            await self.device_registry.stop_scanning()
        await self.disconnect_all()
        log.info("BLE Lock Manager stopped")
        
    async def initiate_connection(self, serial: int, initial_message: list[int], issuer_id: Optional[str] = None):
        """Initiate connection to lock and send initial message"""
        if serial in self.connections:
            log.info(f"Already connected to device {serial}")
            client = self.connections[serial]
        else:
            client = BLELockClient(self.api_base_url, self.device_registry, issuer_id)
            
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
        
    def get_available_devices(self) -> List[int]:
        """Get list of available device serial numbers from registry"""
        if self.device_registry:
            return self.device_registry.list_available_devices()
        return [] 