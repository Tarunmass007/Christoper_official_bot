"""
Bulletproof HTTP Session with Playwright Support
================================================
Professional async HTTP client with multiple backends for maximum reliability.
Uses Playwright for bulletproof requests, falls back to curl_cffi, then aiohttp.
"""

import asyncio
import aiohttp
from typing import Optional, Dict, Any
import random
import os

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("[BulletproofSession] Playwright not available, using fallback")

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    CURL_CFFI_AVAILABLE = True
except (ImportError, Exception):
    CURL_CFFI_AVAILABLE = False

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    raise ImportError("aiohttp is required")


class BulletproofSession:
    """
    Bulletproof HTTP session with multiple backends.
    Priority: Playwright > curl_cffi > aiohttp
    """
    
    def __init__(
        self,
        timeout_seconds: Optional[float] = 60.0,
        proxy: Optional[str] = None,
        use_playwright: bool = False,  # Default to False - use curl_cffi for better performance
    ):
        self.timeout = timeout_seconds or 60.0
        self.proxy = proxy
        self.use_playwright = use_playwright and PLAYWRIGHT_AVAILABLE
        
        # Backend selection
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._curl_session = None
        self._aiohttp_session = None
        
    async def __aenter__(self):
        """Initialize session with best available backend."""
        # Priority:
        # - curl_cffi (best TLS fingerprinting, fast)
        # - Playwright (most human-like but heavy; requires browser binaries)
        # - aiohttp (last resort)

        async def _init_curl() -> bool:
            if not CURL_CFFI_AVAILABLE:
                return False
            try:
                self._curl_session = CurlAsyncSession(
                    timeout=self.timeout,
                    proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None,
                    impersonate="chrome120",
                )
                return True
            except Exception as e:
                print(f"[BulletproofSession] curl_cffi init failed: {e}")
                return False

        # If Playwright not requested, prefer curl immediately
        if not self.use_playwright:
            if await _init_curl():
                return self

        # If Playwright requested, try it; if it fails (missing browser), fall back to curl_cffi then aiohttp.
        if self.use_playwright:
            try:
                self._playwright = await async_playwright().start()
                browser_type = self._playwright.chromium

                # If browser binaries are not installed in the container, DO NOT attempt launch.
                # Launching would print Playwright's big "download new browsers" banner to stdout.
                try:
                    executable_path = getattr(browser_type, "executable_path", None)
                    if executable_path and not os.path.exists(executable_path):
                        # Silent fallback
                        self.use_playwright = False
                        try:
                            await self._playwright.stop()
                        except Exception:
                            pass
                        self._playwright = None
                        # Try curl after Playwright skip
                        if await _init_curl():
                            return self
                        # Continue to aiohttp fallback below
                        raise RuntimeError("Playwright browsers not installed")
                except Exception:
                    # If we can't validate executable path, proceed to launch and let fallback handle it.
                    pass

                launch_options = {
                    "headless": True,
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                    ],
                }
                if self.proxy:
                    launch_options["proxy"] = {"server": self.proxy}

                self._browser = await browser_type.launch(**launch_options)

                context_options = {
                    "viewport": {"width": 1920, "height": 1080},
                    "user_agent": self._get_random_user_agent(),
                    "locale": "en-US",
                    "timezone_id": "America/New_York",
                }
                self._context = await self._browser.new_context(**context_options)
                self._page = await self._context.new_page()

                await self._page.add_init_script(
                    """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    window.chrome = {runtime: {}};
                    """
                )

                return self
            except Exception as e:
                # Common container issue: Playwright browsers not installed
                # Keep this quiet in production to avoid log spam; we fallback automatically.
                self.use_playwright = False
                # Clean up partially-initialized playwright objects
                try:
                    if self._browser:
                        await self._browser.close()
                except Exception:
                    pass
                try:
                    if self._playwright:
                        await self._playwright.stop()
                except Exception:
                    pass
                self._browser = None
                self._context = None
                self._page = None
                self._playwright = None

                # Try curl after Playwright failure
                if await _init_curl():
                    return self

        # Final fallback: aiohttp
        timeout = aiohttp.ClientTimeout(total=self.timeout, connect=20.0, sock_read=30.0)
        connector = aiohttp.TCPConnector(
            ssl=False,
            limit=200,
            limit_per_host=50,
            ttl_dns_cache=600,
            force_close=False,
            enable_cleanup_closed=True,
            keepalive_timeout=30,
            use_dns_cache=True,
        )
        
        self._aiohttp_session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={"Connection": "keep-alive"},
            raise_for_status=False,
        )
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup all resources."""
        if self._page:
            try:
                await self._page.close()
            except:
                pass
        if self._context:
            try:
                await self._context.close()
            except:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except:
                pass
        if self._curl_session:
            try:
                await self._curl_session.close()
            except:
                pass
        if self._aiohttp_session:
            try:
                await self._aiohttp_session.close()
            except:
                pass
    
    def _get_random_user_agent(self) -> str:
        """Get random realistic user agent."""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
        return random.choice(user_agents)
    
    async def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> "BulletproofResponse":
        """Make GET request with retry logic."""
        max_retries = 3

        # Normalize common cross-client kwargs
        # Callers in this repo use: follow_redirects=..., timeout=...
        follow_redirects = kwargs.pop("follow_redirects", True)
        # aiohttp uses allow_redirects; curl_cffi uses allow_redirects; Playwright handles redirects itself.
        allow_redirects = kwargs.pop("allow_redirects", follow_redirects)
        # Avoid passing timeout twice (caller may provide timeout=)
        request_timeout = kwargs.pop("timeout", self.timeout)
        
        for retry in range(max_retries):
            try:
                if self._curl_session:
                    # Use curl_cffi (best TLS fingerprinting, good performance)
                    response = await self._curl_session.get(
                        url,
                        headers=headers,
                        params=params,
                        timeout=request_timeout,
                        allow_redirects=allow_redirects,
                        **kwargs
                    )
                    return BulletproofResponse(
                        status_code=response.status_code,
                        text=response.text,
                        json_data=response.json() if response.headers.get("content-type", "").startswith("application/json") else None,
                        headers=dict(response.headers),
                    )
                
                elif self.use_playwright and self._page:
                    # Use Playwright (most bulletproof but heavy)
                    # For API endpoints, use request API; for pages, use goto
                    if "/products.json" in url or "/api/" in url or "/graphql" in url:
                        # API endpoint - use request API
                        response = await self._page.request.get(
                            url,
                            headers=headers,
                            params=params,
                            timeout=int(self.timeout * 1000),
                        )
                        text = await response.text()
                        json_data = None
                        try:
                            if "application/json" in response.headers.get("content-type", ""):
                                json_data = await response.json()
                        except:
                            pass
                        
                        return BulletproofResponse(
                            status_code=response.status,
                            text=text,
                            json_data=json_data,
                            headers=response.headers,
                        )
                    else:
                        # Regular page - use goto
                        response = await self._page.goto(
                            url,
                            wait_until="networkidle",
                            timeout=int(self.timeout * 1000),
                        )
                        if response:
                            text = await self._page.content()
                            status = response.status
                            headers_dict = response.headers
                            
                            return BulletproofResponse(
                                status_code=status,
                                text=text,
                                json_data=None,
                                headers=headers_dict,
                            )
                
                else:
                    # Use aiohttp (final fallback)
                    async with self._aiohttp_session.get(
                        url,
                        headers=headers,
                        params=params,
                        proxy=self.proxy,
                        allow_redirects=allow_redirects,
                        ssl=False,
                        timeout=request_timeout,
                        **kwargs
                    ) as resp:
                        text = await resp.text()
                        json_data = None
                        try:
                            if "application/json" in resp.headers.get("content-type", ""):
                                json_data = await resp.json()
                        except:
                            pass
                        
                        return BulletproofResponse(
                            status_code=resp.status,
                            text=text,
                            json_data=json_data,
                            headers=dict(resp.headers),
                        )
            
            except Exception as e:
                if retry < max_retries - 1:
                    await asyncio.sleep(0.5 * (2 ** retry))
                    continue
                # Return error response
                return BulletproofResponse(
                    status_code=0,
                    text=f"BP_ERROR[{type(e).__name__}]: {str(e)[:140]}",
                    json_data=None,
                    headers={},
                )
    
    async def post(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Any] = None,
        json: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> "BulletproofResponse":
        """Make POST request with retry logic."""
        max_retries = 3

        # Normalize common cross-client kwargs
        follow_redirects = kwargs.pop("follow_redirects", True)
        allow_redirects = kwargs.pop("allow_redirects", follow_redirects)
        request_timeout = kwargs.pop("timeout", self.timeout)
        
        for retry in range(max_retries):
            try:
                if self._curl_session:
                    # Use curl_cffi (best TLS fingerprinting, good performance)
                    response = await self._curl_session.post(
                        url,
                        headers=headers,
                        data=data,
                        json=json,
                        timeout=request_timeout,
                        allow_redirects=allow_redirects,
                        **kwargs
                    )
                    return BulletproofResponse(
                        status_code=response.status_code,
                        text=response.text,
                        json_data=response.json() if response.headers.get("content-type", "").startswith("application/json") else None,
                        headers=dict(response.headers),
                    )
                
                elif self.use_playwright and self._page:
                    # Use Playwright (most bulletproof but heavy)
                    if json:
                        response = await self._page.request.post(
                            url,
                            headers=headers,
                            json=json,
                            timeout=int(self.timeout * 1000),
                        )
                    else:
                        response = await self._page.request.post(
                            url,
                            headers=headers,
                            data=data,
                            timeout=int(self.timeout * 1000),
                        )
                    
                    text = await response.text()
                    json_data = None
                    try:
                        json_data = await response.json()
                    except:
                        pass
                    
                    return BulletproofResponse(
                        status_code=response.status,
                        text=text,
                        json_data=json_data,
                        headers=response.headers,
                    )
                
                elif self._aiohttp_session:
                    # Use aiohttp (final fallback)
                    async with self._aiohttp_session.post(
                        url,
                        headers=headers,
                        data=data,
                        json=json,
                        proxy=self.proxy,
                        allow_redirects=allow_redirects,
                        ssl=False,
                        timeout=request_timeout,
                        **kwargs
                    ) as resp:
                        text = await resp.text()
                        json_data = None
                        try:
                            if "application/json" in resp.headers.get("content-type", ""):
                                json_data = await resp.json()
                        except:
                            pass
                        
                        return BulletproofResponse(
                            status_code=resp.status,
                            text=text,
                            json_data=json_data,
                            headers=dict(resp.headers),
                        )
                else:
                    # No session available
                    return BulletproofResponse(
                        status_code=0,
                        text="Error: No session available",
                        json_data=None,
                        headers={},
                    )
            
            except Exception as e:
                if retry < max_retries - 1:
                    await asyncio.sleep(0.5 * (2 ** retry))
                    continue
                # Return error response
                return BulletproofResponse(
                    status_code=0,
                    text=f"BP_ERROR[{type(e).__name__}]: {str(e)[:140]}",
                    json_data=None,
                    headers={},
                )


class BulletproofResponse:
    """Response wrapper for BulletproofSession."""
    
    def __init__(
        self,
        status_code: int,
        text: str,
        json_data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.status_code = status_code
        self._text = text
        self._json = json_data
        self._headers = headers or {}
    
    @property
    def text(self) -> str:
        return self._text or ""
    
    def json(self) -> Any:
        return self._json
    
    @property
    def headers(self) -> Dict[str, str]:
        return self._headers
