# Dataset collection checklist (v6.3.16 final stable)

Use this checklist for the main Random Forest dataset series.

1. Keep the feature contract frozen: **1 second / 28 features**.
2. Use the built-in `Load example` scenario as `dataset_v1`:
   - 0-30 NORMAL
   - 30-50 FREQUENT_RECONNECT, `interval_sec=0.1`
   - 50-80 NORMAL
   - 80-110 HIGH_REQUEST_RATE, `requests_per_sec=30`
   - 110-140 NORMAL
   - 140-170 HIGH_FREQUENCY_SMALL_TRANSFERS,
     `transfers_per_sec=15`, `payload_bytes=32`
3. Do not change anomaly intensities inside the same dataset version.
4. Keep capture interface/backend and NIC offload settings consistent across runs.
5. Keep the original `.pcap` and matching metadata `.json` for every experiment.
6. Parse each completed run to CSV with the project parser; do not use stopped/error
   runs for the main training set unless intentionally studying them.
7. Prefer many independent runs over one long run. Target at least 20-30 complete
   experiments before treating model metrics as meaningful.
8. Train/test splitting must stay grouped by `experiment_id`; never randomly mix
   neighboring one-second windows from one experiment across train/test.
9. Keep a final holdout set of complete experiments that is not used for tuning.
10. Validate the trained `.joblib` first offline, then with Admin -> Model & traffic
    -> Model test using the same scenario.

Treat v6.3.16 as feature-frozen during this collection series. If a real bug forces
changes to traffic generation, parsing, feature formulas, or capture semantics,
start a new dataset version instead of silently mixing old and new runs.
