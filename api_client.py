import asyncio
import logging
from typing import Dict, Any, Optional, Tuple
import aiohttp
import json

log = logging.getLogger(__name__)


class LockAPIClient:
    """Client for communicating with the lock control REST API"""
    
    def __init__(self, api_base_url: str = "http://localhost:8080"):
        self.api_base_url = api_base_url.rstrip('/')
        
    async def initiate_lock_activation(self, endpoint_id: str) -> Optional[Tuple[int, list[int]]]:
        """
        Initiate lock activation sequence.
        
        Returns:
            Tuple of (serial, initial_message) if successful, None if failed
        """
        payload = {
            "endpointId": endpoint_id
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_base_url}/_r/homekey_authenticated",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Expected response format:
                        # {
                        #   "tag": "initiate_bluetooth_connection",
                        #   "data": {
                        #     "serial": 12345,
                        #     "message": [0x01, 0x02, 0x03, ...]
                        #   }
                        # }
                        
                        if data.get("tag") == "initiate_bluetooth_connection":
                            connection_data = data.get("data", {})
                            serial = connection_data.get("serial")
                            message = connection_data.get("message", [])
                            
                            if serial is not None and message:
                                log.info(f"API returned initiation data for serial {serial}")
                                return serial, message
                                
                        log.error(f"Unexpected API response format: {data}")
                        return None
                        
                    else:
                        log.error(f"API request failed with status {response.status}")
                        response_text = await response.text()
                        log.error(f"Response: {response_text}")
                        return None
                        
        except asyncio.TimeoutError:
            log.error("API request timed out")
            return None
        except Exception as e:
            log.error(f"Error calling lock activation API: {e}")
            return None
            
 