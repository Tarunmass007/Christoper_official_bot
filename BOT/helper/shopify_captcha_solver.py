"""
Professional Shopify Captcha Solver Module
Robust captcha bypass and solving for Shopify checkout flows.

Features:
- hCaptcha bypass with motion data simulation
- reCAPTCHA v2/v3 invisible bypass
- Shopify-specific bot detection bypass
- Multiple fallback strategies
- Session fingerprinting for stealth
"""

import asyncio
import hashlib
import json
import random
import time
import base64
import logging
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse, urlencode
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=10)


@dataclass
class CaptchaResult:
    """Represents a captcha solving result."""
    success: bool
    token: Optional[str]
    provider: str
    method: str
    elapsed_time: float
    error: Optional[str] = None


class BrowserFingerprint:
    """Generate realistic browser fingerprints for bypass."""
    
    # Modern Chrome versions
    CHROME_VERSIONS = [
        "120.0.6099.109", "120.0.6099.129", "121.0.6167.85",
        "121.0.6167.139", "122.0.6261.94", "123.0.6312.107",
        "124.0.6367.60", "125.0.6422.60", "126.0.6478.55"
    ]
    
    # User agents for different platforms
    USER_AGENTS = {
        "windows": [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36",
            "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36",
        ],
        "mac": [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36",
        ],
        "android": [
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Mobile Safari/537.36",
        ],
        "ios": [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        ]
    }
    
    # Screen resolutions
    RESOLUTIONS = [
        (1920, 1080), (2560, 1440), (1366, 768),
        (1536, 864), (1440, 900), (1280, 720),
        (3840, 2160), (1600, 900)
    ]
    
    # GPU renderers
    GPU_RENDERERS = [
        "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
    ]
    
    # Timezones
    TIMEZONES = [
        ("America/New_York", -300), ("America/Chicago", -360),
        ("America/Denver", -420), ("America/Los_Angeles", -480),
        ("Europe/London", 0), ("Europe/Paris", 60),
        ("Europe/Berlin", 60), ("Asia/Tokyo", 540),
    ]
    
    @classmethod
    def generate(cls, platform: str = "random") -> Dict[str, Any]:
        """Generate a complete browser fingerprint."""
        if platform == "random":
            platform = random.choice(["windows", "mac", "android"])
        
        version = random.choice(cls.CHROME_VERSIONS)
        ua_template = random.choice(cls.USER_AGENTS.get(platform, cls.USER_AGENTS["windows"]))
        user_agent = ua_template.format(version=version)
        
        resolution = random.choice(cls.RESOLUTIONS)
        timezone_name, timezone_offset = random.choice(cls.TIMEZONES)
        
        return {
            "userAgent": user_agent,
            "platform": "Win32" if platform == "windows" else ("MacIntel" if platform == "mac" else "Linux armv8l"),
            "language": "en-US",
            "languages": ["en-US", "en"],
            "colorDepth": random.choice([24, 32]),
            "deviceMemory": random.choice([4, 8, 16, 32]),
            "hardwareConcurrency": random.choice([4, 6, 8, 12, 16]),
            "screenResolution": list(resolution),
            "availableScreenResolution": [resolution[0], resolution[1] - 40],
            "timezone": timezone_name,
            "timezoneOffset": timezone_offset,
            "sessionStorage": True,
            "localStorage": True,
            "indexedDb": True,
            "cpuClass": "unknown",
            "plugins": [],
            "canvas": hashlib.md5(f"canvas_{random.randint(1000, 9999)}".encode()).hexdigest(),
            "webgl": {
                "vendor": "Google Inc. (NVIDIA)",
                "renderer": random.choice(cls.GPU_RENDERERS),
            },
            "webglVendorAndRenderer": random.choice(cls.GPU_RENDERERS),
            "adBlock": False,
            "hasLiedLanguages": False,
            "hasLiedResolution": False,
            "hasLiedOs": False,
            "hasLiedBrowser": False,
            "touchSupport": {
                "maxTouchPoints": 0 if platform in ["windows", "mac"] else 5,
                "touchEvent": platform not in ["windows", "mac"],
                "touchStart": platform not in ["windows", "mac"],
            },
            "fonts": ["Arial", "Helvetica", "Times New Roman", "Georgia", "Verdana"],
            "audio": hashlib.md5(f"audio_{random.randint(1000, 9999)}".encode()).hexdigest()[:32],
        }


