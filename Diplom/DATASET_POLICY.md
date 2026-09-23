# Interchange dataset policy

## Fixed sampling window

The project dataset window is **exactly 1 second**. This is a project invariant, not a parser preference. Do not change it without an explicit project-level decision.

Rules:

- one CSV row represents `[N, N + 1)` seconds from the server-owned experiment origin;
- timeline boundaries are whole seconds and continuous;
- new experiment metadata stores `window_sec: 1`;
- the parser rejects a CLI window override other than `1`;
- legacy metadata that declares another window size is re-parsed on the current 1-second grid;
- stopped/error runs contribute only complete seconds through `dataset_duration_sec`;
- `window_duration_sec` is written to every CSV row and is always `1.0`.

## Metric semantics

All metrics are computed per 1-second row. Count columns therefore also represent event counts per second. `packets_per_sec` and `bytes_per_sec` remain in the CSV for compatibility and are exact numeric aliases of `packet_count` and `total_bytes`.

`avg_interarrival` and `std_interarrival` aggregate packet-to-packet gaps assigned to the second in which the later packet arrived. The previous packet may be in the preceding second, which avoids artificial zeros for sparse one-packet windows.

`new_tcp_connections` counts unique TCP SYN-without-ACK flow tuples in the second. Retransmitted SYN packets still increase `syn_count`, but they do not inflate `new_tcp_connections`.

Ratios and packet-size statistics are calculated only from packets belonging to that one-second row. Empty windows are retained and contain zeros.


## Live inference invariant

The same one-second feature implementation is now used by both offline dataset
creation and live model inference. `server/traffic_features.py` is the source of
truth. Live inference does not write/read CSV between packet capture and the
model. A live prediction is produced only for a complete observed one-second
window; a partial first second after capture startup/restart is discarded.

## Dataset v1 scenario freeze

For the main dataset collection series, the built-in training example is the
canonical `dataset_v1` scenario. Keep these anomaly intensities unchanged
between independent runs unless a new dataset version is intentionally created:

```text
0-30    NORMAL
30-50   FREQUENT_RECONNECT              interval_sec=0.1
50-80   NORMAL
80-110  HIGH_REQUEST_RATE               requests_per_sec=30
110-140 NORMAL
140-170 HIGH_FREQUENCY_SMALL_TRANSFERS  transfers_per_sec=15, payload_bytes=32
```

The normal baseline continues through every phase. Independent runs should vary
normal baseline content naturally (message text and selected files/folders),
but the anomaly parameters above form the v1 class definition.

Capture conditions must remain consistent within a dataset version. Record and
retain the original PCAP + JSON metadata for every run. The metadata already
contains the capture backend/interface and exact timeline. On Linux, keep the
chosen capture interface and NIC offload configuration stable while collecting
a training series; changing TSO/GSO/GRO/LRO behavior mid-series can change
packet-count and packet-size distributions even when application behavior is
unchanged.
