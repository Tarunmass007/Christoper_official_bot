"""
API Endpoint Verification Script
Tests all bot command API endpoints for reachability and basic functionality
"""

import asyncio
import httpx
import json
from datetime import datetime
import sys

# Color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text.center(70)}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*70}{Colors.RESET}\n")

def print_success(text):
    print(f"{Colors.GREEN}✓ {text}{Colors.RESET}")

def print_error(text):
    print(f"{Colors.RED}✗ {text}{Colors.RESET}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠ {text}{Colors.RESET}")

def print_info(text):
    print(f"{Colors.BLUE}ℹ {text}{Colors.RESET}")

class APITester:
    def __init__(self):
        self.results = {
            'total_tests': 0,
            'passed': 0,
            'failed': 0,
            'warnings': 0,
            'endpoints': []
        }
        self.timeout = 10.0  # seconds

    async def test_endpoint(self, name, url, method='GET', data=None, headers=None, expected_status=None, test_type='reachability'):
        """Test a single API endpoint"""
        self.results['total_tests'] += 1

        print(f"\n{Colors.BOLD}Testing: {name}{Colors.RESET}")
        print(f"URL: {url}")
        print(f"Method: {method}")

        result = {
            'name': name,
            'url': url,
            'method': method,
            'status': 'unknown',
            'response_time': None,
            'error': None,
            'timestamp': datetime.now().isoformat()
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
                start_time = asyncio.get_event_loop().time()

                if method == 'GET':
                    response = await client.get(url, headers=headers)
                elif method == 'POST':
                    response = await client.post(url, data=data, headers=headers)
                else:
                    response = await client.request(method, url, data=data, headers=headers)

                end_time = asyncio.get_event_loop().time()
                response_time = round((end_time - start_time) * 1000, 2)  # ms

                result['response_time'] = response_time
                result['status_code'] = response.status_code

                # Check status
                if expected_status:
                    if response.status_code == expected_status:
                        result['status'] = 'passed'
                        self.results['passed'] += 1
                        print_success(f"Status: {response.status_code} (Expected) - Response time: {response_time}ms")
                    else:
                        result['status'] = 'warning'
                        self.results['warnings'] += 1
                        print_warning(f"Status: {response.status_code} (Expected: {expected_status}) - Response time: {response_time}ms")
                else:
                    # Just check if reachable (status < 500)
                    if response.status_code < 500:
                        result['status'] = 'passed'
                        self.results['passed'] += 1
                        print_success(f"Reachable - Status: {response.status_code} - Response time: {response_time}ms")
                    else:
                        result['status'] = 'failed'
                        self.results['failed'] += 1
                        print_error(f"Server Error - Status: {response.status_code} - Response time: {response_time}ms")

                # Try to show response preview
                try:
                    if response.headers.get('content-type', '').startswith('application/json'):
                        preview = json.dumps(response.json(), indent=2)[:200]
                        print_info(f"Response preview: {preview}...")
                    else:
                        preview = response.text[:200]
                        print_info(f"Response preview: {preview}...")
                except:
                    pass

        except httpx.TimeoutException:
            result['status'] = 'failed'
            result['error'] = 'Timeout'
            self.results['failed'] += 1
            print_error(f"Timeout after {self.timeout}s")

        except httpx.ConnectError as e:
            result['status'] = 'failed'
            result['error'] = f'Connection Error: {str(e)}'
            self.results['failed'] += 1
            print_error(f"Connection Error: {str(e)}")

        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
            self.results['failed'] += 1
            print_error(f"Error: {str(e)}")

        self.results['endpoints'].append(result)
        return result

    async def run_all_tests(self):
        """Run all API endpoint tests"""

        print_header("BOT API ENDPOINT VERIFICATION")
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # ========== SHOPIFY ENDPOINTS ==========
        print_header("SHOPIFY ENDPOINTS")

        # SLF Shopify API (for /sh, /tsh, /msh commands)
        await self.test_endpoint(
            name="SLF Shopify Gateway (/sh, /tsh, /msh)",
            url="http://69.62.117.8:8000/check",
            method="GET"
        )

        # AutoShopify API (for /autosh, /ash commands)
        await self.test_endpoint(
            name="AutoShopify Gateway (/autosh, /ash)",
            url="http://136.175.187.188:8079/shc.php",
            method="GET"
        )

        # Shopify Checkout Target (for /sho command)
        await self.test_endpoint(
            name="Shopify Checkout Target (/sho)",
            url="https://coatesforkids.org/products/donation",
            method="GET",
            expected_status=200
        )

        # ========== STRIPE ENDPOINTS ==========
        print_header("STRIPE ENDPOINTS")

        # Note: Stripe API requires authentication, so we just test basic connectivity
        await self.test_endpoint(
            name="Stripe API Base (for /st, /au commands)",
            url="https://api.stripe.com/v1/tokens",
            method="GET",
            expected_status=401  # Unauthorized is expected without API key
        )

        # ========== BRAINTREE/PIXORIZE ENDPOINTS ==========
        print_header("BRAINTREE ENDPOINTS")

        # Pixorize API (for /br command)
        await self.test_endpoint(
            name="Pixorize Braintree API (/br)",
            url="https://apitwo.pixorize.com/users/register-simple",
            method="GET"
        )

        # reCAPTCHA endpoint (used by Braintree)
        await self.test_endpoint(
            name="reCAPTCHA Enterprise API (Braintree dependency)",
            url="https://www.google.com/recaptcha/enterprise.js",
            method="GET",
            expected_status=200
        )

        # ========== UTILITY ENDPOINTS ==========
        print_header("UTILITY ENDPOINTS")

        # Random User API (for /fake command)
        await self.test_endpoint(
            name="Random User Generator (/fake)",
            url="https://randomuser.me/api/?nat=us",
            method="GET",
            expected_status=200
        )

        # IP Check API (for proxy validation)
        await self.test_endpoint(
            name="IP Check API (proxy validation)",
            url="https://api.ipify.org?format=json",
            method="GET",
            expected_status=200
        )

        # ========== TEST WITH SAMPLE DATA ==========
        print_header("FUNCTIONAL TESTS WITH SAMPLE DATA")

        # Test SLF with sample card (will fail validation but tests API)
        await self.test_endpoint(
            name="SLF Gateway with Test Card",
            url="http://69.62.117.8:8000/check?card=4532111111111111|12|2027|123&site=test",
            method="GET"
        )

        # Test AutoShopify with sample data
        await self.test_endpoint(
            name="AutoShopify with Test Card",
            url="http://136.175.187.188:8079/shc.php?cc=4532111111111111|12|2027|123",
            method="GET"
        )

        # Test Random User API
        await self.test_endpoint(
            name="Random User with US nationality",
            url="https://randomuser.me/api/?nat=us",
            method="GET",
            expected_status=200
        )

        # ========== PRINT SUMMARY ==========
        self.print_summary()

    def print_summary(self):
        """Print test results summary"""
        print_header("TEST SUMMARY")

        print(f"Total Tests: {Colors.BOLD}{self.results['total_tests']}{Colors.RESET}")
        print_success(f"Passed: {self.results['passed']}")
        print_error(f"Failed: {self.results['failed']}")
        print_warning(f"Warnings: {self.results['warnings']}")

        success_rate = (self.results['passed'] / self.results['total_tests'] * 100) if self.results['total_tests'] > 0 else 0

        print(f"\n{Colors.BOLD}Success Rate: {success_rate:.1f}%{Colors.RESET}")

        if self.results['failed'] > 0:
            print_header("FAILED ENDPOINTS")
            for endpoint in self.results['endpoints']:
                if endpoint['status'] == 'failed':
                    print_error(f"{endpoint['name']}")
                    print(f"  URL: {endpoint['url']}")
                    print(f"  Error: {endpoint['error']}\n")

        # Save results to JSON
        try:
            with open('api_test_results.json', 'w') as f:
                json.dump(self.results, f, indent=2)
            print_success("Results saved to api_test_results.json")
        except Exception as e:
            print_warning(f"Could not save results: {e}")

        # Command availability summary
        print_header("COMMAND AVAILABILITY SUMMARY")

        command_status = {
            '/sh, /tsh, /msh': 'SLF Shopify Gateway',
            '/autosh, /ash': 'AutoShopify Gateway',
            '/sho': 'Shopify Checkout Target',
            '/st, /au': 'Stripe API Base',
            '/br': 'Pixorize Braintree API',
            '/fake': 'Random User Generator',
            '/bin': 'Local BIN Database (not tested - local)',
            '/gen': 'Local Generator (not tested - local)'
        }

        print("\nChecking command availability based on API tests:\n")

        endpoint_map = {
            'SLF Shopify Gateway (/sh, /tsh, /msh)': ['/sh', '/tsh', '/msh'],
            'AutoShopify Gateway (/autosh, /ash)': ['/autosh', '/ash'],
            'Shopify Checkout Target (/sho)': ['/sho'],
            'Stripe API Base (for /st, /au commands)': ['/st', '/au'],
            'Pixorize Braintree API (/br)': ['/br'],
            'Random User Generator (/fake)': ['/fake']
        }

        for endpoint in self.results['endpoints']:
            if endpoint['name'] in endpoint_map:
                commands = endpoint_map[endpoint['name']]
                status_icon = '✓' if endpoint['status'] == 'passed' else '✗'
                status_color = Colors.GREEN if endpoint['status'] == 'passed' else Colors.RED

                for cmd in commands:
                    print(f"{status_color}{status_icon}{Colors.RESET} {cmd.ljust(15)} - {endpoint['name']}")

        print(f"\n{Colors.CYAN}Note: Local commands (/bin, /gen, /info, etc.) don't require external APIs{Colors.RESET}")

async def main():
    """Main entry point"""
    tester = APITester()
    await tester.run_all_tests()

    # Return exit code based on results
    if tester.results['failed'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}Test interrupted by user{Colors.RESET}")
        sys.exit(130)