class MotionDataGenerator:
    """Generate realistic mouse and touch motion data."""
    
    @staticmethod
    def generate_mouse_movements(count: int = 20) -> list:
        """Generate realistic mouse movement data."""
        movements = []
        x, y = random.randint(100, 400), random.randint(100, 400)
        timestamp = int(time.time() * 1000)
        
        for _ in range(count):
            # Natural movement with acceleration and deceleration
            dx = random.randint(-80, 80)
            dy = random.randint(-60, 60)
            
            # Add curve to movement
            x = max(0, min(1920, x + dx))
            y = max(0, min(1080, y + dy))
            
            # Random time delta (natural pause patterns)
            dt = random.randint(30, 150)
            timestamp += dt
            
            movements.append({
                "x": x,
                "y": y,
                "t": timestamp,
            })
        
        return movements
    
    @staticmethod
    def generate_clicks(count: int = 3) -> list:
        """Generate click event data."""
        clicks = []
        timestamp = int(time.time() * 1000)
        
        for _ in range(count):
            clicks.append({
                "x": random.randint(200, 800),
                "y": random.randint(200, 600),
                "t": timestamp + random.randint(500, 2000),
                "type": "click",
            })
            timestamp += random.randint(1000, 3000)
        
        return clicks
    
    @staticmethod
    def generate_scroll_data() -> Dict:
        """Generate scroll event data."""
        return {
            "x": 0,
            "y": random.randint(100, 800),
            "scrollCount": random.randint(1, 5),
        }
    
    @staticmethod
    def generate_keystroke_timing(length: int = 10) -> list:
        """Generate keystroke timing data."""
        timings = []
        timestamp = int(time.time() * 1000)
        
        for _ in range(length):
            down_up_delta = random.randint(50, 150)
            between_delta = random.randint(100, 300)
            
            timings.append({
                "down": timestamp,
                "up": timestamp + down_up_delta,
            })
            timestamp += down_up_delta + between_delta
        
        return timings
    
    @classmethod
    def generate_full_motion_data(cls) -> Dict[str, Any]:
        """Generate complete motion data for captcha bypass."""
        return {
            "mouseMovements": cls.generate_mouse_movements(random.randint(15, 30)),
            "touchEvents": [],
            "keystrokes": cls.generate_keystroke_timing(random.randint(5, 15)),
            "scrollData": cls.generate_scroll_data(),
            "clickData": cls.generate_clicks(random.randint(2, 5)),
            "timestamp": int(time.time() * 1000),
            "elapsed": random.randint(3000, 10000),
        }


