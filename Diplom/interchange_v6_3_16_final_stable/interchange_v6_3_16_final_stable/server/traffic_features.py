"""Shared 1-second traffic feature extraction for offline and live inference.

This module is the single source of truth for the metrics presented to ML.
The project invariant is one-second windows.  Both parser/pcap_to_csv.py and
server/live_monitor.py use these exact functions.
"""
import statistics


FIXED_WINDOW_SEC = 1.0
_EPSILON = 1e-9

# Canonical model feature order.  Do not reorder without intentionally changing
# the dataset/model schema.
FEATURE_COLUMNS = [
    "packet_count",
    "total_bytes",
    "client_to_server_packets",
    "server_to_client_packets",
    "client_to_server_bytes",
    "server_to_client_bytes",
    "tcp_packets",
    "udp_packets",
    "syn_count",
    "syn_ack_count",
    "fin_count",
    "rst_count",
    "psh_count",
    "new_tcp_connections",
    "unique_flows",
    "http_packets",
    "socket_packets",
    "http_client_payload_packets",
    "small_packet_count",
    "small_packet_ratio",
    "avg_packet_size",
    "std_packet_size",
    "avg_interarrival",
    "std_interarrival",
    "packets_per_sec",
    "bytes_per_sec",
    "client_to_server_packet_ratio",
    "client_to_server_byte_ratio",
]

# A model trained after dropping only identifiers/labels may also contain the
# constant one-second duration column.  The runtime supports that explicitly.
MODEL_AVAILABLE_FEATURES = ["window_duration_sec"] + FEATURE_COLUMNS


def safe_mean(values):
    return statistics.mean(values) if values else 0.0


def safe_pstdev(values):
    return statistics.pstdev(values) if len(values) >= 2 else 0.0


def make_empty_window():
    return {
        "packet_count": 0,
        "total_bytes": 0,
        "client_to_server_packets": 0,
        "server_to_client_packets": 0,
        "client_to_server_bytes": 0,
        "server_to_client_bytes": 0,
        "tcp_packets": 0,
        "udp_packets": 0,
        "syn_count": 0,
        "syn_ack_count": 0,
        "fin_count": 0,
        "rst_count": 0,
        "psh_count": 0,
        "http_packets": 0,
        "socket_packets": 0,
        "http_client_payload_packets": 0,
        "small_packet_count": 0,
        "packet_sizes": [],
        "interarrivals": [],
        "flows": set(),
        "new_tcp_flows": set(),
    }


def finalize_window(bucket, window_sec=FIXED_WINDOW_SEC):
    """Return ML metrics for one complete one-second traffic bucket."""
    if abs(float(window_sec) - FIXED_WINDOW_SEC) > _EPSILON:
        raise ValueError("Interchange metrics are defined only for 1-second windows")

    packet_count = bucket["packet_count"]
    total_bytes = bucket["total_bytes"]
    sizes = bucket["packet_sizes"]
    interarrival = bucket["interarrivals"]
    c2s_packets = bucket["client_to_server_packets"]
    c2s_bytes = bucket["client_to_server_bytes"]

    return {
        "packet_count": packet_count,
        "total_bytes": total_bytes,
        "client_to_server_packets": c2s_packets,
        "server_to_client_packets": bucket["server_to_client_packets"],
        "client_to_server_bytes": c2s_bytes,
        "server_to_client_bytes": bucket["server_to_client_bytes"],
        "tcp_packets": bucket["tcp_packets"],
        "udp_packets": bucket["udp_packets"],
        "syn_count": bucket["syn_count"],
        "syn_ack_count": bucket["syn_ack_count"],
        "fin_count": bucket["fin_count"],
        "rst_count": bucket["rst_count"],
        "psh_count": bucket["psh_count"],
        "new_tcp_connections": len(bucket["new_tcp_flows"]),
        "unique_flows": len(bucket["flows"]),
        "http_packets": bucket["http_packets"],
        "socket_packets": bucket["socket_packets"],
        "http_client_payload_packets": bucket["http_client_payload_packets"],
        "small_packet_count": bucket["small_packet_count"],
        "small_packet_ratio": (
            float(bucket["small_packet_count"]) / packet_count
            if packet_count else 0.0
        ),
        "avg_packet_size": safe_mean(sizes),
        "std_packet_size": safe_pstdev(sizes),
        "avg_interarrival": safe_mean(interarrival),
        "std_interarrival": safe_pstdev(interarrival),
        # A completed row is exactly one second, therefore these rate columns
        # intentionally equal the one-second counters.
        "packets_per_sec": float(packet_count),
        "bytes_per_sec": float(total_bytes),
        "client_to_server_packet_ratio": (
            float(c2s_packets) / packet_count if packet_count else 0.0
        ),
        "client_to_server_byte_ratio": (
            float(c2s_bytes) / total_bytes if total_bytes else 0.0
        ),
    }


