import re
with open('DATA/checkout_collagesoup_com.html', 'r') as f:
    t = f.read()
# Find selectedDeliveryStrategy and handle
idx = t.find('selectedDeliveryStrategy')
if idx >= 0:
    snip = t[idx:idx+250]
    print('selectedDeliveryStrategy snippet:', repr(snip))
# Extract handle
m = re.search(r'selectedDeliveryStrategy[^}]*handle[\"\']?\s*:\s*[\"\']?&quot;?([a-zA-Z0-9_-]{20,})&quot;?', t)
if m:
    print('handle:', m.group(1))
