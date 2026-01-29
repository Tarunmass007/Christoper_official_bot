import csv
import requests

def get_bin_details(bin_number):
    try:
        # Fetch from live API
        url = f"https://bins.antipublic.cc/bins/{bin_number}"
        res = requests.get(url, timeout=5)

        if res.status_code == 200:
            data = res.json()
            if "detail" in data and "not found" in data["detail"].lower():
                return None

            return {
                "bin": data.get("bin"),
                "country": data.get("country_name"),
                "flag": data.get("country_flag"),
                "vendor": data.get("brand"),
                "type": data.get("type"),
                "level": data.get("level"),
                "bank": data.get("bank")
            }

    except Exception as e:
        print(f"[ERROR] Failed to fetch BIN details: {e}")

    return None