# Live model monitor

Interchange v6.3.16 retains a live inference path to the server. CSV is **not** part
of runtime inference.

```text
client network traffic
        |
        v
 tcpdump / dumpcap
        |
        v
 Scapy packet stream
        |
        v
1-second in-memory bucket
        |
        v
traffic_features.py
        |
        v
Random Forest / sklearn model
        |
        +--> predicted class (NORMAL or anomaly type)
        +--> predict_proba confidence
        |
        v
Admin -> Model & traffic
```

## Fixed schema

The live path and `parser/pcap_to_csv.py` import the same functions from
`server/traffic_features.py`. This prevents the training dataset and runtime
model input from drifting apart.

The canonical model vector contains 28 traffic metrics. A model with 29
features is also accepted when the extra feature is the constant
`window_duration_sec = 1.0`.

If the estimator exposes `feature_names_in_`, Interchange uses that exact order
and rejects unsupported names. If it exposes only `n_features_in_`, 28 means the
canonical metric order and 29 means `window_duration_sec` followed by the
canonical metric order.

## Saving a model

The simplest supported format is a normal sklearn estimator:

```python
import joblib
joblib.dump(model, "random_forest.joblib")
```

For the Admin Panel to show meaningful anomaly names, train directly on string
labels such as:

```text
NORMAL
HIGH_REQUEST_RATE
FREQUENT_RECONNECT
HIGH_FREQUENCY_SMALL_TRANSFERS
```

If training uses integer-encoded labels, save an Interchange package instead:

```python
import joblib

joblib.dump({
    "model": model,
    "feature_names": feature_names,
    "class_names": {
        0: "NORMAL",
        1: "HIGH_REQUEST_RATE",
        2: "FREQUENT_RECONNECT",
        3: "HIGH_FREQUENCY_SMALL_TRANSFERS",
    },
}, "random_forest.joblib")
```

`feature_names` must contain only fields supported by
`server/traffic_features.py`.

## Runtime behavior

Loading a model is allowed only through the local Admin API. The server checks
that the file exists, contains a predict-capable model, has a compatible feature
schema and can perform a test prediction before it becomes active.

The packet monitor starts only when both conditions are true:

1. a model is loaded;
2. at least one client is online.

The first fractional second after capture starts or restarts is discarded so a
partial window is never presented to a model as a full one-second sample.

The Admin table reports each active client separately. A double-click opens the
latest full feature vector, probabilities for every class and recent prediction
history.

This release is observation-only. No prediction automatically blocks, rejects,
disconnects or otherwise changes a client account.

## Security

Joblib and pickle are Python object serialization formats and can execute code
while loading. Only load model files created by or otherwise trusted by the
administrator.


## Scenario validation without PCAP files

Admin -> `Model & traffic` -> `Model test` reuses the training timeline editor
for a clean live check. The client generates the same NORMAL/anomaly traffic
phases, but the server does not start `PcapManager` and does not create an
`experiment_runs` row or CSV file. Validation results exist only in memory.

The live monitor still uses tcpdump/dumpcap as a streaming packet source, but
the capture is piped to Scapy and is not written to a PCAP file. Each completed
one-second inference result is matched against the expected timeline class.
Windows that overlap a phase transition are not scored.
