"""
resolve_default.py
-------------------
Runs inside a Mininet host (e.g. h1) to test default DNS resolution.
Reads a host-specific domain list (e.g. pcap/h1_domains.txt),
resolves each using the system resolver, measures latency,
and writes results to results/H1_default_results.csv.

Usage:
    python resolve_default.py H1
"""

import socket
import time
import csv
import os
import sys


def resolve_domains(host_name, domain_file):
    results = []
    total_time = 0
    success = 0
    fail = 0

    # Read domain list
    with open(domain_file, "r") as f:
        domains = [line.strip() for line in f if line.strip()]

    start_all = time.time()

    for domain in domains:
        start = time.time()
        try:
            socket.gethostbyname(domain)
            latency = (time.time() - start) * 1000  # ms
            results.append((domain, "SUCCESS", round(latency, 2)))
            success += 1
        except Exception as e:
            latency = (time.time() - start) * 1000
            results.append((domain, f"FAIL - {str(e)}", round(latency, 2)))
            fail += 1
        total_time += latency

    total_queries = len(domains)
    avg_latency = total_time / total_queries if total_queries else 0
    throughput = total_queries / (time.time() - start_all) if total_queries else 0

    # Ensure results directory exists
    os.makedirs("results", exist_ok=True)
    csv_file = f"results/{host_name}_default_results.csv"

    # Write results
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Domain", "Status", "Latency (ms)"])
        writer.writerows(results)

    print(f"\n--- {host_name} ---")
    print(f"Queries: {total_queries}")
    print(f"Success: {success}")
    print(f"Failed: {fail}")
    print(f"Average latency: {avg_latency:.2f} ms")
    print(f"Throughput: {throughput:.2f} qps")
    print(f"[✓] Results saved to {csv_file}")


if __name__ == "__main__":
    # --- Parse command-line argument ---
    if len(sys.argv) < 2:
        print("Usage: python3 resolve_default.py <HostName>")
        print("Example: python3 resolve_default.py H1")
        sys.exit(1)

    host_name = sys.argv[1].upper()
    host_file = f"pcap/{host_name.lower()}_domains.txt"

    if not os.path.exists(host_file):
        print(f"[!] Domain file not found for {host_name}: {host_file}")
        sys.exit(1)

    resolve_domains(host_name, host_file)
