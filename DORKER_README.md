# Professional Shopify Dorker Bot

## Overview
A professional dorker bot that finds low checkout Shopify stores (<$10) using Google dorks with advanced captcha bypass capabilities.

## Features

### 🔍 **Advanced Search**
- Multiple Google dork queries optimized for low-priced Shopify stores
- Intelligent URL extraction and validation
- Automatic store verification with price checking
- Duplicate detection and filtering

### 🛡️ **Captcha Bypass**
- **2Captcha Integration**: Automatic reCAPTCHA v2 and hCaptcha solving
- **AntiCaptcha Integration**: Alternative captcha solving service
- **CloudScraper**: Built-in Cloudflare and basic captcha bypass
- **Smart Retry Logic**: Automatic retry with captcha solving

### ⚡ **Performance**
- Async/await for parallel processing
- Rate limiting to avoid bans
- Smart request delays
- Efficient URL extraction

### 📊 **Results Management**
- Save results to JSON file
- Download results as TXT file
- Add all stores to your site list with one click
- View top stores with prices

## Installation

### Required Packages
```bash
pip install cloudscraper beautifulsoup4 aiohttp
```

### Optional (for captcha solving):
```bash
# For 2Captcha
pip install 2captcha-python

# For AntiCaptcha
pip install anticaptchaofficial
```

## Usage

### Basic Usage
```
/dork
```
Finds up to 20 stores (default)

### Advanced Usage
```
/dork --max 50
```
Finds up to 50 stores

### With Captcha Bypass
```
/dork --2captcha YOUR_API_KEY
```
Uses 2Captcha API for automatic captcha solving

### Help
```
/dork --help
```
Shows all available options

## Commands

### `/dork`
Main dorking command. Searches Google for low checkout Shopify stores.

**Options:**
- `--max [number]` - Maximum stores to find (default: 20, max: 100)
- `--2captcha [api_key]` - 2Captcha API key for captcha bypass
- `--help` - Show help message

**Examples:**
```
/dork
/dork --max 50
/dork --2captcha YOUR_2CAPTCHA_API_KEY
```

## How It Works

1. **Search Phase**: Uses multiple optimized Google dork queries to find Shopify stores
2. **Extraction Phase**: Extracts and normalizes store URLs from search results
3. **Verification Phase**: Verifies each store:
   - Checks if it's actually a Shopify store
   - Extracts product prices
   - Filters for stores with products under $10
4. **Results Phase**: Saves verified stores with metadata

## Captcha Handling

The dorker automatically handles captchas using:

1. **CloudScraper**: First line of defense - bypasses many Cloudflare and basic captchas
2. **2Captcha Service**: If 2Captcha API key provided, automatically solves reCAPTCHA v2 and hCaptcha
3. **AntiCaptcha Service**: Alternative captcha solving service
4. **Smart Retry**: Automatically retries after solving captcha

## Results Format

Each verified store includes:
- **URL**: Store URL
- **Store Name**: Extracted store name
- **Low Prices**: List of prices found under $10
- **Min Price**: Lowest price found
- **Max Price**: Highest price found (under $10)
- **Verified**: Confirmation that store is valid

## Integration

The dorker integrates seamlessly with your bot:
- **Add All Button**: Adds all found stores to your site list
- **Download Button**: Downloads results as TXT file
- **Auto-save**: Results saved to `DATA/dorked_stores.json`

## Best Practices

1. **Use Captcha API**: For best results, use 2Captcha API key
2. **Reasonable Limits**: Don't set `--max` too high (50-100 is optimal)
3. **Be Patient**: Dorking takes time, especially with many stores
4. **Verify Stores**: Always verify stores before using in production
5. **Rate Limiting**: Built-in delays prevent IP bans

## Troubleshooting

### No Results Found
- Try different dork queries
- Check if Google is blocking requests
- Use captcha bypass service

### Captcha Errors
- Provide 2Captcha API key: `/dork --2captcha YOUR_KEY`
- Check API key balance
- Try again after a few minutes

### Slow Performance
- Reduce `--max` value
- Check internet connection
- Captcha solving adds time

## API Keys

### 2Captcha
1. Sign up at https://2captcha.com
2. Get your API key from dashboard
3. Use: `/dork --2captcha YOUR_API_KEY`

### AntiCaptcha
1. Sign up at https://anti-captcha.com
2. Get your API key
3. Configure in code (requires code modification)

## Notes

- Results are saved to `DATA/dorked_stores.json`
- Stores are automatically filtered for prices under $10
- Only verified Shopify stores are included
- Duplicate stores are automatically removed

## Support

For issues or questions, contact @Chr1shtopher
