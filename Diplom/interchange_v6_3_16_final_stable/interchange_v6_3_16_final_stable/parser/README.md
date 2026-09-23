# Interchange Dataset Parser

This folder is independent from `client/` and `server/`. It converts a PCAP/PCAPNG file plus its JSON metadata into a CSV dataset.

## Fixed project window

The dataset window is **exactly 1 second**. It is no longer a tunable parser parameter. Every row represents `[N, N + 1)` seconds relative to the server-owned experiment start time.

`--window-sec` is retained only for command-line compatibility. The only accepted value is `1`; any other value is rejected. Older metadata that contains `window_sec: 5` or another legacy value is parsed on the current 1-second grid with a warning.

## Install dependency

```bash
python3 -m pip install -r requirements.txt
```

## Parse one experiment

```bash
./run_parser.sh \
  --pcap /path/run_000001_user1_TIMELINE_20260907_120000.pcap \
  --output dataset.csv
```

The parser automatically uses the JSON file with the same basename.

## Parse a whole directory

```bash
./run_parser.sh \
  --input-dir /path/to/pcap_folder \
  --output dataset.csv
```

## Labeling and duration

The server metadata contains the server-owned experiment start epoch, client IP, complete timeline, baseline settings and Interchange ports. Timeline boundaries must be whole seconds, so every 1-second row belongs completely to one phase and receives one label.

For normal completed runs, the full planned timeline is parsed. For stopped/error/timeout runs, metadata exposes `dataset_duration_sec`, which contains only complete captured seconds. The trailing partial second is intentionally excluded because treating it as a full second would bias all count/rate metrics downward.

## Metric semantics for a 1-second row

- `packet_count`, `total_bytes`, direction counts, TCP/UDP counts, flag counts, HTTP/socket counts, small-packet counts, unique flows and new TCP connections are counts observed during that exact second. Numerically, count columns are also per-second event rates.
- `packets_per_sec == packet_count` and `bytes_per_sec == total_bytes`; these columns are retained for dataset compatibility.
- `small_packet_ratio` and direction ratios are calculated inside the same second.
- `avg_packet_size` and `std_packet_size` use packet sizes from the same second.
- `avg_interarrival` and `std_interarrival` aggregate gaps whose later packet lands in the current second. The preceding packet may be in the previous second, so sparse windows keep meaningful timing information.
- `new_tcp_connections` counts unique SYN-without-ACK flow tuples and does not count a retransmitted SYN as a second new connection.
- `window_duration_sec` is always `1.0`.

Empty seconds are retained as zero-filled rows, which preserves the timeline and makes neighboring experiments directly comparable.

Keep `experiment_id` when splitting datasets: train/test splits should be made by whole experiments rather than randomly mixing neighboring windows from the same run.

## Timing note

New metadata uses schema version 4 with `clock_source: server`. PCAP timestamps and the experiment origin therefore come from the same machine. Legacy metadata without a server clock can still be parsed, but the parser warns because unsynchronized client/server clocks may produce empty windows.