def packet_endpoints(pkt, IP, IPv6):
    if IP in pkt:
        return pkt[IP].src, pkt[IP].dst, 4
    if IPv6 in pkt:
        return pkt[IPv6].src, pkt[IPv6].dst, 6
    return None, None, None


def add_packet(bucket, pkt, ts, client_ip, http_port, socket_port,
               IP, IPv6, TCP, UDP, Raw, interarrival=None):
    """Add one captured packet to a client's one-second bucket.

    The same routine is used for historical PCAP parsing and live monitoring.
    Returns True for an accepted IP packet.
    """
    src_ip, dst_ip, ip_version = packet_endpoints(pkt, IP, IPv6)
    if src_ip is None:
        return False

    size = len(bytes(pkt))
    bucket["packet_count"] += 1
    bucket["total_bytes"] += size
    bucket["packet_sizes"].append(size)
    if interarrival is not None and interarrival >= 0:
        bucket["interarrivals"].append(float(interarrival))

    if size <= 256:
        bucket["small_packet_count"] += 1

    if src_ip == client_ip:
        bucket["client_to_server_packets"] += 1
        bucket["client_to_server_bytes"] += size
    elif dst_ip == client_ip:
        bucket["server_to_client_packets"] += 1
        bucket["server_to_client_bytes"] += size

    if TCP in pkt:
        tcp = pkt[TCP]
        bucket["tcp_packets"] += 1

        flags = int(tcp.flags)
        syn = bool(flags & 0x02)
        ack = bool(flags & 0x10)
        fin = bool(flags & 0x01)
        rst = bool(flags & 0x04)
        psh = bool(flags & 0x08)

        if syn:
            bucket["syn_count"] += 1
        if syn and ack:
            bucket["syn_ack_count"] += 1
        if fin:
            bucket["fin_count"] += 1
        if rst:
            bucket["rst_count"] += 1
        if psh:
            bucket["psh_count"] += 1

        sport = int(tcp.sport)
        dport = int(tcp.dport)
        flow = (src_ip, sport, dst_ip, dport, "TCP")
        bucket["flows"].add(flow)
        if syn and not ack:
            # Retransmitted SYNs retain the same initial sequence number.
            try:
                syn_sequence = int(tcp.seq)
            except Exception:
                syn_sequence = None
            bucket["new_tcp_flows"].add(flow + (syn_sequence,))

        if sport == int(http_port) or dport == int(http_port):
            bucket["http_packets"] += 1
        if sport == int(socket_port) or dport == int(socket_port):
            bucket["socket_packets"] += 1

        if (src_ip == client_ip and dport == int(http_port) and
                Raw in pkt and len(bytes(pkt[Raw])) > 0):
            bucket["http_client_payload_packets"] += 1

    elif UDP in pkt:
        udp = pkt[UDP]
        bucket["udp_packets"] += 1
        bucket["flows"].add(
            (src_ip, int(udp.sport), dst_ip, int(udp.dport), "UDP")
        )

    return True


def feature_values(metrics, feature_names):
    """Build a model row in the requested feature order."""
    values = []
    for name in feature_names:
        if name == "window_duration_sec":
            values.append(FIXED_WINDOW_SEC)
        elif name in metrics:
            values.append(metrics[name])
        else:
            raise KeyError("Unknown model feature: %s" % name)
    return values
