"""
Direct Code Verification: Trace command handlers to API calls
Reads Python files directly to verify API call chains
"""

import os
import re
from pathlib import Path

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text.center(80)}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.RESET}\n")

def print_success(text):
    print(f"{Colors.GREEN}✓ {text}{Colors.RESET}")

def print_error(text):
    print(f"{Colors.RED}✗ {text}{Colors.RESET}")

def print_info(text):
    print(f"{Colors.BLUE}  {text}{Colors.RESET}")

def read_file_safe(file_path):
    """Safely read a file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except:
        return None

def find_api_calls(content, api_function_name):
    """Find API function calls in content"""
    patterns = [
        rf'{api_function_name}\s*\(',  # Direct call
        rf'await\s+{api_function_name}\s*\(',  # Async await
        rf'asyncio\.\w+\({api_function_name}',  # Asyncio wrapper
    ]

    for pattern in patterns:
        if re.search(pattern, content):
            return True
    return False

def find_http_requests(content):
    """Find HTTP request calls"""
    patterns = [
        r'httpx\.AsyncClient',
        r'client\.(get|post|put|delete|request)\s*\(',
        r'aiohttp\.ClientSession',
        r'session\.(get|post|put|delete|request)\s*\(',
        r'requests\.(get|post|put|delete|request)\s*\(',
    ]

    found_requests = []
    for pattern in patterns:
        matches = re.finditer(pattern, content, re.IGNORECASE)
        for match in matches:
            # Try to find the URL near the match
            start = max(0, match.start() - 200)
            end = min(len(content), match.end() + 200)
            context = content[start:end]

            # Look for URLs
            url_match = re.search(r'https?://[^\s\'")\]]+', context)
            if url_match:
                found_requests.append(url_match.group(0))

    return found_requests

def verify_command(command_name, handler_file, api_file, api_function):
    """Verify a command's API call chain"""

    print(f"\n{Colors.BOLD}{command_name}{Colors.RESET}")

    result = {
        'command': command_name,
        'handler_exists': False,
        'api_file_exists': False,
        'api_calls_found': False,
        'http_requests': [],
        'status': 'FAILED'
    }

    # Check handler file
    if os.path.exists(handler_file):
        result['handler_exists'] = True
        print_success(f"Handler file exists: {handler_file}")

        handler_content = read_file_safe(handler_file)
        if handler_content:
            # Check if handler calls the API function
            if api_function and find_api_calls(handler_content, api_function):
                result['api_calls_found'] = True
                print_success(f"Handler calls API function: {api_function}()")
            elif api_function:
                print_error(f"Handler does NOT call: {api_function}()")

            # Check for direct HTTP requests in handler
            http_reqs = find_http_requests(handler_content)
            if http_reqs:
                print_info(f"Direct HTTP requests in handler:")
                for req in set(http_reqs):
                    print_info(f"  → {req}")
    else:
        print_error(f"Handler file NOT found: {handler_file}")

    # Check API file
    if api_file:
        if os.path.exists(api_file):
            result['api_file_exists'] = True
            print_success(f"API file exists: {api_file}")

            api_content = read_file_safe(api_file)
            if api_content:
                # Check if API function exists
                if api_function:
                    pattern = rf'(async\s+)?def\s+{api_function}\s*\('
                    if re.search(pattern, api_content):
                        print_success(f"API function defined: {api_function}()")
                    else:
                        print_error(f"API function NOT found: {api_function}()")

                # Find HTTP requests in API
                http_reqs = find_http_requests(api_content)
                if http_reqs:
                    result['http_requests'] = http_reqs
                    print_success(f"API makes HTTP requests to:")
                    for req in set(http_reqs):
                        print_info(f"  → {req}")
                else:
                    print_error("No HTTP requests found in API file")
        else:
            print_error(f"API file NOT found: {api_file}")
    else:
        print_info("No separate API file (uses external API or local)")

    # Determine overall status
    if result['handler_exists']:
        if api_file:
            if result['api_file_exists'] and (result['api_calls_found'] or result['http_requests']):
                result['status'] = 'PASS'
        else:
            # No API file means local only or direct external call
            result['status'] = 'PASS'

    status_color = Colors.GREEN if result['status'] == 'PASS' else Colors.RED
    print(f"{status_color}Status: {result['status']}{Colors.RESET}")

    return result

