import re
with open('DATA/checkout_collagesoup_com.html', 'r') as f:
    t = f.read()
m = re.search(r'deliveryMethodTypes&quot;:\s*\[&quot;([^&]+)&quot;', t)
if m:
    print('deliveryMethodTypes:', m.group(1))
m2 = re.search(r'deliveryMethodTypes&quot;:\[&quot;([^&]+)&quot;', t)
if m2:
    print('alt:', m2.group(0)[:100])
# Find NONE in delivery context
idx = t.find('deliveryMethodTypes')
if idx >= 0:
    print('snippet:', repr(t[idx:idx+150]))
