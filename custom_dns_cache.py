"""
Iterative DNS Resolver — Multi-Level Caching + Metrics
------------------------------------------------------

Logs:
a. Timestamp
b. Domain name
c. Resolution mode
d. DNS server IP contacted
e. Step (Root / TLD / Authoritative / Cache)
f. Response type
g. RTT (ms)
h. Total time (ms)
i. Cache status (HIT / MISS)
"""

import socket, struct, time, csv, random

SERVER_IP, SERVER_PORT = "10.0.0.5", 53
BUFFER_SIZE = 512

SUMMARY_FILE = "resolver_summary.csv"
STEP_FILE = "resolver_detailed_steps.csv"
METRICS_FILE = "resolver_metrics.csv"

ROOT_SERVERS = [
    "198.41.0.4", "170.247.170.2", "192.33.4.12", "199.7.91.13",
    "192.203.230.10", "192.5.5.241", "192.112.36.4", "198.97.190.53",
    "192.36.148.17", "192.58.128.30", "193.0.14.129", "199.7.83.42",
    "202.12.27.33"
]

# ---------------- Multi-level Cache ----------------
CACHE_TTL = 300  # seconds
CACHE = {
    "A": {},   # domain → IP
    "NS": {},  # domain → list of NS names
    "GLUE": {} # ns_name → IP
}

STATS = {
    "total_queries": 0,
    "success": 0,
    "fail": 0,
    "cache_hits": 0,
    "total_latency": 0.0,
    "start_time": time.time()
}

# ---------------- DNS helpers ----------------
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
    tid = random.randint(0, 0xFFFF)
    header = struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    question = encode_domain(domain) + struct.pack("!HH", qtype, qclass)
    return header + question

def send_query(server_ip, data):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    start = time.time()
    try:
        s.sendto(data, (server_ip, 53))
        resp, _ = s.recvfrom(BUFFER_SIZE)
        rtt = (time.time() - start) * 1000
        return resp, rtt
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
    answers, auth, add = [], [], []
    for section, count in zip(["ans", "auth", "add"], [an, ns, ar]):
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
            if section == "ans": answers.append((name, rtype, val))
            elif section == "auth": auth.append((name, rtype, val))
            else: add.append((name, rtype, val))
    return answers, auth, add

# ---------------- Cache helpers ----------------
def cache_get(level, key):
    if key not in CACHE[level]: return None
    val, ts = CACHE[level][key]
    if time.time() - ts > CACHE_TTL:
        del CACHE[level][key]
        return None
    return val

def cache_put(level, key, value):
    CACHE[level][key] = (value, time.time())

# ---------------- Iterative Resolver ----------------
def iterative_resolve(domain):
    steps = []
    start_total = time.time()

    # Check A record cache
    cached_ip = cache_get("A", domain)
    if cached_ip:
        total_ms = (time.time() - start_total) * 1000
        steps.append((domain, "cached", "cache", "CACHE", "ANSWER", "0.00", f"{total_ms:.2f}", "HIT"))
        return cached_ip, total_ms, steps, True

    servers = ROOT_SERVERS[:]
    visited = set()
    cache_status = "MISS"

    while servers:
        srv = servers.pop(0)
        if srv in visited:
            continue
        visited.add(srv)

        stage = "ROOT" if srv in ROOT_SERVERS else "TLD/AUTH"
        query = build_query(domain)
        resp, rtt = send_query(srv, query)
        rtt_ms = f"{rtt:.2f}" if rtt else "timeout"

        ans, auth, add = parse_response(resp)
        response_type = "REFERRAL"
        if any(r[1] == 1 for r in ans):
            response_type = "ANSWER"
        elif not resp:
            response_type = "NO_RESPONSE"

        steps.append((domain, "iterative", srv, stage, response_type, rtt_ms, "-", cache_status))

        # Case 1: Got final A record
        if any(r[1] == 1 for r in ans):
            ip = next(r[2] for r in ans if r[1] == 1)
            total_ms = (time.time() - start_total) * 1000
            steps[-1] = (domain, "iterative", srv, stage, response_type, rtt_ms, f"{total_ms:.2f}", cache_status)
            cache_put("A", domain, ip)
            return ip, total_ms, steps, False

        # Case 2: Referral or glue (cache them)
        glue_ips = [r[2] for r in add if r[1] == 1]
        if glue_ips:
            for ip in glue_ips:
                cache_put("GLUE", srv, ip)
            servers = glue_ips + servers
            continue

        ns_names = [r[2] for r in auth if r[1] == 2]
        if ns_names:
            cache_put("NS", domain, ns_names)
            for ns in ns_names:
                ns_ip = cache_get("GLUE", ns)
                if not ns_ip:
                    ns_ip, _, _, _ = iterative_resolve(ns)
                if ns_ip:
                    servers.insert(0, ns_ip)
                    break

    total_ms = (time.time() - start_total) * 1000
    return None, total_ms, steps, False

# ---------------- Metrics ----------------
def update_metrics(success, total_time, cache_hit):
    STATS["total_queries"] += 1
    if success:
        STATS["success"] += 1
        STATS["total_latency"] += total_time
    else:
        STATS["fail"] += 1
    if cache_hit:
        STATS["cache_hits"] += 1

    avg_latency = STATS["total_latency"]/STATS["success"] if STATS["success"] else 0
    elapsed = time.time() - STATS["start_time"]
    throughput = STATS["total_queries"]/elapsed if elapsed else 0
    cache_pct = (STATS["cache_hits"]/STATS["total_queries"])*100 if STATS["total_queries"] else 0

    with open(METRICS_FILE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Total Queries","Success","Failed","Avg Latency (ms)","Throughput (qps)","% Cache Resolved"])
        w.writerow([STATS["total_queries"],STATS["success"],STATS["fail"],
                    f"{avg_latency:.2f}",f"{throughput:.2f}",f"{cache_pct:.2f}"])

# ---------------- Server ----------------
def start_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((SERVER_IP, SERVER_PORT))
    print(f"[+] Multi-level Cached Resolver running on {SERVER_IP}:{SERVER_PORT}")

    for fpath, header in [
        (SUMMARY_FILE, ["timestamp","client","domain","result_ip","total_time_ms"]),
        (STEP_FILE, ["timestamp","domain","resolution_mode","dns_server_ip","step","response_type","rtt_ms","total_time_ms","cache_status"]),
        (METRICS_FILE, ["Total Queries","Success","Failed","Avg Latency (ms)","Throughput (qps)","% Cache Resolved"])
    ]:
        with open(fpath, "w", newline="") as f:
            csv.writer(f).writerow(header)

    while True:
        data, addr = sock.recvfrom(BUFFER_SIZE)
        client = addr[0]
        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        try:
            qname, _, _, _ = parse_question(data, 12)
        except Exception:
            continue

        print(f"[Query] {client} asked for {qname}")
        ip, total_ms, steps, cache_hit = iterative_resolve(qname)

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

        with open(SUMMARY_FILE, "a", newline="") as f:
            csv.writer(f).writerow([ts, client, qname, ip or "FAIL", f"{total_ms:.2f}"])
        with open(STEP_FILE, "a", newline="") as f:
            w = csv.writer(f)
            for s in steps:
                w.writerow([ts] + list(s))

        update_metrics(ip is not None, total_ms, cache_hit)
        print(f"[Done] {qname} -> {ip or 'FAIL'} ({total_ms:.2f} ms)\n")

if __name__ == "__main__":
    start_server()
