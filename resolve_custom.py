#!/usr/bin/env python3
"""
resolve_custom.py
-----------------
Runs inside a Mininet host (e.g. h1) to test the *custom* DNS resolver (10.0.0.5).
Sends raw DNS queries to that server, records latency, and saves results to CSV.

Usage:
    python3 resolve_custom.py H1
"""

import socket
import time
import csv
import os
import sys
import struct
import random

DNS_SERVER_IP = "10.0.0.5"
DNS_SERVER_PORT = 53
RESULTS_DIR = "results_custom"
TIMEOUT = 5.0  # seconds

# ---------------- DNS packet helpers ----------------

def encode_domain(domain):
    parts = domain.strip(".").split(".")
    return b"".join(bytes([len(p)]) + p.encode() for p in parts) + b"\x00"

def decode_domain(data, offset):
    labels = []
    while True:
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if (length & 0xC0) == 0xC0:
            ptr = struct.unpack_from("!H", data, offset)[0] & 0x3FFF
            sub, _ = decode_domain(data, ptr)
            labels.append(sub)
            offset += 2
            break
        labels.append(data[offset + 1 : offset + 1 + length].decode())
        offset += 1 + length
    return ".".join(labels), offset

def build_query(domain, qtype=1, qclass=1):
    tid = random.randint(0, 0xFFFF)
    header = struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    question = encode_domain(domain) + struct.pack("!HH", qtype, qclass)
    return header + question, tid

def parse_response(data):
    """Return list of A record IPs"""
    if not data or len(data) < 12:
        return []
    _, _, qdcount, ancount, _, _ = struct.unpack_from("!HHHHHH", data, 0)
    offset = 12
    # Skip question
    for _ in range(qdcount):
        _, offset = decode_domain(data, offset)
        offset += 4  # type + class
    # Parse answers
    ips = []
    for _ in range(ancount):
        _, offset = decode_domain(data, offset)
        rtype, rclass, ttl, rdlen = struct.unpack_from("!HHIH", data, offset)
        offset += 10
        rdata = data[offset : offset + rdlen]
        offset += rdlen
        if rtype == 1 and len(rdata) == 4:  # A record
            ip = ".".join(map(str, rdata))
            ips.append(ip)
    return ips

# ---------------- DNS query to custom resolver ----------------

def query_custom_resolver(domain):
    """Send DNS query to custom resolver and measure latency"""
    query, tid = build_query(domain)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)
    start = time.time()
    try:
        sock.sendto(query, (DNS_SERVER_IP, DNS_SERVER_PORT))
        data, _ = sock.recvfrom(512)
        latency = (time.time() - start) * 1000
        ips = parse_response(data)
        return ips, latency
    except socket.timeout:
        return [], TIMEOUT * 1000
    except Exception:
        return [], 0
    finally:
        sock.close()

# ---------------- Main logic ----------------

def resolve_domains(host_name, domain_file):
    results = []
    total_time = 0
    success = 0
    fail = 0

    with open(domain_file, "r") as f:
        domains = [line.strip() for line in f if line.strip()]

    start_all = time.time()

    for domain in domains:
        ips, latency = query_custom_resolver(domain)
        status = "SUCCESS" if ips else "FAIL"
        if ips:
            success += 1
        else:
            fail += 1
        total_time += latency
        results.append((domain, status, ",".join(ips) or "-", round(latency, 2)))

    total_queries = len(domains)
    avg_latency = total_time / total_queries if total_queries else 0
    throughput = total_queries / (time.time() - start_all) if total_queries else 0

    # Save to CSV
    os.makedirs(RESULTS_DIR, exist_ok=True)
    csv_file = f"{RESULTS_DIR}/{host_name}_custom_results.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Domain", "Status", "Resolved_IPs", "Latency (ms)"])
        writer.writerows(results)

    print(f"\n--- {host_name} ---")
    print(f"Queries: {total_queries}")
    print(f"Success: {success}")
    print(f"Failed: {fail}")
    print(f"Average latency: {avg_latency:.2f} ms")
    print(f"Throughput: {throughput:.2f} qps")
    print(f"[✓] Results saved to {csv_file}")

# ---------------- Entry ----------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 resolve_custom.py <HostName>")
        sys.exit(1)

    host_name = sys.argv[1].upper()
    host_file = f"pcap/{host_name.lower()}_domains.txt"

    if not os.path.exists(host_file):
        print(f"[!] Domain file not found for {host_name}: {host_file}")
        sys.exit(1)

    resolve_domains(host_name, host_file)
