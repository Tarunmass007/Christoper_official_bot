"""
TLS Async Session with Fingerprinting
======================================
Professional async HTTP client with TLS fingerprinting support.
Uses curl_cffi for browser-like TLS fingerprints to bypass detection.
"""

import asyncio
import aiohttp
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    CURL_CFFI_AVAILABLE = True
except (ImportError, Exception) as e:
    CURL_CFFI_AVAILABLE = False
    print(f"[TLSAsyncSession] curl_cffi not available: {e}")

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    print("[TLSAsyncSession] aiohttp not available")
    raise  # aiohttp is required

# Default client identifiers for TLS fingerprinting
DEFAULT_CLIENT_ID = "chrome120"
SUPPORTED_CLIENTS = [
    "chrome120", "chrome124", "chrome117",
    "firefox120", "safari16_0", "edge120"
]


class TLSAsyncSession:
    """
    Async HTTP session with TLS fingerprinting support.
    
    Features:
    - Browser-like TLS fingerprints (Chrome, Firefox, Safari, Edge)
    - Proxy support
    - Timeout configuration
    - Follow redirects option
    - Async context manager support
    
    Usage:
        async with TLSAsyncSession(timeout_seconds=60, proxy="http://proxy:port") as session:
            response = await session.get("https://example.com")
            data = response.json()
    """
    
    def __init__(
        self,
        timeout_seconds: Optional[float] = 60.0,
        proxy: Optional[str] = None,
        follow_redirects: bool = True,
        client_identifier: Optional[str] = None,
    ):
        """
        Initialize TLS Async Session.
        
        Args:
            timeout_seconds: Request timeout in seconds (default: 60)
            proxy: Proxy URL in format http://user:pass@host:port or http://host:port
            follow_redirects: Whether to follow HTTP redirects (default: True)
            client_identifier: TLS fingerprint identifier (chrome120, firefox120, etc.)
        """
        self.timeout = timeout_seconds
        self.proxy = proxy
        self.follow_redirects = follow_redirects
        self.client_id = client_identifier or DEFAULT_CLIENT_ID
        
        # Validate client identifier
        if self.client_id not in SUPPORTED_CLIENTS:
            # Try to map common variations
            client_map = {
                "chrome_120": "chrome120",
                "chrome_124": "chrome124",
                "chrome_117": "chrome117",
                "firefox_120": "firefox120",
                "safari_16_0": "safari16_0",
            }
            self.client_id = client_map.get(self.client_id, DEFAULT_CLIENT_ID)
        
        self._session = None
        # Prefer aiohttp if curl_cffi is not available or unreliable
        self._use_curl_cffi = CURL_CFFI_AVAILABLE and AIOHTTP_AVAILABLE  # Only use curl_cffi if both are available (fallback safety)
    
    async def __aenter__(self):
        """Async context manager entry."""
        # Always use aiohttp for reliability (curl_cffi can be unstable)
        # aiohttp is more stable and works better in production environments
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp is required. Please install: pip install aiohttp"
            )
        
        timeout = aiohttp.ClientTimeout(total=self.timeout or 60.0, connect=20.0, sock_read=30.0)
        # Use TCPConnector with better settings for reliability and connection stability
        connector = aiohttp.TCPConnector(
            ssl=False,
            limit=200,  # Higher connection limit for better throughput
            limit_per_host=50,  # More connections per host
            ttl_dns_cache=600,  # Longer DNS cache TTL (10 minutes)
            force_close=False,  # Keep connections alive for reuse
            enable_cleanup_closed=True,  # Auto-cleanup closed connections
            keepalive_timeout=30,  # Keep connections alive for 30s
            use_dns_cache=True,  # Enable DNS caching
        )
        
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={
                "Connection": "keep-alive",
            },
            raise_for_status=False,  # Don't raise on HTTP errors, handle manually
        )
        self._proxy = self.proxy
        self._use_curl_cffi = False  # Use aiohttp for reliability
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._session:
            try:
                await self._session.close()
            except Exception as e:
                print(f"[TLSAsyncSession] Error closing session: {e}")
            finally:
                self._session = None
    
    async def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> "TLSResponse":
        """
        Make GET request.
        
        Args:
            url: Target URL
            headers: Optional request headers
            params: Optional query parameters
            **kwargs: Additional arguments (follow_redirects, timeout, etc.)
            
        Returns:
            TLSResponse object
        """
        if not self._session:
            raise RuntimeError("Session not initialized. Use 'async with' context manager.")
        
        # Convert follow_redirects to allow_redirects for aiohttp
        allow_redirects = kwargs.pop('follow_redirects', True)
        # Handle timeout - aiohttp uses timeout parameter or ClientTimeout
        timeout = kwargs.pop('timeout', None)
        if timeout:
            # Convert timeout to aiohttp.ClientTimeout
            if isinstance(timeout, (int, float)):
                timeout = aiohttp.ClientTimeout(total=float(timeout))
        
        # Build proxy dict for aiohttp
        proxy_url = None
        if self._proxy:
            proxy_url = self._proxy
        
        # Use per-request timeout if provided, otherwise use session timeout
        req_timeout = timeout
        if req_timeout and isinstance(req_timeout, (int, float)):
            req_timeout = aiohttp.ClientTimeout(
                total=float(req_timeout),
                connect=20.0,  # Longer connect timeout for stability
                sock_read=float(req_timeout) * 0.8  # Read timeout
            )
        elif not req_timeout:
            req_timeout = aiohttp.ClientTimeout(
                total=self.timeout or 60.0,
                connect=20.0,
                sock_read=30.0
            )
        
        # Retry logic for connection errors
        max_retries = 3
        last_exception = None
        
        for retry in range(max_retries):
            try:
                async with self._session.get(
                    url,
                    headers=headers or {},
                    params=params,
                    proxy=proxy_url,
                    allow_redirects=allow_redirects,
                    timeout=req_timeout,
                    ssl=False,  # Disable SSL verification for compatibility
                    **kwargs
                ) as resp:
                    text = await resp.text()
                    json_data = None
                    try:
                        json_data = await resp.json()
                    except:
                        pass
                    
                    return TLSResponse(
                        status_code=resp.status,
                        text=text,
                        json_data=json_data,
                        headers=dict(resp.headers)
                    )
            except (aiohttp.ClientConnectorError, aiohttp.ServerConnectionError, asyncio.TimeoutError) as e:
                last_exception = e
                if retry < max_retries - 1:
                    # Exponential backoff: 0.5s, 1s, 2s
                    await asyncio.sleep(0.5 * (2 ** retry))
                    continue
                # Final retry failed
                error_msg = str(e)
                status_code = 0
                if "timeout" in error_msg.lower() or isinstance(e, asyncio.TimeoutError):
                    status_code = 408  # Request Timeout
                return TLSResponse(
                    status_code=status_code,
                    text=f"Connection error: {error_msg[:100]}",
                    json_data=None,
                    headers={}
                )
            except (aiohttp.ClientError, Exception) as e:
                # For other errors, return immediately (no retry)
                error_msg = str(e)
                status_code = 0
                if "timeout" in error_msg.lower():
                    status_code = 408
                return TLSResponse(
                    status_code=status_code,
                    text=f"Error: {error_msg[:100]}",
                    json_data=None,
                    headers={}
                )
    
    async def post(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> "TLSResponse":
        """
        Make POST request.
        
        Args:
            url: Target URL
            headers: Optional request headers
            data: Optional form data
            json: Optional JSON data
            **kwargs: Additional arguments (follow_redirects, timeout, etc.)
            
        Returns:
            TLSResponse object
        """
        if not self._session:
            raise RuntimeError("Session not initialized. Use 'async with' context manager.")
        
        # Convert follow_redirects to allow_redirects for aiohttp
        allow_redirects = kwargs.pop('follow_redirects', True)
        # Handle timeout - aiohttp uses timeout parameter or ClientTimeout
        timeout = kwargs.pop('timeout', None)
        if timeout:
            # Convert timeout to aiohttp.ClientTimeout
            if isinstance(timeout, (int, float)):
                timeout = aiohttp.ClientTimeout(total=float(timeout))
        
        # Build proxy dict for aiohttp
        proxy_url = None
        if self._proxy:
            proxy_url = self._proxy
        
        # Use per-request timeout if provided, otherwise use session timeout
        req_timeout = timeout
        if req_timeout and isinstance(req_timeout, (int, float)):
            req_timeout = aiohttp.ClientTimeout(
                total=float(req_timeout),
                connect=20.0,  # Longer connect timeout for stability
                sock_read=float(req_timeout) * 0.8  # Read timeout
            )
        elif not req_timeout:
            req_timeout = aiohttp.ClientTimeout(
                total=self.timeout or 60.0,
                connect=20.0,
                sock_read=30.0
            )
        
        # Retry logic for connection errors
        max_retries = 3
        last_exception = None
        
        for retry in range(max_retries):
            try:
                async with self._session.post(
                    url,
                    headers=headers or {},
                    data=data,
                    json=json,
                    proxy=proxy_url,
                    allow_redirects=allow_redirects,
                    timeout=req_timeout,
                    ssl=False,  # Disable SSL verification for compatibility
                    **kwargs
                ) as resp:
                    text = await resp.text()
                    json_data = None
                    try:
                        json_data = await resp.json()
                    except:
                        pass
                    
                    return TLSResponse(
                        status_code=resp.status,
                        text=text,
                        json_data=json_data,
                        headers=dict(resp.headers)
                    )
            except (aiohttp.ClientConnectorError, aiohttp.ServerConnectionError, asyncio.TimeoutError) as e:
                last_exception = e
                if retry < max_retries - 1:
                    # Exponential backoff: 0.5s, 1s, 2s
                    await asyncio.sleep(0.5 * (2 ** retry))
                    continue
                # Final retry failed
                error_msg = str(e)
                status_code = 0
                if "timeout" in error_msg.lower() or isinstance(e, asyncio.TimeoutError):
                    status_code = 408  # Request Timeout
                return TLSResponse(
                    status_code=status_code,
                    text=f"Connection error: {error_msg[:100]}",
                    json_data=None,
                    headers={}
                )
            except (aiohttp.ClientError, Exception) as e:
                # For other errors, return immediately (no retry)
                error_msg = str(e)
                status_code = 0
                if "timeout" in error_msg.lower():
                    status_code = 408
                return TLSResponse(
                    status_code=status_code,
                    text=f"Error: {error_msg[:100]}",
                    json_data=None,
                    headers={}
                )


class TLSResponse:
    """
    Response wrapper for TLSAsyncSession requests.
    Provides unified interface for curl_cffi and aiohttp responses.
    """
    
    def __init__(
        self,
        response=None,
        status_code: Optional[int] = None,
        text: Optional[str] = None,
        json_data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize TLSResponse.
        
        Args:
            response: curl_cffi Response object (if using curl_cffi)
            status_code: HTTP status code (if using aiohttp)
            text: Response text (if using aiohttp)
            json_data: Parsed JSON data (if using aiohttp)
            headers: Response headers (if using aiohttp)
        """
        if response is not None:
            # curl_cffi response
            self._response = response
            self.status_code = response.status_code
            self._text = None
            self._json = None
            self._headers = response.headers
        else:
            # aiohttp response (fallback)
            self._response = None
            self.status_code = status_code or 200
            self._text = text
            self._json = json_data
            self._headers = headers or {}
    
    @property
    def text(self) -> str:
        """Get response text."""
        if self._response:
            return self._response.text
        return self._text or ""
    
    def json(self) -> Any:
        """Parse and return JSON response."""
        if self._response:
            return self._response.json()
        return self._json
    
    @property
    def headers(self) -> Dict[str, str]:
        """Get response headers."""
        if self._response:
            return dict(self._response.headers)
        return self._headers or {}
    
    @property
    def url(self) -> str:
        """Get final URL (after redirects)."""
        if self._response:
            return str(self._response.url)
        return ""
