import json
import re
import os

# Configuration
OWNER_ID = "6891929831"
DATA_FILE = "DATA/txtsite.json"
FILES_TO_PROCESS = [
    "Ex_Chk_Filter_Sites.txt"
]

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def parse_working_file(filename):
    sites = []
    if not os.path.exists(filename):
        print(f"File not found: {filename}")
        return sites
        
    with open(filename, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        
    # Regex to find blocks of URL and Gateway
    # Assuming standard block format
    blocks = content.split("------------------------------------------------------------")
    for block in blocks:
        url_match = re.search(r"URL: (https?://\S+)", block)
        gate_match = re.search(r"Gateway: (.+)", block)
        
        if url_match:
            url = url_match.group(1).strip()
            gate = gate_match.group(1).strip() if gate_match else "Normal"
            sites.append({"site": url, "gate": gate})
            
    return sites

def parse_simple_list(filename):
    sites = []
    if not os.path.exists(filename):
        print(f"File not found: {filename}")
        return sites

    with open(filename, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
        
    for line in lines:
        line = line.strip()
        if line.startswith("http"):
            sites.append({"site": line, "gate": "Normal"})
            
    return sites

def main():
    data = load_data()
    user_sites = data.get(OWNER_ID, [])
    
    # Create a set of existing URLs to avoid duplicates
    existing_urls = {s["site"] for s in user_sites}
    
    new_count = 0
    
    for filename in FILES_TO_PROCESS:
        print(f"Processing {filename}...")
        if "working_under" in filename:
            found_sites = parse_working_file(filename)
        else:
            found_sites = parse_simple_list(filename)
            
        print(f"Found {len(found_sites)} sites in {filename}")
        
        for s in found_sites:
            if s["site"] not in existing_urls:
                user_sites.append(s)
                existing_urls.add(s["site"])
                new_count += 1
                
    data[OWNER_ID] = user_sites
    save_data(data)
    print(f"Successfully added {new_count} new sites. Total sites for {OWNER_ID}: {len(user_sites)}")

if __name__ == "__main__":
    main()