def main():
    print_header("COMMAND -> API CALL VERIFICATION")
    print("Directly analyzing code files to verify API call chains\n")

    base_dir = Path(__file__).parent

    # Define all commands to verify
    commands = [
        # Shopify SLF Commands
        {
            'name': '/sh (Shopify SLF Single)',
            'handler': 'BOT/Charge/Shopify/slf/single.py',
            'api': 'BOT/Charge/Shopify/slf/slf.py',
            'function': 'check_card'
        },
        {
            'name': '/tsh (Shopify SLF Test)',
            'handler': 'BOT/Charge/Shopify/slf/tsh.py',
            'api': 'BOT/Charge/Shopify/slf/slf.py',
            'function': 'check_card'
        },
        {
            'name': '/msh (Shopify SLF Mass)',
            'handler': 'BOT/Charge/Shopify/slf/mass.py',
            'api': 'BOT/Charge/Shopify/slf/slf.py',
            'function': 'check_card'
        },
        # AutoShopify Commands
        {
            'name': '/autosh or /ash (AutoShopify)',
            'handler': 'BOT/Charge/Shopify/ash/single.py',
            'api': 'BOT/Charge/Shopify/ash/api.py',
            'function': 'check_autoshopify'
        },
        {
            'name': '/mautosh or /mash (AutoShopify Mass)',
            'handler': 'BOT/Charge/Shopify/ash/mass.py',
            'api': 'BOT/Charge/Shopify/ash/api.py',
            'function': 'check_autoshopify'
        },
        # Shopify Checkout
        {
            'name': '/sho (Shopify Checkout)',
            'handler': 'BOT/Charge/Shopify/sho/single.py',
            'api': 'BOT/Charge/Shopify/sho/sho.py',
            'function': 'create_shopify_charge'
        },
        {
            'name': '/msho (Shopify Checkout Mass)',
            'handler': 'BOT/Charge/Shopify/sho/mass.py',
            'api': 'BOT/Charge/Shopify/sho/sho.py',
            'function': 'create_shopify_charge'
        },
        # Shopify Gateway
        {
            'name': '/sg (Shopify Gateway)',
            'handler': 'BOT/Charge/Shopify/sg/single.py',
            'api': 'BOT/Charge/Shopify/sg/sg.py',
            'function': 'create_shopify_charge'
        },
        {
            'name': '/msg (Shopify Gateway Mass)',
            'handler': 'BOT/Charge/Shopify/sg/mass.py',
            'api': 'BOT/Charge/Shopify/sg/sg.py',
            'function': 'create_shopify_charge'
        },
        # Stripe Commands
        {
            'name': '/st (Stripe $20 Charge)',
            'handler': 'BOT/Charge/Stripe/single.py',
            'api': 'BOT/Charge/Stripe/api.py',
            'function': 'async_stripe_charge'
        },
        {
            'name': '/au (Stripe Auth $0)',
            'handler': 'BOT/Auth/Stripe/single.py',
            'api': 'BOT/Auth/Stripe/fixme.py',
            'function': 'async_stripe_auth_fixme'
        },
        {
            'name': '/mau (Stripe Auth Mass)',
            'handler': 'BOT/Auth/Stripe/mass.py',
            'api': 'BOT/Auth/Stripe/fixme.py',
            'function': 'async_stripe_auth_fixme'
        },
        # Braintree
        {
            'name': '/br (Braintree)',
            'handler': 'BOT/Charge/Braintree/single.py',
            'api': 'BOT/Charge/Braintree/api.py',
            'function': 'check_braintree'
        },
        # Tool Commands
        {
            'name': '/bin (BIN Lookup)',
            'handler': 'BOT/tools/bin.py',
            'api': 'TOOLS/getbin.py',
            'function': 'get_bin_details'
        },
        {
            'name': '/fake (Fake User)',
            'handler': 'BOT/tools/fake.py',
            'api': None,
            'function': None
        },
        {
            'name': '/gen (Card Generator)',
            'handler': 'BOT/tools/gen.py',
            'api': None,
            'function': None
        },
    ]

    results = []

    for cmd in commands:
        handler_path = base_dir / cmd['handler']
        api_path = base_dir / cmd['api'] if cmd['api'] else None

        result = verify_command(
            cmd['name'],
            str(handler_path),
            str(api_path) if api_path else None,
            cmd['function']
        )
        results.append(result)

    # Print summary
    print_header("VERIFICATION SUMMARY")

    passed = sum(1 for r in results if r['status'] == 'PASS')
    failed = sum(1 for r in results if r['status'] == 'FAILED')

    print(f"Total Commands Verified: {Colors.BOLD}{len(results)}{Colors.RESET}")
    print_success(f"Passed: {passed}")
    print_error(f"Failed: {failed}")

    success_rate = (passed / len(results) * 100) if results else 0
    print(f"\n{Colors.BOLD}Success Rate: {success_rate:.1f}%{Colors.RESET}\n")

    # Show all API endpoints found
    print_header("API ENDPOINTS DETECTED")

    all_endpoints = set()
    for r in results:
        all_endpoints.update(r['http_requests'])

    if all_endpoints:
        print("\nThe bot makes HTTP requests to these endpoints:\n")
        for endpoint in sorted(all_endpoints):
            # Clean up the URL
            endpoint = endpoint.split('?')[0].strip('"\'')
            print_info(f"• {endpoint}")
    else:
        print_error("No HTTP endpoints detected")

    # Final verdict
    print_header("FINAL VERDICT")

    if failed == 0:
        print_success("✓ ALL COMMANDS HAVE PROPER API CALL CHAINS")
        print(f"{Colors.GREEN}Every command that requires an API call has the proper routing in place.{Colors.RESET}\n")
    else:
        print_error(f"✗ {failed} COMMAND(S) HAVE ISSUES")
        print(f"{Colors.RED}Some commands may not properly call their APIs.{Colors.RESET}\n")

        print("Failed commands:")
        for r in results:
            if r['status'] == 'FAILED':
                print_error(f"  • {r['command']}")

    return 0 if failed == 0 else 1

if __name__ == '__main__':
    exit(main())
