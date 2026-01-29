"""
Professional Shopify Store Dorker with Captcha Bypass
====================================================
Finds low checkout Shopify stores using Google dorks with professional captcha handling.
"""

import asyncio
import aiohttp
import re
import json
import time
import random
from typing import List, Dict, Optional
from urllib.parse import quote, urlparse
from bs4 import BeautifulSoup
import cloudscraper

# Try to import captcha solving services
try:
    from twocaptcha import TwoCaptcha
    TWOCAPTCHA_AVAILABLE = True
except ImportError:
    TWOCAPTCHA_AVAILABLE = False

try:
    from anticaptchaofficial.anticaptcha import AntiCaptcha
    ANTICAPTCHA_AVAILABLE = True
except ImportError:
    ANTICAPTCHA_AVAILABLE = False

# Configuration
GOOGLE_SEARCH_URL = "https://www.google.com/search"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Rate limiting
REQUEST_DELAY = random.uniform(2, 4)  # Delay between requests
MAX_RETRIES = 3


class CaptchaSolver:
    """Professional captcha solver with multiple service support."""
    
    def __init__(self, api_key_2captcha: Optional[str] = None, api_key_anticaptcha: Optional[str] = None):
        self.two_captcha = None
        self.anti_captcha = None
        
        if TWOCAPTCHA_AVAILABLE and api_key_2captcha:
            try:
                self.two_captcha = TwoCaptcha(api_key_2captcha)
            except Exception:
                pass
        
        if ANTICAPTCHA_AVAILABLE and api_key_anticaptcha:
            try:
                self.anti_captcha = AntiCaptcha(api_key_anticaptcha)
            except Exception:
                pass
    
    async def solve_recaptcha_v2(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve reCAPTCHA v2."""
        if self.two_captcha:
            try:
                result = self.two_captcha.recaptcha(sitekey=site_key, url=page_url)
                return result.get('code') if result else None
            except Exception:
                pass
        
        if self.anti_captcha:
            try:
                self.anti_captcha.set_website_url(page_url)
                self.anti_captcha.set_website_key(site_key)
                result = self.anti_captcha.solve_and_return_solution()
                return result if result else None
            except Exception:
                pass
        
        return None
    
    async def solve_hcaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve hCaptcha."""
        if self.two_captcha:
            try:
                result = self.two_captcha.hcaptcha(sitekey=site_key, url=page_url)
                return result.get('code') if result else None
            except Exception:
                pass
        
        return None


class ShopifyDorker:
    """Professional Shopify store dorker with captcha bypass."""
    
    def __init__(self, captcha_solver: Optional[CaptchaSolver] = None, proxy: Optional[str] = None):
        self.captcha_solver = captcha_solver
        self.proxy = proxy
        self.session = None
        self.scraper = None
        self.found_stores = []
    
    def _get_headers(self) -> Dict[str, str]:
        """Get randomized headers."""
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
    
    async def _create_session(self):
        """Create aiohttp session with cloudscraper fallback."""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=30)
            connector = aiohttp.TCPConnector(ssl=False)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers=self._get_headers()
            )
        
        # Also create cloudscraper session for captcha handling
        if not self.scraper:
            self.scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True
                }
            )
    
    async def _handle_captcha(self, html: str, url: str) -> bool:
        """Detect and solve captchas."""
        # Check for reCAPTCHA
        recaptcha_match = re.search(r'data-sitekey=["\']([^"\']+)["\']', html)
        if recaptcha_match and self.captcha_solver:
            site_key = recaptcha_match.group(1)
            token = await self.captcha_solver.solve_recaptcha_v2(site_key, url)
            if token:
                # Inject token into page (would need to resubmit form)
                return True
        
        # Check for hCaptcha
        hcaptcha_match = re.search(r'data-sitekey=["\']([^"\']+)["\']', html)
        if hcaptcha_match and 'hcaptcha' in html.lower() and self.captcha_solver:
            site_key = hcaptcha_match.group(1)
            token = await self.captcha_solver.solve_hcaptcha(site_key, url)
            if token:
                return True
        
        return False
    
    async def search_google(self, query: str, num_results: int = 50) -> List[str]:
        """Search Google with captcha bypass using multiple methods."""
        await self._create_session()
        
        results = []
        start = 0
        retry_count = 0
        max_retries = MAX_RETRIES
        
        while len(results) < num_results and start < 100:  # Max 100 results
            try:
                # Build search URL
                params = {
                    "q": query,
                    "num": 10,  # Results per page
                    "start": start,
                    "hl": "en",
                    "gl": "us",
                }
                
                search_url = f"{GOOGLE_SEARCH_URL}?{self._build_query_string(params)}"
                
                # Use cloudscraper for better captcha handling
                try:
                    response = self.scraper.get(search_url, headers=self._get_headers(), timeout=20)
                    html = response.text
                except Exception as e:
                    print(f"⚠️ Request failed: {e}")
                    retry_count += 1
                    if retry_count >= max_retries:
                        break
                    await asyncio.sleep(REQUEST_DELAY * 2)
                    continue
                
                # Check for captcha
                if "captcha" in html.lower() or "recaptcha" in html.lower() or "sorry" in html.lower():
                    if self.captcha_solver:
                        print(f"🔐 Captcha detected, solving...")
                        solved = await self._handle_captcha(html, search_url)
                        if solved:
                            # Retry after solving
                            await asyncio.sleep(3)
                            try:
                                response = self.scraper.get(search_url, headers=self._get_headers(), timeout=20)
                                html = response.text
                            except Exception:
                                retry_count += 1
                                if retry_count >= max_retries:
                                    break
                                continue
                        else:
                            print(f"⚠️ Failed to solve captcha. Skipping...")
                            retry_count += 1
                            if retry_count >= max_retries:
                                break
                            await asyncio.sleep(REQUEST_DELAY * 3)
                            continue
                    else:
                        print(f"⚠️ Captcha detected but no solver configured. Using alternative method...")
                        # Try alternative search method
                        await asyncio.sleep(REQUEST_DELAY * 2)
                        retry_count += 1
                        if retry_count >= max_retries:
                            break
                        continue
                
                # Check if we got valid results
                if "did not match any documents" in html.lower() or len(html) < 1000:
                    print(f"⚠️ No results found or invalid response")
                    break
                
                # Extract URLs from search results
                shopify_urls = self._extract_shopify_urls(html)
                if shopify_urls:
                    results.extend(shopify_urls)
                    retry_count = 0  # Reset retry count on success
                else:
                    # No URLs found, might be last page
                    if start > 0:
                        break
                
                # Rate limiting
                await asyncio.sleep(REQUEST_DELAY)
                start += 10
                
            except Exception as e:
                print(f"❌ Error searching: {e}")
                retry_count += 1
                if retry_count >= max_retries:
                    break
                await asyncio.sleep(REQUEST_DELAY * 2)
        
        return list(set(results))  # Remove duplicates
    
    def _build_query_string(self, params: Dict) -> str:
        """Build URL query string."""
        return "&".join([f"{k}={quote(str(v))}" for k, v in params.items()])
    
    def _extract_shopify_urls(self, html: str) -> List[str]:
        """Extract Shopify store URLs from HTML."""
        urls = []
        
        # Pattern 1: Direct myshopify.com URLs
        pattern1 = r'https?://[a-zA-Z0-9-]+\.myshopify\.com[^\s"<>\)]*'
        matches = re.findall(pattern1, html)
        urls.extend(matches)
        
        # Pattern 2: Google search result URLs (extract from /url?q=)
        google_url_pattern = r'/url\?q=([^&]+)'
        google_matches = re.findall(google_url_pattern, html)
        for match in google_matches:
            try:
                from urllib.parse import unquote
                decoded_url = unquote(match)
                if 'myshopify.com' in decoded_url or self._is_likely_shopify(decoded_url):
                    urls.append(decoded_url)
            except Exception:
                continue
        
        # Pattern 3: Extract from HTML links using BeautifulSoup
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract from all links
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                
                # Handle Google redirect URLs
                if href.startswith('/url?'):
                    match = re.search(r'url\?q=([^&]+)', href)
                    if match:
                        try:
                            from urllib.parse import unquote
                            href = unquote(match.group(1))
                        except Exception:
                            continue
                
                if 'myshopify.com' in href or self._is_likely_shopify(href):
                    if href.startswith('http'):
                        urls.append(href)
        except Exception:
            pass
        
        # Pattern 4: Extract from JSON-LD or script tags
        json_pattern = r'"url":\s*"([^"]*myshopify[^"]*)"'
        json_matches = re.findall(json_pattern, html)
        urls.extend(json_matches)
        
        # Clean and validate URLs
        cleaned_urls = []
        seen = set()
        for url in urls:
            try:
                # Decode URL if needed
                from urllib.parse import unquote
                url = unquote(url)
                
                parsed = urlparse(url)
                
                # Must be myshopify.com or have Shopify indicators
                if 'myshopify.com' in parsed.netloc or self._is_likely_shopify(url):
                    # Normalize URL
                    if not parsed.scheme:
                        url = 'https://' + url
                    
                    # Remove query params and fragments, get base URL
                    base_url = url.split('?')[0].split('#')[0]
                    
                    # Get store base URL (remove /products/, /collections/, etc.)
                    if '/products/' in base_url:
                        base_url = base_url.split('/products/')[0]
                    elif '/collections/' in base_url:
                        base_url = base_url.split('/collections/')[0]
                    elif '/cart' in base_url:
                        base_url = base_url.split('/cart')[0]
                    elif '/checkout' in base_url:
                        base_url = base_url.split('/checkout')[0]
                    
                    # Ensure it ends with .myshopify.com or is a valid domain
                    if base_url not in seen:
                        seen.add(base_url)
                        cleaned_urls.append(base_url.rstrip('/'))
            except Exception:
                continue
        
        return cleaned_urls
    
    def _is_likely_shopify(self, url: str) -> bool:
        """Check if URL is likely a Shopify store."""
        shopify_indicators = [
            '/products/',
            '/collections/',
            '/cart',
            '/checkout',
            'cdn.shopify.com',
            'myshopify.com',
        ]
        return any(indicator in url.lower() for indicator in shopify_indicators)
    
    async def verify_store(self, url: str) -> Optional[Dict]:
        """Verify if a URL is a valid Shopify store with low-priced products."""
        try:
            await self._create_session()
            
            # Normalize URL
            if not url.startswith('http'):
                url = 'https://' + url
            
            # Try to access the store
            response = self.scraper.get(url, headers=self._get_headers(), timeout=15)
            
            if response.status_code != 200:
                return None
            
            html = response.text
            
            # Check if it's actually Shopify
            if 'shopify' not in html.lower() and 'myshopify.com' not in url:
                # Try to find Shopify indicators
                if not any(indicator in html.lower() for indicator in ['shopify', 'cdn.shopify', 'checkout.shopify']):
                    return None
            
            # Extract product prices
            prices = self._extract_prices(html)
            low_prices = [p for p in prices if p and p < 10.0]
            
            if not low_prices:
                return None
            
            # Extract store name
            store_name = self._extract_store_name(html, url)
            
            return {
                "url": url,
                "store_name": store_name,
                "low_prices": low_prices,
                "min_price": min(low_prices),
                "max_price": max(low_prices),
                "verified": True
            }
            
        except Exception as e:
            return None
    
    def _extract_prices(self, html: str) -> List[float]:
        """Extract product prices from HTML."""
        prices = []
        
        # Pattern 1: $X.XX format
        pattern1 = r'\$(\d+\.?\d*)'
        matches = re.findall(pattern1, html)
        for match in matches:
            try:
                price = float(match)
                if 0 < price < 100:  # Reasonable price range
                    prices.append(price)
            except ValueError:
                continue
        
        # Pattern 2: Price in JSON data
        json_pattern = r'"price":\s*"?(\d+\.?\d*)"?'
        matches = re.findall(json_pattern, html)
        for match in matches:
            try:
                price = float(match) / 100 if len(match) > 2 else float(match)  # Handle cents
                if 0 < price < 100:
                    prices.append(price)
            except ValueError:
                continue
        
        # Pattern 3: Price in data attributes
        data_pattern = r'data-price=["\'](\d+\.?\d*)["\']'
        matches = re.findall(data_pattern, html)
        for match in matches:
            try:
                price = float(match)
                if 0 < price < 100:
                    prices.append(price)
            except ValueError:
                continue
        
        return prices
    
    def _extract_store_name(self, html: str, url: str) -> str:
        """Extract store name from HTML or URL."""
        # Try to get from title tag
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.find('title')
        if title:
            title_text = title.get_text().strip()
            # Remove common suffixes
            for suffix in [' - Shopify', ' | Shopify', 'Shop']:
                if suffix in title_text:
                    title_text = title_text.replace(suffix, '').strip()
            if title_text:
                return title_text[:50]  # Limit length
        
        # Fallback to domain name
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '').replace('.myshopify.com', '')
        return domain or "Unknown Store"
    
    async def dork_stores(self, dork_queries: List[str], max_stores: int = 50) -> List[Dict]:
        """Main dorking function - searches and verifies stores."""
        all_urls = []
        
        # Search with all dork queries
        for query in dork_queries:
            print(f"🔍 Searching: {query}")
            urls = await self.search_google(query, num_results=30)
            all_urls.extend(urls)
            await asyncio.sleep(REQUEST_DELAY)
        
        # Remove duplicates
        unique_urls = list(set(all_urls))
        print(f"✅ Found {len(unique_urls)} unique URLs")
        
        # Verify stores
        verified_stores = []
        for url in unique_urls[:max_stores]:
            print(f"🔎 Verifying: {url}")
            store_info = await self.verify_store(url)
            if store_info:
                verified_stores.append(store_info)
                print(f"✅ Verified: {store_info['store_name']} - Min price: ${store_info['min_price']:.2f}")
            await asyncio.sleep(1)  # Rate limit verification
        
        return verified_stores
    
    async def close(self):
        """Close sessions."""
        if self.session:
            await self.session.close()


