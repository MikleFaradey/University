#!/usr/bin/env python3
import argparse
import csv
import json
import math
import sys
from pathlib import Path


# The offline parser and the live model runtime use one shared extractor.
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from traffic_features import (  # noqa: E402
    FEATURE_COLUMNS, FIXED_WINDOW_SEC, add_packet, finalize_window,
    make_empty_window, packet_endpoints
)

DEFAULT_WINDOW_SEC = FIXED_WINDOW_SEC
_EPSILON = 1e-9

CSV_COLUMNS = [
    "experiment_id",
    "source_pcap",
    "window_index",
    "window_start_sec",
    "window_end_sec",
    "window_duration_sec",
    "phase_index",
    "label",
] + list(FEATURE_COLUMNS)


def load_scapy():
    try:
        from scapy.all import PcapReader, IP, IPv6, TCP, UDP, Raw
        return PcapReader, IP, IPv6, TCP, UDP, Raw
    except ImportError:
        raise SystemExit(
            "Scapy is required. Install it with: "
            "python3 -m pip install -r requirements.txt"
        )


def load_metadata(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    required = [
        "experiment_id",
        "target_client_ip",
        "timeline",
        "experiment_start_epoch",
    ]
    for name in required:
        if data.get(name) is None:
            raise ValueError("Metadata field is missing: %s" % name)

    if not data["timeline"]:
        raise ValueError("Metadata timeline is empty")

    return data


def _is_whole_second(value):
    try:
        number = float(value)
    except Exception:
        return False
    return abs(number - round(number)) <= _EPSILON


def validate_fixed_timeline(timeline):
    """Validate that every label boundary is aligned to the fixed 1 s grid."""
    previous_end = 0
    for index, phase in enumerate(timeline):
        try:
            start = float(phase["start_sec"])
            end = float(phase["end_sec"])
        except Exception:
            raise ValueError(
                "Timeline phase #%d has invalid start/end" % (index + 1)
            )

        if not _is_whole_second(start) or not _is_whole_second(end):
            raise ValueError(
                "Timeline phase #%d is not aligned to whole seconds; "
                "the project dataset window is fixed at 1 second"
                % (index + 1)
            )

        start = int(round(start))
        end = int(round(end))
        if start != previous_end:
            raise ValueError(
                "Timeline must be continuous: phase #%d must start at %d"
                % (index + 1, previous_end)
            )
        if end <= start:
            raise ValueError(
                "Timeline phase #%d end must be greater than start"
                % (index + 1)
            )
        previous_end = end

    if previous_end <= 0:
        raise ValueError("Timeline duration must be greater than zero")
    return previous_end


def resolve_fixed_window(metadata, requested_window=None):
    """Return the immutable project window and reject accidental overrides."""
    if requested_window is not None:
        try:
            requested = float(requested_window)
        except Exception:
            raise ValueError("Window size must be numeric")
        if abs(requested - FIXED_WINDOW_SEC) > _EPSILON:
            raise ValueError(
                "Interchange dataset window is fixed at 1 second; "
                "--window-sec may only be 1"
            )

    metadata_window = metadata.get("window_sec")
    if metadata_window is not None:
        try:
            metadata_window = float(metadata_window)
        except Exception:
            metadata_window = None
        if (metadata_window is not None and
                abs(metadata_window - FIXED_WINDOW_SEC) > _EPSILON):
            print(
                "WARNING: metadata declares window_sec=%s; this is a legacy "
                "value and is ignored. Interchange now always parses 1-second "
                "windows." % metadata_window,
                file=sys.stderr
            )

    return FIXED_WINDOW_SEC


def phase_for_window(timeline, start_sec, end_sec):
    for index, phase in enumerate(timeline):
        p_start = float(phase["start_sec"])
        p_end = float(phase["end_sec"])
        if start_sec >= p_start and end_sec <= p_end:
            return index, str(phase["label"])
    return -1, "MIXED"



def _dataset_duration(metadata, timeline_end):
    raw_duration = metadata.get(
        "dataset_duration_sec",
        metadata.get("total_duration_sec", timeline_end)
    )
    duration = float(raw_duration)
    if duration < 0:
        raise ValueError("Dataset duration cannot be negative")
    if not _is_whole_second(duration):
        raise ValueError(
            "Dataset duration must be aligned to whole seconds because the "
            "project window is fixed at 1 second"
        )
    duration = int(round(duration))
    if duration > int(timeline_end):
        raise ValueError("Dataset duration cannot exceed timeline duration")
    return duration


def parse_pair(pcap_path, metadata_path, window_sec=None):
    PcapReader, IP, IPv6, TCP, UDP, Raw = load_scapy()
    metadata = load_metadata(metadata_path)

    resolve_fixed_window(metadata, window_sec)
    timeline = metadata["timeline"]
    timeline_end = validate_fixed_timeline(timeline)

    if metadata.get("clock_source") != "server":
        print(
            "WARNING: legacy metadata does not declare server clock. "
            "If client and server clocks differed, windows may be empty.",
            file=sys.stderr
        )

    origin = float(metadata["experiment_start_epoch"])
    total_duration = _dataset_duration(metadata, timeline_end)
    client_ip = str(metadata["target_client_ip"])
    http_port = int(metadata.get("server_http_port", 8080))
    socket_port = int(metadata.get("server_socket_port", 8081))
    experiment_id = metadata["experiment_id"]

    if total_duration == 0:
        return []

    window_count = total_duration
    buckets = [make_empty_window() for _ in range(window_count)]
    previous_packet_ts = None

    reader = PcapReader(str(pcap_path))
    try:
        for pkt in reader:
            try:
                ts = float(pkt.time)
            except Exception:
                continue

            relative = ts - origin
            if relative < 0 or relative >= total_duration:
                continue

            index = int(math.floor(relative))
            if index < 0 or index >= window_count:
                continue

            src_ip, dst_ip, ip_version = packet_endpoints(pkt, IP, IPv6)
            if src_ip is None:
                continue

            interarrival = None
            if previous_packet_ts is not None:
                interarrival = ts - previous_packet_ts
                if interarrival < 0:
                    # Broken/out-of-order capture timestamp: do not poison metric.
                    interarrival = None

            accepted = add_packet(
                buckets[index],
                pkt,
                ts,
                client_ip,
                http_port,
                socket_port,
                IP, IPv6, TCP, UDP, Raw,
                interarrival=interarrival
            )
            if accepted:
                previous_packet_ts = ts
    finally:
        try:
            reader.close()
        except Exception:
            pass

    rows = []
    for index, bucket in enumerate(buckets):
        start_sec = float(index)
        end_sec = start_sec + FIXED_WINDOW_SEC
        phase_index, label = phase_for_window(
            timeline, start_sec, end_sec
        )
        if phase_index < 0:
            raise ValueError(
                "1-second window %.0f-%.0f is not fully covered by one "
                "timeline phase" % (start_sec, end_sec)
            )
        features = finalize_window(bucket)

        row = {
            "experiment_id": experiment_id,
            "source_pcap": Path(pcap_path).name,
            "window_index": index,
            "window_start_sec": start_sec,
            "window_end_sec": end_sec,
            "window_duration_sec": FIXED_WINDOW_SEC,
            "phase_index": phase_index,
            "label": label,
        }
        row.update(features)
        rows.append(row)

    return rows


def discover_pairs(input_dir):
    input_dir = Path(input_dir)
    pairs = []

    for pcap in sorted(input_dir.rglob("*.pcap")):
        metadata = pcap.with_suffix(".json")
        if metadata.exists():
            pairs.append((pcap, metadata))

    for pcap in sorted(input_dir.rglob("*.pcapng")):
        metadata = pcap.with_suffix(".json")
        if metadata.exists():
            pairs.append((pcap, metadata))

    return pairs


def write_csv(rows, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Convert Interchange PCAP + timeline metadata to fixed 1-second "
            "ML CSV windows"
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pcap", help="One PCAP/PCAPNG file")
    group.add_argument(
        "--input-dir",
        help="Directory with PCAP + JSON pairs"
    )
    parser.add_argument(
        "--metadata",
        help="Metadata JSON for --pcap. Default: same basename"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output dataset CSV"
    )
    parser.add_argument(
        "--window-sec",
        type=float,
        default=None,
        help=(
            "Compatibility option. The project window is fixed at 1 second; "
            "only --window-sec 1 is accepted."
        )
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if (args.window_sec is not None and
            abs(float(args.window_sec) - FIXED_WINDOW_SEC) > _EPSILON):
        raise SystemExit(
            "Interchange dataset window is fixed at 1 second; "
            "--window-sec may only be 1"
        )

    pairs = []
    if args.pcap:
        pcap = Path(args.pcap)
        metadata = (
            Path(args.metadata)
            if args.metadata
            else pcap.with_suffix(".json")
        )
        if not pcap.exists():
            raise SystemExit("PCAP not found: %s" % pcap)
        if not metadata.exists():
            raise SystemExit("Metadata not found: %s" % metadata)
        pairs = [(pcap, metadata)]
    else:
        pairs = discover_pairs(args.input_dir)
        if not pairs:
            raise SystemExit(
                "No PCAP + JSON pairs found in %s" % args.input_dir
            )

    all_rows = []
    parsed_experiments = 0
    for pcap, metadata in pairs:
        print("Parsing:", pcap)
        try:
            rows = parse_pair(
                pcap,
                metadata,
                window_sec=args.window_sec
            )
        except Exception as exc:
            if args.input_dir:
                print("Skipping invalid experiment:", pcap)
                print("Reason:", exc)
                continue
            raise
        all_rows.extend(rows)
        parsed_experiments += 1

    write_csv(all_rows, args.output)
    print("Experiments:", parsed_experiments)
    print("Windows:", len(all_rows))
    print("Window seconds:", int(FIXED_WINDOW_SEC))
    print("CSV:", Path(args.output).resolve())


if __name__ == "__main__":
    main()
