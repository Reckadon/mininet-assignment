#!/usr/bin/env python3
"""
Iterative DNS Resolver (from scratch, no external libraries)
-------------------------------------------------------------
• Listens on UDP port 53 and accepts real DNS queries (RFC 1035 format).
• Parses query header and question manually.
• Performs iterative resolution using root -> TLD -> authoritative chain.
• Logs step-wise RTTs and total latency to CSV files.

Run:
    sudo python3 iterative_dns_resolver_raw.py
"""

import socket, struct, time, csv

SERVER_IP   = "10.0.0.5"
SERVER_PORT = 53
BUFFER_SIZE = 512

LOG_FILE  = "resolver_summary.csv"
STEP_FILE = "resolver_steps.csv"

# Root server list (IPv4)
ROOT_SERVERS = [
    "198.41.0.4", "170.247.170.2", "192.33.4.12", "199.7.91.13", "192.203.230.10", "192.5.5.241", "192.112.36.4", "198.97.190.53", "192.36.148.17", "192.58.128.30", "193.0.14.129", "199.7.83.42", "202.12.27.33"
]

# -------------------------------------------------------------------
# DNS packet helpers
# -------------------------------------------------------------------
def encode_domain(name: str) -> bytes:
    parts = name.strip(".").split(".")
    return b"".join([bytes([len(p)]) + p.encode() for p in parts]) + b"\x00"

def decode_domain(data, offset):
    labels = []
    while True:
        length = data[offset]
        if length == 0:
            offset += 1
            break
        # handle compression
        if (length & 0xC0) == 0xC0:
            ptr = struct.unpack_from("!H", data, offset)[0] & 0x3FFF
            subdomain, _ = decode_domain(data, ptr)
            labels.append(subdomain)
            offset += 2
            break
        labels.append(data[offset+1:offset+1+length].decode())
        offset += 1 + length
    return ".".join(labels), offset

def parse_question(data, offset):
    qname, offset = decode_domain(data, offset)
    qtype, qclass = struct.unpack_from("!HH", data, offset)
    offset += 4
    return qname, qtype, qclass, offset

def build_query(domain, qtype=1, qclass=1, qid=None):
    if qid is None:
        qid = int(time.time()*1000) & 0xFFFF
    header = struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    question = encode_domain(domain) + struct.pack("!HH", qtype, qclass)
    return header + question, qid

# -------------------------------------------------------------------
# Send query and get response
# -------------------------------------------------------------------
def send_query(server_ip, query_data):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    start = time.time()
    try:
        s.sendto(query_data, (server_ip, 53))
        data, _ = s.recvfrom(BUFFER_SIZE)
        rtt = (time.time() - start) * 1000
        return data, rtt
    except Exception:
        return None, None
    finally:
        s.close()

# -------------------------------------------------------------------
# Parse response, extract answers / referrals
# -------------------------------------------------------------------
def parse_response(data):
    if not data or len(data) < 12:
        return [], [], []
    (tid, flags, qd, an, ns, ar) = struct.unpack_from("!HHHHHH", data, 0)
    offset = 12
    # skip questions
    for _ in range(qd):
        _, _, _, offset = parse_question(data, offset)

    answers, authorities, additionals = [], [], []
    for section, count in [("ans", an), ("auth", ns), ("add", ar)]:
        for _ in range(count):
            name, offset = decode_domain(data, offset)
            rtype, rclass, ttl, rdlen = struct.unpack_from("!HHIH", data, offset)
            offset += 10
            rdata = data[offset:offset+rdlen]
            offset += rdlen
            if rtype == 1 and len(rdata) == 4:  # A record
                ip = ".".join(map(str, rdata))
                rec = (name, rtype, ip)
            elif rtype == 2:  # NS record
                ns, _ = decode_domain(data, offset-rdlen)
                rec = (name, rtype, ns)
            else:
                rec = (name, rtype, rdata)
            if section == "ans":
                answers.append(rec)
            elif section == "auth":
                authorities.append(rec)
            else:
                additionals.append(rec)
    return answers, authorities, additionals

# -------------------------------------------------------------------
# Iterative resolver core
# -------------------------------------------------------------------
def iterative_resolve(domain):
    steps = []
    total_start = time.time()
    servers = ROOT_SERVERS[:]
    visited = set()

    while servers:
        server = servers.pop(0)
        if server in visited: continue
        visited.add(server)

        query, qid = build_query(domain)
        resp, rtt = send_query(server, query)
        steps.append((domain, server, f"{rtt:.2f}" if rtt else "timeout"))

        if not resp:
            continue

        answers, auth, add = parse_response(resp)

        # Case 1: got final A record
        if any(r[1] == 1 for r in answers):
            ip = next((r[2] for r in answers if r[1] == 1), None)
            total_time = (time.time() - total_start) * 1000
            return ip, total_time, steps

        # Case 2: got referrals (NS records)
        glue_ips = [r[2] for r in add if r[1] == 1]
        if glue_ips:
            servers = glue_ips + servers
            continue

        # Case 3: no glue, extract NS names and resolve them
        ns_names = [r[2] for r in auth if r[1] == 2]
        if ns_names:
            ns_ip = None
            for ns in ns_names:
                ip, _, _ = iterative_resolve(ns)
                if ip:
                    ns_ip = ip
                    break
            if ns_ip:
                servers.insert(0, ns_ip)
                continue
        # else try next root
    total_time = (time.time() - total_start) * 1000
    return None, total_time, steps

# -------------------------------------------------------------------
# UDP server main loop
# -------------------------------------------------------------------
def start_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((SERVER_IP, SERVER_PORT))
    print(f"[+] Iterative DNS Resolver listening on {SERVER_IP}:{SERVER_PORT}")

    # CSV headers
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerow(["timestamp","client","domain","result_ip","total_time_ms"])
    with open(STEP_FILE, "w", newline="") as f:
        csv.writer(f).writerow(["timestamp","domain","server_contacted","rtt_ms"])

    while True:
        data, addr = sock.recvfrom(BUFFER_SIZE)
        client = addr[0]

        # Parse query domain
        try:
            _, _, qd, _, _, _ = struct.unpack_from("!HHHHHH", data, 0)
            offset = 12
            qname, _, _, _ = parse_question(data, offset)
        except Exception:
            continue

        print(f"[Query] {client} asked for {qname}")

        ip, total_time, steps = iterative_resolve(qname)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        # Build simple DNS reply
        reply = b""
        if ip:
            tid = data[:2]
            flags = b"\x81\x80"  # standard response, no error
            counts = struct.pack("!HHHH", 1, 1, 0, 0)
            header = tid + flags + counts
            question = data[12:len(data)]
            answer = encode_domain(qname) + struct.pack("!HHI", 1, 1, 60)
            answer += struct.pack("!H", 4)
            answer += bytes(map(int, ip.split(".")))
            reply = header + question + answer
        else:
            reply = data[:2] + b"\x81\x83" + data[4:]  # NXDOMAIN

        sock.sendto(reply, addr)

        # Log
        with open(LOG_FILE, "a", newline="") as f:
            csv.writer(f).writerow([ts, client, qname, ip or "FAIL", f"{total_time:.2f}"])
        with open(STEP_FILE, "a", newline="") as f:
            w = csv.writer(f)
            for s in steps:
                w.writerow([ts] + list(s))

        print(f"[Done] {qname} -> {ip or 'FAIL'} ({total_time:.2f} ms)\n")

# -------------------------------------------------------------------
if __name__ == "__main__":
    start_server()
