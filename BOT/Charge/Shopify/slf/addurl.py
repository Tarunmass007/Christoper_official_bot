"""
FIXED /addurl Handler for Shopify Sites
Key fixes for stickerdad.com and similar sites:

1. Enhanced product parsing with cloudscraper fallback
2. Proper test validation with ReceiptId check
3. Better error surfacing for debugging
4. Price limit validation ($25 max)
"""

@Client.on_message(filters.command(["addurl", "slfurl", "seturl"]))
async def add_site_handler(client: Client, message: Message):
    """
    FIXED: Enhanced /addurl with proper validation for stickerdad.com
    """
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    clickable_name = f"<a href='tg://user?id={user_id}'>{user_name}</a>"
    
    # Check registration
    users = load_users()
    if user_id not in users:
        return await message.reply(
            """<pre>Access Denied 🚫</pre>
<b>Register first:</b> <code>/register</code>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Get URLs from command
    args = message.command[1:]
    
    # Support reply to message
    if not args and message.reply_to_message and message.reply_to_message.text:
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        args = re.findall(url_pattern, message.reply_to_message.text)
        if not args:
            domain_pattern = r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}'
            args = re.findall(domain_pattern, message.reply_to_message.text)
    
    if not args:
        return await message.reply(
            """<pre>📖 Add Site Guide</pre>
━━━━━━━━━━━━━━━
<b>Usage:</b>
<code>/addurl https://store.myshopify.com</code>
<code>/addurl store.com</code>

<b>Works with:</b> stickerdad.com and all Shopify sites
<b>Max Price:</b> $25.00 total checkout
━━━━━━━━━━━━━━━""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Limit to 10 URLs
    urls = args[:10]
    total_urls = len(urls)
    
    start_time = time.time()
    
    # Show processing
    status_msg = await message.reply(
        f"""<pre>🔍 Validating Sites...</pre>
━━━━━━━━━━━━━
<b>Sites:</b> <code>{total_urls}</code>
<b>Status:</b> <i>Checking products...</i>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )
    
    try:
        user_proxy = get_rotating_proxy(int(user_id))
        
        # STEP 1: Validate products with enhanced parsing
        async def validate_with_progress():
            results = []
            for idx, url in enumerate(urls, 1):
                try:
                    async with TLSAsyncSession(timeout_seconds=20, proxy=user_proxy) as session:
                        # Enhanced validation with cloudscraper fallback
                        result = await validate_and_parse_site_enhanced(url, session, user_proxy)
                    results.append(result)
                    
                    # Quick progress update
                    if idx % 1 == 0 or idx == len(urls):
                        await status_msg.edit_text(
                            f"""<pre>🔍 Validating Sites...</pre>
━━━━━━━━━━━━━
<b>Progress:</b> <code>{idx}/{total_urls}</code>
<b>Status:</b> <i>Parsing lowest product...</i>""",
                            parse_mode=ParseMode.HTML
                        )
                except Exception as e:
                    results.append({
                        "valid": False,
                        "url": url,
                        "error": f"Parse error: {str(e)[:40]}",
                        "price": "N/A"
                    })
            return results
        
        results = await validate_with_progress()
        
        valid_sites = [r for r in results if r["valid"]]
        invalid_sites = [r for r in results if not r["valid"]]

        if not valid_sites:
            time_taken = round(time.time() - start_time, 2)
            error_lines = []
            for site in invalid_sites[:5]:
                err = site.get('error', 'Invalid')[:45]
                error_lines.append(f"• <code>{site['url'][:35]}</code>\n  └─ {err}")
            error_text = "\n".join(error_lines)
            return await status_msg.edit_text(
                f"""<pre>Invalid Sites ❌</pre>
━━━━━━━━━━━━━
<b>Checked:</b> <code>{total_urls}</code>
<b>Valid:</b> <code>0</code>

<b>Errors:</b>
{error_text}

<b>For stickerdad.com:</b> Make sure URL is exact
<b>Example:</b> <code>/addurl https://stickerdad.com</code>
━━━━━━━━━━━━━
⏱️ <code>{time_taken}s</code>""",
                parse_mode=ParseMode.HTML
            )

        # STEP 2: Test sites with proper gate validation
        await status_msg.edit_text(
            f"""<pre>✓ Products Found</pre>
━━━━━━━━━━━━━
<b>Valid:</b> <code>{len(valid_sites)}</code>
<b>Status:</b> <i>Testing checkout (receipt validation)...</i>""",
            parse_mode=ParseMode.HTML
        )
        
        # Enhanced test with better error surfacing
        async def test_site_enhanced(site_info):
            """Test with detailed error capture"""
            logger.info(f"🧪 Testing {site_info['url']}")
            has_rec, test_res = await test_site_with_card_enhanced(
                site_info["url"], 
                user_proxy, 
                max_retries=3
            )
            if has_rec:
                pr = test_res.get("Price") or site_info.get("price") or "N/A"
                try:
                    pv = float(pr)
                    pr = f"{pv:.2f}" if pv != int(pv) else str(int(pv))
                except (TypeError, ValueError):
                    pr = str(pr) if pr else "N/A"
                site_info["price"] = pr
                site_info["formatted_price"] = f"${pr}"
                site_info["test_result"] = test_res.get("Response", "SUCCESS")
                # Save immediately
                save_site_for_user_unified(user_id, site_info["url"], "Normal", pr)
                logger.info(f"✅ {site_info['url']} verified with ReceiptId")
                return site_info
            else:
                # Surface actual error for debugging
                error = test_res.get("Response", "NO_RECEIPT")
                logger.warning(f"❌ {site_info['url']} failed: {error}")
                site_info["test_error"] = error
                return None
        
        # Test all in parallel
        test_tasks = [test_site_enhanced(v) for v in valid_sites]
        test_results = await asyncio.gather(*test_tasks, return_exceptions=True)
        
        # Collect successful
        sites_with_receipt = []
        test_errors = []
        for result in test_results:
            if result and not isinstance(result, Exception):
                sites_with_receipt.append(result)
            elif isinstance(result, Exception):
                test_errors.append(str(result)[:50])
        
        if not sites_with_receipt:
            time_taken = round(time.time() - start_time, 2)
            # Show actual gate errors for debugging
            error_summary = []
            for site in valid_sites[:3]:
                if hasattr(site, 'test_error'):
                    error_summary.append(f"• {site['url'][:30]}: {site['test_error'][:40]}")
            error_text = "\n".join(error_summary) if error_summary else "All test checkouts failed to generate receipt"
            
            return await status_msg.edit_text(
                f"""<pre>No Sites Verified ❌</pre>
━━━━━━━━━━━━━
<b>Products found but checkout test failed.</b>

<b>Gate Errors:</b>
{error_text}

<b>For stickerdad.com:</b>
• Check if site is actually working
• Try with proxy: <code>/setpx</code>
• Site may have checkout restrictions

<b>Debug:</b> Valid products detected, but no ReceiptId from gate
━━━━━━━━━━━━━
⏱️ <code>{time_taken}s</code>""",
                parse_mode=ParseMode.HTML
            )
        
        # SUCCESS - show results
        time_taken = round(time.time() - start_time, 2)
        primary_site = sites_with_receipt[0]
        
        response_lines = [
            f"<pre>Site Verified ✅</pre>",
            "━━━━━━━━━━━━━",
            f"[⌯] <b>Site:</b> <code>{primary_site['url']}</code>",
            f"[⌯] <b>Gateway:</b> <code>Shopify Normal</code>",
            f"[⌯] <b>Price:</b> <code>${primary_site['price']}</code>",
            f"[⌯] <b>Status:</b> <code>Active ✓</code> (receipt verified)",
            f"[⌯] <b>Result:</b> <code>{primary_site.get('test_result', 'OK')}</code>",
        ]
        
        if len(sites_with_receipt) > 1:
            response_lines.append("")
            response_lines.append(f"<b>Also verified ({len(sites_with_receipt) - 1}):</b>")
            for s in sites_with_receipt[1:3]:
                response_lines.append(f"• <code>{s['url'][:35]}</code> [${s['price']}]")
        
        if invalid_sites:
            response_lines.append("")
            response_lines.append(f"<b>Failed:</b> <code>{len(invalid_sites)}</code> sites")
        
        response_lines.extend([
            "━━━━━━━━━━━━━",
            f"[⌯] <b>Check cards:</b> <code>/sh</code> or <code>/slf</code>",
            f"[⌯] <b>Time:</b> <code>{time_taken}s</code>",
            f"[⌯] <b>User:</b> {clickable_name}",
        ])
        
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✓ Check Card", callback_data="show_check_help"),
                InlineKeyboardButton("📋 Sites", callback_data="show_my_sites")
            ]
        ])
        
        await status_msg.edit_text(
            "\n".join(response_lines),
            parse_mode=ParseMode.HTML,
            reply_markup=buttons,
            disable_web_page_preview=True
        )
        
    except Exception as e:
        time_taken = round(time.time() - start_time, 2)
        logger.error(f"❌ /addurl error: {e}", exc_info=True)
        await status_msg.edit_text(
            f"""<pre>Error ⚠️</pre>
━━━━━━━━━━━━━
<b>Error:</b> <code>{str(e)[:100]}</code>
<b>Time:</b> <code>{time_taken}s</code>

<b>Try again or report issue.</b>""",
            parse_mode=ParseMode.HTML
        )


async def validate_and_parse_site_enhanced(
    url: str,
    session: TLSAsyncSession,
    proxy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    ENHANCED: Better parsing with cloudscraper fallback for stickerdad.com
    """
    result = {
        "valid": False,
        "url": url,
        "gateway": "Normal",
        "price": "N/A",
        "error": None,
        "product_id": None,
        "product_title": None,
        "currency": "USD",
        "formatted_price": None,
    }
    
    try:
        normalized_url = normalize_url(url)
        result["url"] = normalized_url
        
        # Try regular fetch first
        products = await fetch_products_json(session, normalized_url, proxy)
<<<<<<< HEAD
        # Enhanced: one more cloudscraper attempt when session fetch returned no products (stickerdad.com etc.)
=======
        
        # If failed, try cloudscraper
>>>>>>> 956d20fcca140dbf0cbec8a2c29bc10adc94b725
        if not products and HAS_CLOUDSCRAPER:
            try:
                products = await asyncio.to_thread(
                    _fetch_products_cloudscraper_sync,
                    normalized_url,
<<<<<<< HEAD
                    proxy,
                )
                if products:
                    pass  # continue with parsing below
            except Exception:
                pass
        if not products:
            result["error"] = "No products (not Shopify or protected)"
            return result
        lowest = find_lowest_variant_from_products(products)
        if not lowest:
            result["error"] = "No parseable variants from products.json"
=======
                    proxy
                )
                logger.info(f"✅ Products via cloudscraper for {normalized_url}")
            except Exception as e:
                logger.debug(f"Cloudscraper fetch failed: {e}")
        
        if not products:
            result["error"] = "No products (not Shopify or protected)"
>>>>>>> 956d20fcca140dbf0cbec8a2c29bc10adc94b725
            return result
        
        lowest = find_lowest_variant_from_products(products)
        if not lowest:
            result["error"] = "No valid variants"
            return result
        
        # Check price limit
        price_value = lowest['price']
        if price_value > 25.0:
            result["error"] = f"Price ${price_value:.2f} > $25 limit"
            result["valid"] = False
            return result
        
        # Populate
        result["valid"] = True
        result["product_id"] = lowest['variant'].get('id')
        result["product_title"] = lowest['product'].get('title', 'N/A')[:50]
        result["price"] = f"{lowest['price']:.2f}"
        result["formatted_price"] = f"${lowest['price']:.2f}"
        
        logger.info(f"✅ Validated {normalized_url}: {result['product_title']} at ${result['price']}")
        return result
        
    except Exception as e:
        logger.error(f"❌ Validation error for {url}: {e}")
        result["error"] = str(e)[:50]
        return result


async def test_site_with_card_enhanced(
    url: str, 
    proxy: Optional[str] = None, 
    max_retries: int = 3
) -> tuple[bool, dict]:
    """
    ENHANCED: Better error surfacing for debugging stickerdad.com
    Returns (has_receipt, result_dict_with_detailed_error)
    """
    proxy_url = None
    if proxy and str(proxy).strip():
        px = str(proxy).strip()
        proxy_url = px if px.startswith(("http://", "https://")) else f"http://{px}"

    last_res = {"Response": "NO_RECEIPT", "ReceiptId": None, "Price": "0.00"}

    for attempt in range(max_retries):
        try:
            async with TLSAsyncSession(timeout_seconds=70, proxy=proxy_url) as session:
                logger.info(f"🧪 Test attempt {attempt + 1}/{max_retries} for {url}")
                res = await autoshopify_with_captcha_retry(
                    url, TEST_CARD, session, max_captcha_retries=2, proxy=proxy_url
                )
                last_res = res
                
                # Check for receipt
                if res.get("ReceiptId"):
                    logger.info(f"✅ Receipt found: {res.get('ReceiptId')}")
                    return True, res
                else:
                    logger.warning(f"⚠️ No receipt: {res.get('Response')}")
                    
        except Exception as e:
            logger.error(f"❌ Test exception attempt {attempt + 1}: {e}")
            last_res = {"Response": f"TEST_ERROR: {str(e)[:60]}", "ReceiptId": None, "Price": "0.00"}
            if attempt == max_retries - 1:
                return False, last_res
            await asyncio.sleep(0.2 * (attempt + 1))
            continue

    # Return actual error for debugging
    resp = (last_res.get("Response") or "").strip()
    if not resp:
        resp = "NO_RECEIPT"
    
    logger.warning(f"❌ Final result: {resp}")
    return False, {"Response": resp, "ReceiptId": None, "Price": last_res.get("Price") or "0.00"}
<<<<<<< HEAD


def get_user_current_site(user_id: str) -> Optional[Dict[str, str]]:
    """Get user's currently saved site using unified site manager."""
    site = get_primary_site(user_id)
    if site:
        return {
            "site": site.get("url"),
            "gate": site.get("gateway"),
            "price": site.get("price", "N/A")
        }
    return None


# ==================== COMMAND HANDLERS ====================

@Client.on_message(filters.command(["addurl", "slfurl", "seturl"]))
async def add_site_handler(client: Client, message: Message):
    """
    Handle /addurl command to add and validate Shopify sites.
    Works in both private chats and groups.
    Parses lowest product and validates before saving.
    
    IMPORTANT: No special handling for admin/owner - everyone is treated the same.
    All users (including admin/owner) must add sites manually. No default sites.
    
    Usage:
        /addurl https://example.myshopify.com
        /addurl example.com
        /addurl site1.com site2.com site3.com (multiple sites)
    """
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    clickable_name = f"<a href='tg://user?id={user_id}'>{user_name}</a>"
    
    # Check if user is registered
    users = load_users()
    if user_id not in users:
        return await message.reply(
            """<pre>Access Denied 🚫</pre>
<b>You must register first using</b> <code>/register</code> <b>command.</b>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Get URLs from command
    args = message.command[1:]
    
    # Also support reply to message containing URLs
    if not args and message.reply_to_message and message.reply_to_message.text:
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        args = re.findall(url_pattern, message.reply_to_message.text)
        if not args:
            domain_pattern = r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}'
            args = re.findall(domain_pattern, message.reply_to_message.text)
    
    if not args:
        return await message.reply(
            """<pre>📖 Add Site Guide</pre>
━━━━━━━━━━━━━━━
<b>Add a Shopify site for checking:</b>

<code>/addurl https://store.myshopify.com</code>
<code>/addurl store.com</code>
<code>/addurl site1.com site2.com</code> <i>(multiple)</i>

<b>After adding:</b> Use <code>/sh</code> or <code>/slf</code> to check cards

<b>Other Commands:</b>
• <code>/mysite</code> - View your current site
• <code>/txturl</code> - Add multiple sites
• <code>/txtls</code> - List all your sites
• <code>/delsite</code> - Remove your site
━━━━━━━━━━━━━━━
<i>Works in groups & private chats!</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Limit to 10 URLs at once
    urls = args[:10]
    total_urls = len(urls)
    
    start_time = time.time()
    
    # Show processing message
    status_msg = await message.reply(
        f"""<pre>🔍 Validating Shopify Sites...</pre>
━━━━━━━━━━━━━
<b>Sites:</b> <code>{total_urls}</code>
<b>Status:</b> <i>Parsing lowest products...</i>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Get user's proxy if set
        user_proxy = get_rotating_proxy(int(user_id))
        
        # Validate all sites with lowest product parsing - show progress quickly
        async def validate_with_progress():
            results = []
            for idx, url in enumerate(urls, 1):
                try:
                    async with TLSAsyncSession(timeout_seconds=FAST_TIMEOUT, proxy=user_proxy) as session:
                        result = await validate_and_parse_site(url, session, user_proxy)
                    results.append(result)
                    # Update progress quickly
                    if idx % 1 == 0 or idx == len(urls):
                        await status_msg.edit_text(
                            f"""<pre>🔍 Validating Shopify Sites...</pre>
━━━━━━━━━━━━━
<b>Sites:</b> <code>{total_urls}</code>
<b>Progress:</b> <code>{idx}/{total_urls}</code>
<b>Status:</b> <i>Parsing products & checking price...</i>""",
                            parse_mode=ParseMode.HTML
                        )
                except Exception as e:
                    results.append({
                        "valid": False,
                        "url": url,
                        "error": str(e)[:50],
                        "price": "N/A"
                    })
            return results
        
        results = await validate_with_progress()
        
        valid_sites = [r for r in results if r["valid"]]
        invalid_sites = [r for r in results if not r["valid"]]

        if not valid_sites:
            time_taken = round(time.time() - start_time, 2)
            error_lines = []
            for site in invalid_sites[:5]:
                err = site.get('error', 'Invalid') or 'Invalid'
                error_lines.append(f"• <code>{site['url'][:40]}</code> → {err}")
            error_text = "\n".join(error_lines)
            return await status_msg.edit_text(
                f"""<pre>Invalid Site(s) ❌</pre>
━━━━━━━━━━━━━
<b>Checked:</b> <code>{total_urls}</code>
<b>Valid:</b> <code>0</code> (no products from products.json)

<b>Errors:</b>
{error_text}

<b>Tips:</b>
• Use a Shopify store with <code>/products.json</code>
• Full URL: <code>https://store.com</code>
━━━━━━━━━━━━━
⏱️ <b>Time:</b> <code>{time_taken}s</code>""",
                parse_mode=ParseMode.HTML
            )

        # Test sites in parallel for speed - save immediately when receipt found
        proxy_url = user_proxy
        if user_proxy and str(user_proxy).strip():
            px = str(user_proxy).strip()
            proxy_url = px if px.startswith(("http://", "https://")) else f"http://{px}"
        
        sites_with_receipt = []
        saved_sites = []
        
        # Test all valid sites in parallel (fast) - show progress quickly
        await status_msg.edit_text(
            f"""<pre>🔍 Testing Sites...</pre>
━━━━━━━━━━━━━
<b>Valid Sites:</b> <code>{len(valid_sites)}</code>
<b>Status:</b> <i>Running test checkout with bill generation...</i>""",
            parse_mode=ParseMode.HTML
        )
        
        async def test_and_save(site_info):
            has_rec, test_res = await test_site_with_card(site_info["url"], proxy_url, max_retries=3)
            if has_rec:
                pr = test_res.get("Price") or site_info.get("price") or "N/A"
                try:
                    pv = float(pr)
                    pr = f"{pv:.2f}" if pv != int(pv) else str(int(pv))
                except (TypeError, ValueError):
                    pr = str(pr) if pr else "N/A"
                site_info["price"] = pr
                site_info["formatted_price"] = f"${pr}"
                site_info["test_result"] = test_res.get("Response", "OK")
                save_site_for_user_unified(user_id, site_info["url"], site_info.get("gateway", "Normal"), pr)
                return site_info
            site_info["test_error"] = (test_res.get("Response") or "NO_RECEIPT").strip()
            return None
        
        # Run all tests in parallel
        test_tasks = [test_and_save(v) for v in valid_sites]
        test_results = await asyncio.gather(*test_tasks, return_exceptions=True)
        
        # Collect successful sites
        for result in test_results:
            if result and not isinstance(result, Exception):
                sites_with_receipt.append(result)
        if not sites_with_receipt:
            time_taken = round(time.time() - start_time, 2)
            error_lines = []
            for s in valid_sites[:5]:
                err = (s.get("test_error") or "NO_RECEIPT").strip()[:50]
                error_lines.append(f"• <code>{s['url'][:35]}</code>\n  └─ {err}")
            error_text = "\n".join(error_lines) if error_lines else "All test checkouts failed to generate receipt."
            return await status_msg.edit_text(
                f"""<pre>No Sites Verified ❌</pre>
━━━━━━━━━━━━━
<b>Gate test did not return receipt/bill.</b>
(Site has products; test checkout failed.)
<b>Gate error:</b> <code>{(valid_sites[0].get('test_error') or 'NO_RECEIPT')[:60]}</code>

<b>Tips:</b>
• Set proxy: <code>/setpx</code>
• Use a gate that completes checkout with receipt
━━━━━━━━━━━━━
⏱️ <b>Time:</b> <code>{time_taken}s</code>""",
                parse_mode=ParseMode.HTML
            )
        time_taken = round(time.time() - start_time, 2)
        primary_site = sites_with_receipt[0] if sites_with_receipt else None
        if not primary_site:
            return await status_msg.edit_text(
                f"""<pre>No Sites Verified ❌</pre>
━━━━━━━━━━━━━
<b>Gate test did not return receipt/bill.</b>
(All sites tested; no receipts found.)

<b>Tips:</b>
• Set proxy: <code>/setpx</code>
• Use a gate that completes checkout with receipt
━━━━━━━━━━━━━
⏱️ <b>Time:</b> <code>{time_taken}s</code>""",
                parse_mode=ParseMode.HTML
            )
        
        site_url = primary_site["url"]
        gateway = primary_site.get("gateway", "Normal")
        price = primary_site["price"]
        product_title = primary_site.get("product_title", "N/A")
        formatted_price = primary_site.get("formatted_price", f"${price}")
        # Already saved in parallel test above
        response_lines = [
            f"<pre>Site Added Successfully ✅</pre>",
            "━━━━━━━━━━━━━",
            f"[⌯] <b>Site:</b> <code>{site_url}</code>",
            f"[⌯] <b>Gateway:</b> <code>Shopify Normal</code>",
            f"[⌯] <b>Price:</b> <code>{formatted_price}</code>",
            f"[⌯] <b>Product:</b> <code>{product_title}...</code>",
            f"[⌯] <b>Status:</b> <code>Active ✓</code> (test card verified)",
        ]
        if len(sites_with_receipt) > 1:
            response_lines.append("")
            response_lines.append(f"<b>Also verified ({len(sites_with_receipt) - 1}):</b>")
            for s in sites_with_receipt[1:5]:
                response_lines.append(f"• <code>{s['url'][:35]}</code> [${s.get('price', 'N/A')}]")
        if invalid_sites:
            response_lines.append("")
            response_lines.append(f"<b>Failed:</b> <code>{len(invalid_sites)}</code> site(s)")
        response_lines.extend([
            "━━━━━━━━━━━━━",
            f"[⌯] <b>Command:</b> <code>/sh</code> or <code>/slf</code>",
            f"[⌯] <b>Time:</b> <code>{time_taken}s</code>",
            f"[⌯] <b>User:</b> {clickable_name}",
        ])
        
        # Buttons
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✓ Check Card", callback_data="show_check_help"),
                InlineKeyboardButton("📋 My Sites", callback_data="show_my_sites")
            ]
        ])
        
        await status_msg.edit_text(
            "\n".join(response_lines),
            parse_mode=ParseMode.HTML,
            reply_markup=buttons,
            disable_web_page_preview=True
        )
        
    except Exception as e:
        time_taken = round(time.time() - start_time, 2)
        await status_msg.edit_text(
            f"""<pre>Error Occurred ⚠️</pre>
━━━━━━━━━━━━━
<b>Error:</b> <code>{str(e)[:100]}</code>
<b>Time:</b> <code>{time_taken}s</code>

<b>Please try again or contact support.</b>""",
            parse_mode=ParseMode.HTML
        )


@Client.on_message(filters.command(["mysite", "getsite", "siteinfo"]))
async def my_site_handler(client: Client, message: Message):
    """Show user's currently saved primary site."""
    user_id = str(message.from_user.id)
    
    site_info = get_user_current_site(user_id)
    
    if not site_info:
        return await message.reply(
            """<pre>No Site Found ℹ️</pre>
<b>You haven't added any site yet.</b>

Use <code>/addurl https://store.com</code> to add a Shopify site.""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Get all sites count
    all_sites = get_user_sites(user_id)
    total_count = len(all_sites)
    
    await message.reply(
        f"""<pre>Your Primary Site 📋</pre>
━━━━━━━━━━━━━
[⌯] <b>Site:</b> <code>{site_info.get('site', 'N/A')}</code>
[⌯] <b>Gateway:</b> <code>{site_info.get('gate', 'Unknown')}</code>
[⌯] <b>Price:</b> <code>${site_info.get('price', 'N/A')}</code>
━━━━━━━━━━━━━
<b>Total Sites:</b> <code>{total_count}</code>
<b>Commands:</b> <code>/sh</code> or <code>/slf</code> to check cards
<b>List All:</b> <code>/txtls</code>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )


@Client.on_message(filters.command(["delsite", "removesite", "clearsite", "remurl"]))
async def delete_site_handler(client: Client, message: Message):
    """Delete all of user's saved sites (unified storage). Idempotent; safe to run repeatedly."""
    user_id = str(message.from_user.id)
    try:
        count = clear_user_sites(user_id)
        if count > 0:
            return await message.reply(
                f"<pre>Sites Removed ✅</pre>\n<b>Cleared {count} site(s).</b> You can add again with <code>/addurl</code>.",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        await message.reply(
            "<pre>No Site Found ℹ️</pre>\n<b>You don't have any site saved.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.reply(
            f"<pre>Error ⚠️</pre>\n<code>{str(e)[:80]}</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )


# ==================== CALLBACK HANDLERS ====================

@Client.on_callback_query(filters.regex("^show_check_help$"))
async def show_check_help_callback(client, callback_query):
    """Show card checking help."""
    await callback_query.answer()
    await callback_query.message.reply(
        """<pre>📖 Card Checking Guide</pre>
━━━━━━━━━━━━━━━
<b>Single Card Check:</b>
<code>/sh 4111111111111111|12|2025|123</code>

<b>Reply to Card:</b>
Reply to a message containing a card with <code>/sh</code>

<b>Mass Check:</b>
<code>/msh</code> (reply to list of cards)

<b>Format:</b> <code>cc|mm|yy|cvv</code> or <code>cc|mm|yyyy|cvv</code>
━━━━━━━━━━━━━━━
<b>Supported Gates:</b>
• Shopify Payments (Normal)
• Stripe
• PayPal/Braintree
━━━━━━━━━━━━━━━""",
        parse_mode=ParseMode.HTML
    )


@Client.on_callback_query(filters.regex("^show_my_sites$"))
async def show_my_sites_callback(client, callback_query):
    """Show user's all sites."""
    user_id = str(callback_query.from_user.id)
    sites = get_user_sites(user_id)
    
    if not sites:
        await callback_query.answer("❌ No sites saved!", show_alert=True)
        return
    
    # Build sites list
    lines = ["<pre>📋 Your Sites</pre>", "━━━━━━━━━━━━━"]
    
    for i, site in enumerate(sites[:10], 1):
        is_primary = "⭐" if site.get("is_primary") else ""
        url = site.get("url", "N/A")[:35]
        lines.append(f"{i}. {is_primary}<code>{url}</code>")
    
    if len(sites) > 10:
        lines.append(f"\n<i>...and {len(sites) - 10} more</i>")
    
    lines.append("━━━━━━━━━━━━━")
    lines.append(f"<b>Total:</b> <code>{len(sites)}</code> sites")
    
    await callback_query.answer()
    await callback_query.message.reply(
        "\n".join(lines),
        parse_mode=ParseMode.HTML
    )


@Client.on_callback_query(filters.regex("^show_my_site$"))
async def show_my_site_callback(client, callback_query):
    """Show user's primary site."""
    user_id = str(callback_query.from_user.id)
    site_info = get_user_current_site(user_id)
    
    if site_info:
        await callback_query.answer(
            f"📋 YOUR SITE\n\n"
            f"🌐 {site_info.get('site', 'N/A')[:40]}\n"
            f"⚡ {site_info.get('gate', 'Unknown')[:30]}\n\n"
            f"Use /sh to check cards!",
            show_alert=True
        )
    else:
        await callback_query.answer(
            "❌ No site saved!\n\n"
            "Use /addurl to add a site.",
            show_alert=True
        )


@Client.on_callback_query(filters.regex("^plans_info$"))
async def plans_info_callback(client, callback_query):
    """Show plans information."""
    await callback_query.answer()
    await callback_query.message.reply(
        """<pre>💎 Available Plans</pre>
━━━━━━━━━━━━━━━
<b>🎟️ Free Plan:</b>
• 10 credits/day
• 10s antispam delay
• Basic features

<b>⭐ Premium Plan:</b>
• 500 credits/day
• 3s antispam delay
• All gates access
• Priority support

<b>👑 VIP Plan:</b>
• Unlimited credits
• No antispam delay
• All features
• 24/7 support
━━━━━━━━━━━━━━━
Use <code>/buy</code> to purchase!""",
        parse_mode=ParseMode.HTML
    )
=======
>>>>>>> 956d20fcca140dbf0cbec8a2c29bc10adc94b725
