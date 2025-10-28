#!/usr/bin/env python3
import socket
import time
import csv
import os

CUSTOM_DNS_IP = "10.0.0.5"
CUSTOM_DNS_PORT = 53
RESULTS_DIR = "results"

def resolve_via_custom_resolver(host_name, domain_file):
    results = []
    total_time = 0
    success = 0
    fail = 0

    with open(domain_file, 'r') as f:
        domains = [line.strip() for line in f if line.strip()]

    start_all = time.time()

    for domain in domains:
        start = time.time()
        try:
            # Create UDP socket for DNS query
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(5)
            s.sendto(domain.encode(), (CUSTOM_DNS_IP, CUSTOM_DNS_PORT))
            data, _ = s.recvfrom(1024)
            latency = (time.time() - start) * 1000  # ms
            ip = data.decode(errors="ignore").strip()
            s.close()

            if ip and "FAIL" not in ip:
                results.append((domain, ip, "SUCCESS", round(latency, 2)))
                success += 1
            else:
                results.append((domain, "N/A", "FAIL", round(latency, 2)))
                fail += 1
        except Exception:
            latency = (time.time() - start) * 1000
            results.append((domain, "N/A", "FAIL", round(latency, 2)))
            fail += 1
        total_time += latency

    total_queries = len(domains)
    avg_latency = total_time / total_queries if total_queries else 0
    throughput = total_queries / (time.time() - start_all) if total_queries else 0

    # Write per-domain results
    os.makedirs(RESULTS_DIR, exist_ok=True)
    csv_file = f"{RESULTS_DIR}/{host_name}_custom_results.csv"
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Domain", "Resolved IP", "Status", "Latency (ms)"])
        writer.writerows(results)

    # Print summary
    print(f"\n--- {host_name} (Custom Resolver) ---")
    print(f"Queries: {total_queries}")
    print(f"Success: {success}")
    print(f"Failed: {fail}")
    print(f"Average latency: {avg_latency:.2f} ms")
    print(f"Throughput: {throughput:.2f} queries/sec")

    return {
        "host": host_name,
        "queries": total_queries,
        "success": success,
        "fail": fail,
        "avg_latency": avg_latency,
        "throughput": throughput
    }

if __name__ == "__main__":
    hosts = {
        "H1": "pcap/h1_domains.txt",
        "H2": "pcap/h2_domains.txt",
        "H3": "pcap/h3_domains.txt",
        "H4": "pcap/h4_domains.txt"
    }

    summary = []
    for host, domain_file in hosts.items():
        summary.append(resolve_via_custom_resolver(host, domain_file))

    # Write overall summary
    with open(f"{RESULTS_DIR}/custom_summary.csv", 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Host", "Total Queries", "Success", "Failed", "Avg Latency (ms)", "Throughput (qps)"])
        for row in summary:
            writer.writerow(row.values())

    print("\n[✓] All results saved in 'results/' directory.")
