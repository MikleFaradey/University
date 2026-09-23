# Interchange Random Forest training

The training pipeline uses the same `server/traffic_features.py` schema as live
inference. The project ML window is fixed at **exactly 1 second** and the model
uses the canonical **28 traffic features** in their declared order.

## Install dependencies

From the project root:

```bash
python3 -m pip install -r server/requirements.txt
```

For Python 3.7 the project requirements intentionally pin the last compatible
NumPy/SciPy/scikit-learn generation.

## 1. Build a dataset from training captures

Example:

```bash
python3 parser/pcap_to_csv.py \
  --input-dir /path/to/server/pcap \
  --output ./dataset/training.csv
```

Do **not** delete `experiment_id`, `source_pcap`, `window_duration_sec`, `label`
or any canonical feature columns from the parser output.

## 2. Train Random Forest

```bash
python3 server/ml/train_random_forest.py \
  --dataset ./dataset \
  --output ./models/interchange_rf_v1.joblib
```

Default baseline parameters:

- 500 trees;
- `max_depth=None`;
- `min_samples_split=4`;
- `min_samples_leaf=2`;
- `max_features="sqrt"`;
- `class_weight="balanced_subsample"`;
- `random_state=42`.

The split is by **whole experiment/PCAP groups**, never by random one-second
rows. This prevents neighboring windows from the same run leaking into both
training and test data.

Every class must appear in at least two independent experiments, and the
trainer searches for a grouped split that contains every class in both train
and test sets.

## Output

Training creates:

```text
interchange_rf_v1.joblib
interchange_rf_v1.metrics.json
interchange_rf_v1.confusion.csv
interchange_rf_v1.feature_importance.csv
```

The `.joblib` is an Interchange model package containing the estimator, feature
order, classes, fixed window, training metadata and quality metrics. It can be
selected directly in **Admin -> Model & traffic**.

## Validate a model before opening Admin

```bash
python3 server/ml/check_model.py ./models/interchange_rf_v1.joblib
```

The check loads the model through the same `ModelManager` used by live runtime
and performs one test prediction with the canonical one-second vector.

## Important evaluation metrics

Do not judge the model only by overall accuracy. Inspect:

- macro F1;
- recall for each anomaly class;
- confusion matrix;
- train-vs-test accuracy gap;
- feature importance;
- live `Model test` results in the Admin panel.