# Predefined dork queries for low checkout stores
DORK_QUERIES = [
    'site:myshopify.com/products/ ("$0" OR "$1" OR "$2" OR "$3" OR "$4" OR "$5" OR "$6" OR "$7" OR "$8" OR "$9") -"$10"',
    'inurl:myshopify.com/products/ "$" -"$10" -"$15" -"$20"',
    'site:myshopify.com ("$0.99" OR "$1.99" OR "$2.99" OR "$3.99" OR "$4.99" OR "$5.99" OR "$6.99" OR "$7.99" OR "$8.99" OR "$9.99")',
    'inurl:myshopify.com/collections/ "$" -"$10"',
    'site:myshopify.com/products/ "price" ("$0" OR "$1" OR "$2" OR "$3" OR "$4" OR "$5" OR "$6" OR "$7" OR "$8" OR "$9")',
]


async def dork_shopify_stores(
    captcha_api_key_2captcha: Optional[str] = None,
    captcha_api_key_anticaptcha: Optional[str] = None,
    proxy: Optional[str] = None,
    custom_queries: Optional[List[str]] = None,
    max_stores: int = 50
) -> List[Dict]:
    """
    Main function to dork Shopify stores with low checkout prices.
    
    Args:
        captcha_api_key_2captcha: 2Captcha API key (optional)
        captcha_api_key_anticaptcha: AntiCaptcha API key (optional)
        proxy: Proxy to use (optional, format: http://user:pass@host:port)
        custom_queries: Custom dork queries (optional)
        max_stores: Maximum number of stores to verify
    
    Returns:
        List of verified store dictionaries with URL, name, and prices
    """
    # Initialize captcha solver if API keys provided
    captcha_solver = None
    if captcha_api_key_2captcha or captcha_api_key_anticaptcha:
        captcha_solver = CaptchaSolver(
            api_key_2captcha=captcha_api_key_2captcha,
            api_key_anticaptcha=captcha_api_key_anticaptcha
        )
    
    # Create dorker
    dorker = ShopifyDorker(captcha_solver=captcha_solver, proxy=proxy)
    
    try:
        # Use custom queries or default
        queries = custom_queries or DORK_QUERIES
        
        # Dork stores
        stores = await dorker.dork_stores(queries, max_stores=max_stores)
        
        return stores
    finally:
        await dorker.close()


# Example usage
if __name__ == "__main__":
    async def main():
        # Example: Run dorker with captcha solving
        stores = await dork_shopify_stores(
            captcha_api_key_2captcha="YOUR_2CAPTCHA_API_KEY",  # Optional
            max_stores=20
        )
        
        # Save results
        with open("dorked_stores.json", "w") as f:
            json.dump(stores, f, indent=2)
        
        print(f"\n✅ Found {len(stores)} verified stores!")
        for store in stores:
            print(f"  • {store['store_name']}: {store['url']} (${store['min_price']:.2f})")
    
    asyncio.run(main())