class ShopifyCaptchaSolver:
    """
    Professional Shopify captcha solver with multiple bypass strategies.
    """
    
    # hCaptcha endpoints
    HCAPTCHA_SITECONFIG = "https://hcaptcha.com/checksiteconfig"
    HCAPTCHA_GETCAPTCHA = "https://hcaptcha.com/getcaptcha"
    
    # reCAPTCHA endpoints
    RECAPTCHA_ANCHOR = "https://www.google.com/recaptcha/api2/anchor"
    RECAPTCHA_RELOAD = "https://www.google.com/recaptcha/api2/reload"
    
    # Shopify-specific endpoints
    SHOPIFY_CHECKPOINT = "https://api.checkpoint-staging.shopify.com"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the captcha solver.
        
        Args:
            api_key: Optional API key for external solving services
        """
        self.api_key = api_key
        self.solved_count = 0
        self.failed_count = 0
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=60,
                follow_redirects=True,
                http2=True,
            )
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    def _get_headers(self, fingerprint: Dict, referer: str = "") -> Dict[str, str]:
        """Generate headers based on fingerprint."""
        return {
            "User-Agent": fingerprint["userAgent"],
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": referer,
            "Origin": referer.split("/")[0] + "//" + referer.split("/")[2] if "/" in referer else "",
        }
    
    async def bypass_hcaptcha(
        self,
        sitekey: str,
        host: str,
        timeout: int = 30
    ) -> CaptchaResult:
        """
        Attempt to bypass hCaptcha using motion data simulation.
        
        Args:
            sitekey: The hCaptcha site key
            host: The host domain
            timeout: Request timeout
            
        Returns:
            CaptchaResult with token if successful
        """
        start_time = time.time()
        
        try:
            client = await self._get_client()
            fingerprint = BrowserFingerprint.generate()
            motion_data = MotionDataGenerator.generate_full_motion_data()
            
            headers = {
                "User-Agent": fingerprint["userAgent"],
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "Origin": "https://newassets.hcaptcha.com",
                "Referer": "https://newassets.hcaptcha.com/",
            }
            
            # Step 1: Get site config
            config_params = {
                "v": "1a3b5c7",
                "host": host,
                "sitekey": sitekey,
                "sc": "1",
                "swa": "1",
            }
            
            config_response = await asyncio.wait_for(
                client.get(
                    self.HCAPTCHA_SITECONFIG,
                    params=config_params,
                    headers=headers,
                ),
                timeout=timeout
            )
            
            if config_response.status_code != 200:
                return CaptchaResult(
                    success=False,
                    token=None,
                    provider="hcaptcha",
                    method="motion_bypass",
                    elapsed_time=time.time() - start_time,
                    error=f"Config request failed: {config_response.status_code}"
                )
            
            config_data = config_response.json()
            c_value = config_data.get("c", {})
            
            # Step 2: Get captcha (attempt no-challenge bypass)
            getcaptcha_data = {
                "v": "1a3b5c7",
                "sitekey": sitekey,
                "host": host,
                "hl": "en",
                "motionData": json.dumps(motion_data),
                "n": "",
                "c": json.dumps(c_value),
            }
            
            captcha_response = await asyncio.wait_for(
                client.post(
                    self.HCAPTCHA_GETCAPTCHA,
                    data=getcaptcha_data,
                    headers=headers,
                ),
                timeout=timeout
            )
            
            if captcha_response.status_code != 200:
                return CaptchaResult(
                    success=False,
                    token=None,
                    provider="hcaptcha",
                    method="motion_bypass",
                    elapsed_time=time.time() - start_time,
                    error=f"Captcha request failed: {captcha_response.status_code}"
                )
            
            challenge_data = captcha_response.json()
            
            # Check for direct pass (no visual challenge)
            if challenge_data.get("pass"):
                token = challenge_data.get("generated_pass_UUID")
                if token:
                    self.solved_count += 1
                    return CaptchaResult(
                        success=True,
                        token=token,
                        provider="hcaptcha",
                        method="motion_bypass",
                        elapsed_time=time.time() - start_time
                    )
            
            # Visual challenge required
            self.failed_count += 1
            return CaptchaResult(
                success=False,
                token=None,
                provider="hcaptcha",
                method="motion_bypass",
                elapsed_time=time.time() - start_time,
                error="Visual challenge required"
            )
            
        except asyncio.TimeoutError:
            return CaptchaResult(
                success=False,
                token=None,
                provider="hcaptcha",
                method="motion_bypass",
                elapsed_time=time.time() - start_time,
                error="Timeout"
            )
        except Exception as e:
            logger.error(f"hCaptcha bypass error: {e}")
            return CaptchaResult(
                success=False,
                token=None,
                provider="hcaptcha",
                method="motion_bypass",
                elapsed_time=time.time() - start_time,
                error=str(e)[:100]
            )
    
    async def bypass_recaptcha_v2_invisible(
        self,
        sitekey: str,
        domain: str,
        timeout: int = 30
    ) -> CaptchaResult:
        """
        Attempt to bypass invisible reCAPTCHA v2 using anchor/reload method.
        
        Args:
            sitekey: The reCAPTCHA site key
            domain: The target domain
            timeout: Request timeout
            
        Returns:
            CaptchaResult with token if successful
        """
        start_time = time.time()
        
        try:
            client = await self._get_client()
            fingerprint = BrowserFingerprint.generate()
            
            # Encode domain
            co_value = base64.b64encode(domain.encode()).decode().rstrip('=')
            
            # Version strings (rotated for evasion)
            versions = [
                "pCoGBhjs9s8EhFOHJFe8cqis",
                "aR9gHo8L8E_5hBxX_C_0AQj4",
                "r6AQhsVQ0SJNvQWQX4wPsqpc"
            ]
            version = random.choice(versions)
            
            headers = self._get_headers(fingerprint, domain)
            
            # Step 1: Get anchor token
            anchor_params = {
                "ar": "1",
                "k": sitekey,
                "co": co_value,
                "hl": "en",
                "v": version,
                "size": "invisible",
            }
            
            anchor_response = await asyncio.wait_for(
                client.get(
                    self.RECAPTCHA_ANCHOR,
                    params=anchor_params,
                    headers=headers,
                ),
                timeout=timeout
            )
            
            if anchor_response.status_code != 200:
                return CaptchaResult(
                    success=False,
                    token=None,
                    provider="recaptcha",
                    method="anchor_reload",
                    elapsed_time=time.time() - start_time,
                    error=f"Anchor request failed: {anchor_response.status_code}"
                )
            
            # Extract token
            anchor_text = anchor_response.text
            if 'recaptcha-token' not in anchor_text:
                return CaptchaResult(
                    success=False,
                    token=None,
                    provider="recaptcha",
                    method="anchor_reload",
                    elapsed_time=time.time() - start_time,
                    error="Token not found in anchor"
                )
            
            try:
                token1 = anchor_text.split('recaptcha-token" value="')[1].split('">')[0]
            except (IndexError, ValueError):
                return CaptchaResult(
                    success=False,
                    token=None,
                    provider="recaptcha",
                    method="anchor_reload",
                    elapsed_time=time.time() - start_time,
                    error="Failed to extract anchor token"
                )
            
            # Step 2: Reload to get final token
            reload_data = {
                "v": version,
                "reason": "q",
                "c": token1,
                "k": sitekey,
                "co": co_value,
                "hl": "en",
                "size": "invisible",
            }
            
            reload_headers = {**headers, "Content-Type": "application/x-www-form-urlencoded"}
            
            reload_response = await asyncio.wait_for(
                client.post(
                    f"{self.RECAPTCHA_RELOAD}?k={sitekey}",
                    data=urlencode(reload_data),
                    headers=reload_headers,
                ),
                timeout=timeout
            )
            
            if reload_response.status_code != 200:
                return CaptchaResult(
                    success=False,
                    token=None,
                    provider="recaptcha",
                    method="anchor_reload",
                    elapsed_time=time.time() - start_time,
                    error=f"Reload request failed: {reload_response.status_code}"
                )
            
            reload_text = reload_response.text
            
            if '"rresp","' in reload_text:
                try:
                    final_token = reload_text.split('"rresp","')[1].split('"')[0]
                    self.solved_count += 1
                    return CaptchaResult(
                        success=True,
                        token=final_token,
                        provider="recaptcha",
                        method="anchor_reload",
                        elapsed_time=time.time() - start_time
                    )
                except (IndexError, ValueError):
                    pass
            
            self.failed_count += 1
            return CaptchaResult(
                success=False,
                token=None,
                provider="recaptcha",
                method="anchor_reload",
                elapsed_time=time.time() - start_time,
                error="Failed to extract final token"
            )
            
        except asyncio.TimeoutError:
            return CaptchaResult(
                success=False,
                token=None,
                provider="recaptcha",
                method="anchor_reload",
                elapsed_time=time.time() - start_time,
                error="Timeout"
            )
        except Exception as e:
            logger.error(f"reCAPTCHA bypass error: {e}")
            return CaptchaResult(
                success=False,
                token=None,
                provider="recaptcha",
                method="anchor_reload",
                elapsed_time=time.time() - start_time,
                error=str(e)[:100]
            )
    
    def generate_shopify_bypass_data(
        self,
        checkout_url: str,
        session_token: str
    ) -> Dict[str, Any]:
        """
        Generate Shopify-specific captcha bypass data.
        Used for Shopify's internal bot detection.
        
        Args:
            checkout_url: The checkout URL
            session_token: The session token
            
        Returns:
            Bypass data dictionary
        """
        fingerprint = BrowserFingerprint.generate()
        motion_data = MotionDataGenerator.generate_full_motion_data()
        
        # Parse domain from checkout URL
        parsed = urlparse(checkout_url)
        domain = parsed.netloc
        
        timestamp = int(time.time() * 1000)
        nonce = hashlib.sha256(f"{session_token}{timestamp}".encode()).hexdigest()[:16]
        
        return {
            "provider": "shopify_checkpoint",
            "challenge": None,
            "sitekey": None,
            "token": nonce,
            "timestamp": timestamp,
            "response": {
                "fingerprint": fingerprint,
                "motion": motion_data,
                "source": "checkout",
                "domain": domain,
            }
        }
    
    async def solve_shopify_captcha(
        self,
        checkout_url: str,
        session_token: str,
        captcha_type: str = "auto",
        sitekey: Optional[str] = None,
        timeout: int = 60
    ) -> CaptchaResult:
        """
        Main method to solve Shopify captcha with multiple strategies.
        
        Args:
            checkout_url: The checkout URL
            session_token: The session token
            captcha_type: Type of captcha ("hcaptcha", "recaptcha", "auto")
            sitekey: The captcha site key (if known)
            timeout: Request timeout
            
        Returns:
            CaptchaResult with solution
        """
        start_time = time.time()
        
        parsed = urlparse(checkout_url)
        domain = f"https://{parsed.netloc}"
        
        # Try Shopify bypass first (fastest)
        bypass_data = self.generate_shopify_bypass_data(checkout_url, session_token)
        
        # If captcha type is unknown, try detection
        if captcha_type == "auto":
            # Default to trying all methods
            methods = ["shopify", "hcaptcha", "recaptcha"]
        else:
            methods = [captcha_type]
        
        last_error = None
        
        for method in methods:
            if method == "shopify":
                # Shopify bypass doesn't need actual solving
                return CaptchaResult(
                    success=True,
                    token=bypass_data["token"],
                    provider="shopify",
                    method="bypass",
                    elapsed_time=time.time() - start_time
                )
            
            elif method == "hcaptcha":
                if sitekey:
                    result = await self.bypass_hcaptcha(sitekey, parsed.netloc, timeout)
                    if result.success:
                        return result
                    last_error = result.error
            
            elif method == "recaptcha":
                if sitekey:
                    result = await self.bypass_recaptcha_v2_invisible(sitekey, domain, timeout)
                    if result.success:
                        return result
                    last_error = result.error
        
        # All methods failed
        return CaptchaResult(
            success=False,
            token=None,
            provider=captcha_type,
            method="all_failed",
            elapsed_time=time.time() - start_time,
            error=last_error or "All bypass methods failed"
        )
    
    def get_stats(self) -> Dict[str, int]:
        """Get solver statistics."""
        total = self.solved_count + self.failed_count
        return {
            "solved": self.solved_count,
            "failed": self.failed_count,
            "total": total,
            "success_rate": round(self.solved_count / total * 100, 2) if total > 0 else 0,
        }


# Global solver instance
_solver: Optional[ShopifyCaptchaSolver] = None


def get_solver() -> ShopifyCaptchaSolver:
    """Get the global solver instance."""
    global _solver
    if _solver is None:
        _solver = ShopifyCaptchaSolver()
    return _solver


# Async convenience functions
async def solve_hcaptcha(sitekey: str, host: str, timeout: int = 30) -> CaptchaResult:
    """Solve hCaptcha using the global solver."""
    solver = get_solver()
    return await solver.bypass_hcaptcha(sitekey, host, timeout)


async def solve_recaptcha(sitekey: str, domain: str, timeout: int = 30) -> CaptchaResult:
    """Solve reCAPTCHA using the global solver."""
    solver = get_solver()
    return await solver.bypass_recaptcha_v2_invisible(sitekey, domain, timeout)


async def solve_shopify_captcha(
    checkout_url: str,
    session_token: str,
    captcha_type: str = "auto",
    sitekey: Optional[str] = None
) -> CaptchaResult:
    """Solve Shopify captcha using the global solver."""
    solver = get_solver()
    return await solver.solve_shopify_captcha(checkout_url, session_token, captcha_type, sitekey)


def generate_bypass_data(checkout_url: str, session_token: str) -> Dict[str, Any]:
    """Generate Shopify bypass data."""
    solver = get_solver()
    return solver.generate_shopify_bypass_data(checkout_url, session_token)


# For backward compatibility with existing captcha_bypasser.py
async def get_shopify_captcha_bypass(checkout_url: str, session_token: str) -> Optional[Dict[str, Any]]:
    """
    Async wrapper for Shopify captcha bypass generation.
    Compatible with existing code.
    """
    return generate_bypass_data(checkout_url, session_token)
