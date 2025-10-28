#!/usr/bin/env python3
"""
Performs full iterative resolution (Root → TLD → Authoritative)
and logs detailed stepwise metrics for every query.

Logging fields:
a. Timestamp
b. Domain name
c. Resolution mode
d. DNS server IP contacted
e. Step (Root / TLD / Authoritative)
f. Response type (Answer / Referral / NXDOMAIN / NoResponse)
g. Round-trip time (ms)
h. Total time to resolution (ms)
i. Cache status (N/A since caching disabled)

Run:
    sudo python iterative_dns_resolver_logged_nocache.py
"""

import socket, struct, time, csv, random

SERVER_IP, SERVER_PORT = "10.0.0.5", 53
BUFFER_SIZE = 512

# CSV logs
SUMMARY_FILE = "resolver_summary.csv"
STEP_FILE    = "resolver_detailed_steps.csv"

# Root servers (IPv4)
ROOT_SERVERS = [
    "198.41.0.4", "170.247.170.2", "192.33.4.12", "199.7.91.13",
    "192.203.230.10", "192.5.5.241", "192.112.36.4", "198.97.190.53",
    "192.36.148.17", "192.58.128.30", "193.0.14.129", "199.7.83.42",
    "202.12.27.33"
]

# ---------------------------------------------------------------------
# DNS helpers
# ---------------------------------------------------------------------
def encode_domain(name):
    parts = name.strip(".").split(".")
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
        labels.append(data[offset+1:offset+1+length].decode())
        offset += 1 + length
    return ".".join(labels), offset

def parse_question(data, offset):
    qname, offset = decode_domain(data, offset)
    qtype, qclass = struct.unpack_from("!HH", data, offset)
    return qname, qtype, qclass, offset + 4

def build_query(domain, qtype=1, qclass=1):
    qid = random.randint(0, 0xFFFF)
    header = struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    question = encode_domain(domain) + struct.pack("!HH", qtype, qclass)
    return header + question

def send_query(server_ip, data):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    start = time.time()
    try:
        s.sendto(data, (server_ip, 53))
        resp, _ = s.recvfrom(BUFFER_SIZE)
        return resp, (time.time() - start) * 1000
    except Exception:
        return None, None
    finally:
        s.close()

def parse_response(data):
    if not data or len(data) < 12:
        return [], [], []
    _, _, qd, an, ns, ar = struct.unpack_from("!HHHHHH", data, 0)
    offset = 12
    for _ in range(qd):
        _, _, _, offset = parse_question(data, offset)
    sections = {"ans": [], "auth": [], "add": []}
    for sec, count in zip(sections, [an, ns, ar]):
        for _ in range(count):
            name, offset = decode_domain(data, offset)
            rtype, rclass, ttl, rdlen = struct.unpack_from("!HHIH", data, offset)
            offset += 10
            rdata = data[offset:offset+rdlen]
            offset += rdlen
            if rtype == 1 and len(rdata) == 4:
                val = ".".join(map(str, rdata))
            elif rtype == 2:
                val, _ = decode_domain(data, offset - rdlen)
            else:
                val = rdata
            sections[sec].append((name, rtype, val))
    return sections["ans"], sections["auth"], sections["add"]

# ---------------------------------------------------------------------
# Iterative resolver (no cache)
# ---------------------------------------------------------------------
def iterative_resolve(domain):
    steps, start_total = [], time.time()
    servers, visited = ROOT_SERVERS[:], set()

    while servers:
        srv = servers.pop(0)
        if srv in visited:
            continue
        visited.add(srv)

        # Determine hierarchy level
        if srv in ROOT_SERVERS:
            stage = "ROOT"
        else:
            stage = "TLD/AUTHORITATIVE"

        query = build_query(domain)
        resp, rtt = send_query(srv, query)
        rtt_ms = f"{rtt:.2f}" if rtt else "timeout"

        ans, auth, add = parse_response(resp)
        response_type = "REFERRAL"
        if any(r[1] == 1 for r in ans):
            response_type = "ANSWER"
        elif not resp:
            response_type = "NO_RESPONSE"

        steps.append((domain, "iterative", srv, stage, response_type, rtt_ms, "-", "N/A"))

        # Case 1: final A record
        if any(r[1] == 1 for r in ans):
            ip = next(r[2] for r in ans if r[1] == 1)
            total_ms = (time.time() - start_total) * 1000
            steps[-1] = steps[-1][:-2] + (f"{total_ms:.2f}", "N/A")
            return ip, total_ms, steps

        # Case 2: referrals / glue
        glue = [r[2] for r in add if r[1] == 1]
        if glue:
            servers = glue + servers
            continue
        ns_names = [r[2] for r in auth if r[1] == 2]
        for ns in ns_names:
            ip, _, _ = iterative_resolve(ns)
            if ip:
                servers.insert(0, ip)
                break

    return None, (time.time() - start_total) * 1000, steps

# ---------------------------------------------------------------------
# UDP server main loop
# ---------------------------------------------------------------------
def start_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((SERVER_IP, SERVER_PORT))
    print(f"[+] Iterative resolver (no cache) listening on {SERVER_IP}:{SERVER_PORT}")

    # Initialize CSV headers
    with open(SUMMARY_FILE, "w", newline="") as f:
        csv.writer(f).writerow(["timestamp","client","domain","result_ip","total_time_ms"])
    with open(STEP_FILE, "w", newline="") as f:
        csv.writer(f).writerow([
            "timestamp","domain","resolution_mode","dns_server_ip",
            "step","response_type","rtt_ms","total_time_ms","cache_status"
        ])

    while True:
        data, addr = sock.recvfrom(BUFFER_SIZE)
        client = addr[0]
        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        try:
            qname, _, _, _ = parse_question(data, 12)
        except Exception:
            continue

        print(f"[Query] {client} asked for {qname}")
        ip, total_ms, steps = iterative_resolve(qname)

        # Construct reply
        if ip:
            tid = data[:2]
            flags = b"\x81\x80"
            counts = struct.pack("!HHHH", 1, 1, 0, 0)
            question = data[12:]
            ans = encode_domain(qname)+struct.pack("!HHI",1,1,60)+struct.pack("!H",4)+bytes(map(int,ip.split(".")))
            reply = tid+flags+counts+question+ans
        else:
            reply = data[:2]+b"\x81\x83"+data[4:]

        sock.sendto(reply, addr)

        # Log results
        with open(SUMMARY_FILE, "a", newline="") as f:
            csv.writer(f).writerow([ts, client, qname, ip or "FAIL", f"{total_ms:.2f}"])
        with open(STEP_FILE, "a", newline="") as f:
            w = csv.writer(f)
            for s in steps:
                w.writerow([ts] + list(s))

        print(f"[Done] {qname} -> {ip or 'FAIL'} ({total_ms:.2f} ms)\n")

# ---------------------------------------------------------------------
if __name__ == "__main__":
    start_server()
