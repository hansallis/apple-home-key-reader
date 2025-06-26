import copy
import hashlib
import json
import logging
import threading
import time
import asyncio
import aiohttp
from typing import List, Optional

from entity import Endpoint, Issuer
from repository import Repository

log = logging.getLogger()


class APIRepository(Repository):
    """API-based repository that reads and writes to a JSON endpoint"""

    _issuers: List[Issuer]

    def __init__(self, api_base_url: str, api_secret: Optional[str] = None, read_endpoint: str = "/_r/homekey_state_requested", store_endpoint: str = "/_r/homekey_state_updated"):
        # Don't call super().__init__ since we don't need file-based storage
        self.api_base_url = api_base_url.rstrip('/')
        self.api_secret = api_secret
        self.read_endpoint = read_endpoint
        self.store_endpoint = store_endpoint
        self.read_url = f"{self.api_base_url}{self.read_endpoint}"
        self.store_url = f"{self.api_base_url}{self.store_endpoint}"
        
        self._reader_private_key = bytes.fromhex("00" * 32)
        self._reader_identifier = bytes.fromhex("00" * 8)
        self._issuers = list()
        self._transaction_lock = threading.Lock()
        self._state_lock = threading.Lock()
        
        # Periodic reading setup
        self._read_timer = None
        self._stop_reading = threading.Event()
        
        # Initial data load
        self._load_state_from_api()
        self._start_periodic_reading()

    def _start_periodic_reading(self):
        """Start periodic reading from API every minute"""
        def _periodic_read():
            while not self._stop_reading.wait(60):  # Read every minute
                try:
                    self._load_state_from_api()
                except Exception as e:
                    log.warning(f"Failed to read from API during periodic update: {e}")
        
        self._read_thread = threading.Thread(target=_periodic_read, daemon=True)
        self._read_thread.start()

    def _stop_periodic_reading(self):
        """Stop periodic reading"""
        self._stop_reading.set()
        if hasattr(self, '_read_thread'):
            self._read_thread.join(timeout=5)

    def _load_state_from_api(self):
        """Load state from API endpoint using POST request"""
        try:
            with self._state_lock:
                configuration = asyncio.run(self._async_load_state())
                if configuration is not None:
                    self._reader_private_key = bytes.fromhex(
                        configuration.get("reader_private_key", "00" * 32)
                    )
                    self._reader_identifier = bytes.fromhex(
                        configuration.get("reader_identifier", "00" * 8)
                    )
                    self._issuers = [
                        Issuer.from_dict(issuer)
                        for _, issuer in configuration.get("issuers", {}).items()
                    ]
                    log.debug("Successfully loaded state from API")
        except Exception as e:
            log.exception(f"Unexpected error loading from API: {e}")

    async def _async_load_state(self):
        """Async helper to load state from API"""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            headers = {'Content-Type': 'application/json'}
            if self.api_secret:
                headers['Authorization'] = f"Bearer {self.api_secret}"
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.read_url,
                    json={},
                    headers=headers
                ) as response:
                    response.raise_for_status()
                    return await response.json()
        except aiohttp.ClientError as e:
            log.warning(f"Could not load Home Key configuration from API: {e}")
            return None
        except json.JSONDecodeError as e:
            log.error(f"Invalid JSON response from API: {e}")
            return None

    def _save_state_to_api(self):
        """Save state to API endpoint using POST request"""
        try:
            with self._state_lock:
                data = {
                    "reader_private_key": self._reader_private_key.hex(),
                    "reader_identifier": self._reader_identifier.hex(),
                    "issuers": {
                        issuer.id.hex(): issuer.to_dict() for issuer in self._issuers
                    },
                }
                
                success = asyncio.run(self._async_save_state(data))
                if success:
                    log.debug("Successfully saved state to API")
        except Exception as e:
            log.exception(f"Unexpected error saving to API: {e}")

    async def _async_save_state(self, data):
        """Async helper to save state to API"""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            headers = {'Content-Type': 'application/json'}
            if self.api_secret:
                headers['Authorization'] = f"Bearer {self.api_secret}"
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.store_url,
                    json=data,
                    headers=headers
                ) as response:
                    response.raise_for_status()
                    return True
        except aiohttp.ClientError as e:
            log.error(f"Could not save Home Key configuration to API: {e}")
            return False

    def _refresh_state(self):
        """Save state to API (no need to reload since we have the latest state)"""
        self._save_state_to_api()

    def get_reader_private_key(self):
        return self._reader_private_key

    def set_reader_private_key(self, reader_private_key):
        with self._transaction_lock:
            self._reader_private_key = reader_private_key
            self._refresh_state()

    def get_reader_identifier(self):
        return self._reader_identifier

    def set_reader_identifier(self, reader_identifier):
        with self._transaction_lock:
            self._reader_identifier = reader_identifier
            self._refresh_state()

    def get_reader_group_identifier(self):
        return (
            hashlib.sha256("key-identifier".encode() + self.get_reader_private_key())
        ).digest()[:8]

    def get_all_issuers(self):
        return copy.deepcopy([i for i in self._issuers])

    def get_all_endpoints(self):
        return copy.deepcopy(
            [endpoint for issuer in self._issuers for endpoint in issuer.endpoints]
        )

    def get_endpoint_by_public_key(self, public_key: bytes) -> Optional[Endpoint]:
        return next(
            (
                endpoint
                for endpoint in self.get_all_endpoints()
                if endpoint.public_key == public_key
            ),
            None,
        )

    def get_endpoint_by_id(self, id) -> Optional[Endpoint]:
        return next(
            (endpoint for endpoint in self.get_all_endpoints() if endpoint.id == id),
            None,
        )

    def get_issuer_by_public_key(self, public_key) -> Optional[Issuer]:
        return next(
            (
                issuer
                for issuer in self.get_all_issuers()
                if issuer.public_key == public_key
            ),
            None,
        )

    def get_issuer_by_id(self, id) -> Optional[Issuer]:
        return next(
            (issuer for issuer in self.get_all_issuers() if issuer.id == id), None
        )

    def get_issuer_by_endpoint(self, endpoint: Endpoint) -> Optional[Issuer]:
        return next(
            (issuer for issuer in self.get_all_issuers() 
             if any(ep.id == endpoint.id for ep in issuer.endpoints)), None
        )

    def remove_issuer(self, issuer: Issuer):
        with self._transaction_lock:
            issuers = [i for i in copy.deepcopy(self._issuers) if i.id != issuer.id]
            self._issuers = issuers
            self._refresh_state()

    def upsert_issuer(self, issuer: Issuer):
        with self._transaction_lock:
            issuer = copy.deepcopy(issuer)
            issuers = [
                (i if i.id != issuer.id else issuer)
                for i in copy.deepcopy(self._issuers)
            ]
            if issuer not in issuers:
                issuers.append(issuer)
            self._issuers = issuers
            self._refresh_state()

    def upsert_endpoint(self, issuer_id, endpoint: Endpoint):
        with self._transaction_lock:
            issuer = next(
                (issuer for issuer in self._issuers if issuer.id == issuer_id), None
            )
            if issuer is None:
                return
            endpoints = [
                (e if e.id != endpoint.id else endpoint) for e in issuer.endpoints
            ]
            if endpoint not in endpoints:
                endpoints.append(endpoint)
            issuer.endpoints = endpoints
            self._refresh_state()

    def upsert_issuers(self, issuers: List[Issuer]):
        issuers_dict = {issuer.id: copy.deepcopy(issuer) for issuer in issuers}
        with self._transaction_lock:
            iss = [issuers_dict.get(i.id, i) for i in copy.deepcopy(self._issuers)]
            for issuer in issuers_dict.values():
                if issuer not in iss:
                    iss.append(issuer)
            self._issuers = iss
            self._refresh_state()

    def __del__(self):
        """Cleanup periodic reading on destruction"""
        self._stop_periodic_reading() 