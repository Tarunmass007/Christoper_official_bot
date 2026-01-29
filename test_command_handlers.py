"""
Command Handler Verification Script
Tests if each bot command can properly route to its API function
"""

import asyncio
import sys
import os
from pathlib import Path

# Add BOT directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Color codes
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
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

def print_info(text):
    print(f"{Colors.BLUE}ℹ {text}{Colors.RESET}")

async def verify_command_imports():
    """Verify all command handlers and API functions can be imported"""

    print_header("COMMAND HANDLER IMPORT VERIFICATION")

    results = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'details': []
    }

    # List of all command modules and their API functions
    commands_to_test = [
        # Shopify Commands
        {
            'name': '/sh (SLF Single)',
            'handler_path': 'BOT.Charge.Shopify.slf.single',
            'api_path': 'BOT.Charge.Shopify.slf.slf',
            'api_function': 'check_card',
            'handler_function': 'handle_slf'
        },
        {
            'name': '/tsh (SLF Test)',
            'handler_path': 'BOT.Charge.Shopify.slf.tsh',
            'api_path': 'BOT.Charge.Shopify.slf.slf',
            'api_function': 'check_card',
            'handler_function': 'tsh_handler'
        },
        {
            'name': '/msh (SLF Mass)',
            'handler_path': 'BOT.Charge.Shopify.slf.mass',
            'api_path': 'BOT.Charge.Shopify.slf.slf',
            'api_function': 'check_card',
            'handler_function': None  # Mass handler
        },
        {
            'name': '/sho (Shopify Checkout Single)',
            'handler_path': 'BOT.Charge.Shopify.sho.single',
            'api_path': 'BOT.Charge.Shopify.sho.sho',
            'api_function': 'create_shopify_charge',
            'handler_function': 'handle_sho_command'
        },
        {
            'name': '/msho (Shopify Checkout Mass)',
            'handler_path': 'BOT.Charge.Shopify.sho.mass',
            'api_path': 'BOT.Charge.Shopify.sho.sho',
            'api_function': 'create_shopify_charge',
            'handler_function': None
        },
        {
            'name': '/sg (Shopify Gateway Single)',
            'handler_path': 'BOT.Charge.Shopify.sg.single',
            'api_path': 'BOT.Charge.Shopify.sg.sg',
            'api_function': 'create_shopify_charge',
            'handler_function': None
        },
        {
            'name': '/msg (Shopify Gateway Mass)',
            'handler_path': 'BOT.Charge.Shopify.sg.mass',
            'api_path': 'BOT.Charge.Shopify.sg.sg',
            'api_function': 'create_shopify_charge',
            'handler_function': None
        },
        {
            'name': '/autosh or /ash (AutoShopify)',
            'handler_path': 'BOT.Charge.Shopify.ash.single',
            'api_path': 'BOT.Charge.Shopify.ash.api',
            'api_function': 'check_autoshopify',
            'handler_function': 'handle_autosh'
        },
        {
            'name': '/mautosh or /mash (AutoShopify Mass)',
            'handler_path': 'BOT.Charge.Shopify.ash.mass',
            'api_path': 'BOT.Charge.Shopify.ash.api',
            'api_function': 'check_autoshopify',
            'handler_function': None
        },
        # Stripe Commands
        {
            'name': '/st (Stripe $20 Charge)',
            'handler_path': 'BOT.Charge.Stripe.single',
            'api_path': 'BOT.Charge.Stripe.api',
            'api_function': 'async_stripe_charge',
            'handler_function': 'handle_stripe_charge'
        },
        {
            'name': '/au (Stripe Auth $0)',
            'handler_path': 'BOT.Auth.Stripe.single',
            'api_path': 'BOT.Auth.Stripe.fixme',
            'api_function': 'async_stripe_auth_fixme',
            'handler_function': 'handle_au_command'
        },
        {
            'name': '/mau (Stripe Auth Mass)',
            'handler_path': 'BOT.Auth.Stripe.mass',
            'api_path': 'BOT.Auth.Stripe.fixme',
            'api_function': 'async_stripe_auth_fixme',
            'handler_function': None
        },
        # Braintree Commands
        {
            'name': '/br (Braintree)',
            'handler_path': 'BOT.Charge.Braintree.single',
            'api_path': 'BOT.Charge.Braintree.api',
            'api_function': 'check_braintree',
            'handler_function': 'handle_braintree'
        },
        # Tool Commands
        {
            'name': '/bin (BIN Lookup)',
            'handler_path': 'BOT.tools.bin',
            'api_path': 'TOOLS.getbin',
            'api_function': 'get_bin_details',
            'handler_function': 'bin_lookup'
        },
        {
            'name': '/mbin (Mass BIN Lookup)',
            'handler_path': 'BOT.tools.bin',
            'api_path': 'TOOLS.getbin',
            'api_function': 'get_bin_details',
            'handler_function': 'mass_bin_lookup'
        },
        {
            'name': '/fake (Fake User Generator)',
            'handler_path': 'BOT.tools.fake',
            'api_path': None,  # Uses external API
            'api_function': None,
            'handler_function': 'generate_fake_user'
        },
        {
            'name': '/gen (Card Generator)',
            'handler_path': 'BOT.tools.gen',
            'api_path': 'TOOLS.getbin',
            'api_function': 'get_bin_details',
            'handler_function': 'gen_command'
        },
        # Helper Commands (no API)
        {
            'name': '/start (Start Command)',
            'handler_path': 'BOT.helper.start',
            'api_path': None,
            'api_function': None,
            'handler_function': 'start_command'
        },
        {
            'name': '/help (Help Command)',
            'handler_path': 'BOT.helper.help',
            'api_path': None,
            'api_function': None,
            'handler_function': 'help_command'
        },
        {
            'name': '/ping (Ping Command)',
            'handler_path': 'BOT.helper.ping',
            'api_path': None,
            'api_function': None,
            'handler_function': 'ping_handler'
        },
        {
            'name': '/info (Info Command)',
            'handler_path': 'BOT.helper.info',
            'api_path': None,
            'api_function': None,
            'handler_function': 'info_command'
        }
    ]

    print(f"Testing {len(commands_to_test)} command handlers...\n")

    for cmd in commands_to_test:
        results['total'] += 1

        print(f"\n{Colors.BOLD}Testing: {cmd['name']}{Colors.RESET}")

        # Test handler import
        handler_status = False
        api_status = False
        error_msg = None

        try:
            print_info(f"Handler module: {cmd['handler_path']}")
            handler_module = __import__(cmd['handler_path'], fromlist=[''])

            if cmd['handler_function']:
                if hasattr(handler_module, cmd['handler_function']):
                    print_success(f"Handler function '{cmd['handler_function']}' found")
                    handler_status = True
                else:
                    print_error(f"Handler function '{cmd['handler_function']}' NOT found")
                    error_msg = f"Missing handler function: {cmd['handler_function']}"
            else:
                print_success("Handler module loaded (mass handler)")
                handler_status = True

        except ImportError as e:
            print_error(f"Failed to import handler: {e}")
            error_msg = f"Import error: {e}"
        except Exception as e:
            print_error(f"Error: {e}")
            error_msg = str(e)

        # Test API import if applicable
        if cmd['api_path']:
            try:
                print_info(f"API module: {cmd['api_path']}")
                api_module = __import__(cmd['api_path'], fromlist=[''])

                if cmd['api_function']:
                    if hasattr(api_module, cmd['api_function']):
                        print_success(f"API function '{cmd['api_function']}' found")
                        api_status = True
                    else:
                        print_error(f"API function '{cmd['api_function']}' NOT found")
                        error_msg = f"Missing API function: {cmd['api_function']}"
                else:
                    print_success("API module loaded")
                    api_status = True

            except ImportError as e:
                print_error(f"Failed to import API: {e}")
                error_msg = f"API import error: {e}"
            except Exception as e:
                print_error(f"Error: {e}")
                error_msg = str(e)
        else:
            api_status = True  # No API required
            print_info("No API module required (uses external API or local only)")

        # Overall status
        if handler_status and api_status:
            print_success(f"✓ {cmd['name']} - READY")
            results['success'] += 1
        else:
            print_error(f"✗ {cmd['name']} - FAILED")
            results['failed'] += 1

        results['details'].append({
            'command': cmd['name'],
            'handler_ok': handler_status,
            'api_ok': api_status,
            'error': error_msg
        })

    # Print summary
    print_header("IMPORT TEST SUMMARY")
    print(f"Total Commands: {results['total']}")
    print_success(f"Imports Successful: {results['success']}")
    print_error(f"Imports Failed: {results['failed']}")

    success_rate = (results['success'] / results['total'] * 100) if results['total'] > 0 else 0
    print(f"\n{Colors.BOLD}Success Rate: {success_rate:.1f}%{Colors.RESET}\n")

    if results['failed'] > 0:
        print_header("FAILED IMPORTS")
        for detail in results['details']:
            if not (detail['handler_ok'] and detail['api_ok']):
                print_error(f"{detail['command']}")
                if detail['error']:
                    print(f"  Error: {detail['error']}")

    print_header("COMMAND -> API MAPPING VERIFICATION")

    print("\nCommands that call APIs:\n")

    api_commands = [
        ("Shopify SLF", ["/sh", "/tsh", "/msh"], "http://69.62.117.8:8000/check"),
        ("AutoShopify", ["/autosh", "/ash", "/mautosh", "/mash"], "http://136.175.187.188:8079/shc.php"),
        ("Shopify Checkout", ["/sho", "/msho"], "Shopify Checkout API"),
        ("Shopify Gateway", ["/sg", "/msg"], "Shopify Gateway API"),
        ("Stripe Charge", ["/st"], "Stripe API"),
        ("Stripe Auth", ["/au", "/mau"], "Stripe API"),
        ("Braintree", ["/br"], "Pixorize API"),
        ("BIN Lookup", ["/bin", "/mbin"], "Local BIN Database"),
        ("Fake Generator", ["/fake"], "https://randomuser.me/api/"),
        ("Card Generator", ["/gen"], "Local Luhn Algorithm + BIN DB")
    ]

    for api_name, commands, endpoint in api_commands:
        print(f"{Colors.CYAN}{api_name}:{Colors.RESET}")
        for cmd in commands:
            # Check if this command passed
            cmd_passed = any(
                d['handler_ok'] and d['api_ok']
                for d in results['details']
                if cmd in d['command']
            )
            status_icon = '✓' if cmd_passed else '✗'
            status_color = Colors.GREEN if cmd_passed else Colors.RED
            print(f"  {status_color}{status_icon}{Colors.RESET} {cmd.ljust(15)} → {endpoint}")
        print()

    return results

async def main():
    """Main entry point"""
    results = await verify_command_imports()

    # Return exit code
    if results['failed'] > 0:
        sys.exit(1)
    else:
        print_success("\n✓ All command handlers are properly configured!\n")
        sys.exit(0)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}Test interrupted by user{Colors.RESET}")
        sys.exit(130)
    except Exception as e:
        print_error(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
