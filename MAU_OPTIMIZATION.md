# /mau Command - 33-Thread Parallel Processing

## Overview
Complete professional overhaul of `/mau` command with 33-thread parallel processing, default site `shop.nomade-studio.be`, new account creation per thread, and silver bullet bulletproof requests.

---

## Key Features

### ✅ 33-Thread Parallel Processing
- **Concurrency**: 33 simultaneous threads
- **Rate Limit**: 25 requests/second
- **Initial Delay**: 0.01s (ultra-fast)
- **New Account Per Thread**: Each thread creates a fresh account
- **Silver Bullet Speed**: Maximum performance with bulletproof reliability

### ✅ Default Site: shop.nomade-studio.be
- **Primary Site**: `https://shop.nomade-studio.be` (forced default for `/mau`)
- **Workflow**: Register → Dashboard → Payment Methods → Add Payment Method → Stripe API → Confirm
- **Fast Processing**: 35s timeout (optimized)

### ✅ New Account Creation Per Thread
- **Fresh Account**: Each card check creates a new account
- **Random Email**: Auto-generated per thread
- **Random Password**: Strong password per account
- **Isolated Sessions**: No session conflicts

### ✅ Professional Response Parsing
- **Format**: Matches `/au` response format exactly
- **Status Classification**: APPROVED, CCN LIVE, DECLINED, ERROR
- **BIN Lookup**: Full BIN details for hits
- **Real-time Updates**: Progress updates every 0.4s

---

## Code Changes

### `BOT/Auth/Stripe/mass.py`

#### MassRateLimiter Class
```python
class MassRateLimiter:
    """Rate limiter for 33-thread parallel processing - silver bullet performance."""
    def __init__(self, concurrency=33, requests_per_second=25):
        self.sem = asyncio.Semaphore(concurrency)
        self.requests_per_second = requests_per_second
        self.request_times = deque()
        self.lock = asyncio.Lock()
        self.current_delay = 0.01  # Ultra-fast for maximum speed
```

#### Parallel Processing
- **33 Threads**: `concurrency=33`
- **25 req/sec**: Token bucket rate limiting
- **New Account**: Each `check_one_card` creates fresh account
- **asyncio.as_completed**: Process results as they complete

#### Default Site Enforcement
```python
# Force nomade as default for /mau (silver bullet performance)
if gate_key != "nomade":
    gate_key = "nomade"
    gate_label = "nomade-studio.be"
```

---

## Workflow

### Per Card Check (33 Parallel Threads)

1. **Rate Limiting**: Wait for token bucket slot
2. **Minimal Delay**: 0.01s adaptive delay
3. **New Account Creation**:
   - GET `/my-account/` registration page
   - Generate random email/password
   - POST registration
   - GET dashboard `/my-account/`
   - GET `payment-methods/`
   - GET `add-payment-method/` (extract nonce)
4. **Stripe API**: Create payment method
5. **Confirm**: POST to `admin-ajax.php`
6. **Parse Response**: Match `/au` format
7. **Return Result**: APPROVED, CCN LIVE, or DECLINED

---

## Performance Metrics

### Before:
- Sequential processing
- Single account reuse
- Default gate selection
- Slower processing

### After:
- **33 threads** parallel ⚡
- **New account per thread** (bulletproof)
- **Forced nomade default** (fast site)
- **25 req/sec** rate limit
- **0.01s delays** (ultra-fast)
- **35s timeout** (optimized)

**Result**: **Silver bullet bulletproof requests** with maximum speed! 🚀

---

## Response Format

Matches `/au` format exactly:
- **APPROVED**: Card authenticated successfully
- **CCN LIVE**: Card is live (CVC/ZIP/AVS issues)
- **DECLINED**: Card declined
- **ERROR**: System errors

### Hit Message Format:
```
[#StripeAuth] | APPROVED/CCN LIVE ✦
━━━━━━━━━━━━━━━
[•] Card: cc|mm|yy|cvv
[•] Gateway: Stripe Auth [nomade-studio.be]
[•] Status: Approved ✅ / CCN Live ⚡
[•] Response: message
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
[+] BIN: xxxxxx
[+] Info: vendor - type - level
[+] Bank: bank name 🏦
[+] Country: country flag
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
[ﾒ] Checked By: user [plan badge]
[ϟ] Dev: Chr1shtopher
━━━━━━━━━━━━━━━
```

---

## Technical Details

### Account Creation Per Thread
- **Isolated**: Each thread has its own session
- **Random Credentials**: Unique email/password per check
- **No Conflicts**: No session sharing between threads
- **Fast Registration**: Optimized workflow

### Rate Limiting
- **Token Bucket**: 25 requests/second
- **Semaphore**: 33 concurrent threads
- **Minimal Delays**: 0.01s adaptive delay
- **Fast Processing**: Maximum throughput

### Error Handling
- **Network Errors**: Graceful handling
- **Timeout Errors**: 35s timeout
- **Site Errors**: Returns ERROR status
- **Stripe Errors**: Classified correctly

---

## Files Modified

1. **`BOT/Auth/Stripe/mass.py`**:
   - Added `MassRateLimiter` class (33 threads)
   - Rewrote processing to parallel
   - Forced nomade as default
   - Added stop button functionality
   - Optimized for speed

2. **`BOT/Auth/StripeAuth/nomade_checker.py`**:
   - Reduced timeout to 35s (from 40s)
   - Optimized for maximum speed

---

## Testing Checklist

- [x] 33 threads working correctly
- [x] New account creation per thread
- [x] Default site: nomade-studio.be
- [x] Response format matches /au
- [x] Parallel processing
- [x] Rate limiting
- [x] Stop button functionality
- [x] Progress updates
- [x] Error handling
- [x] Fast processing speed

---

## Performance Summary

### `/mau` - Silver Bullet Performance
- ✅ 33 threads parallel processing
- ✅ New account per thread (bulletproof)
- ✅ Default site: nomade-studio.be
- ✅ 25 requests/second
- ✅ 0.01s delays (ultra-fast)
- ✅ 35s timeout (optimized)
- ✅ Full response parsing
- ✅ Real-time progress updates

**Result**: Professional, bulletproof, silver bullet speed implementation! 🚀⚡

---

**All optimizations are production-ready and tested!**
