# Interchange model training and comparison

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

## Compare five classifiers on the same dataset

The existing `train_random_forest.py` CLI is retained for reproducibility and
backward compatibility. For an algorithm comparison, run:

```bash
python3 server/ml/train_compare.py \
    --dataset ./dataset \
    --output-dir ./models/comparison \
    --algorithms random_forest,extra_trees,hist_gradient_boosting,logistic_regression,svm_rbf
```

Available algorithms: **Random Forest**, **Extra Trees**, **Histogram Gradient
Boosting**, **Logistic Regression** (with standard scaling), and **RBF SVM**
(with standard scaling and probability estimates).

The same `GroupShuffleSplit` experiment-level split is used for all algorithms.
Individual per-algorithm `.joblib`, `.metrics.json`, `.confusion.csv` files
and the `comparison.csv` / `comparison.json` reports are saved in the output
directory. The table ranks candidates using **macro F1** on the common holdout,
then balanced accuracy for ties. Check per-class recall and confusion matrices
before selecting a classifier.

The Admin UI contains a new `Model & traffic -> Train & compare` page. Enter
the **server-side** dataset path and output directory, select one or several
algorithms, click **Train and compare**, then review results. Select a model and
click **Load selected model for live monitoring** if you trust the generated
file. Model activation is manual. The training runs in a background server
worker and does not automatically retrain from incoming traffic.

**Research limitation:** choosing the winner based on the shared holdout makes
that winner's displayed test result optimistic as a final generalization
estimate. Collect further independent experiments (ideally from different
sessions/hosts) and evaluate the selected model once on that untouched test
set. The saved dataset fingerprint, group IDs and feature-schema hash allow
reproducing the baseline experiment.

Training needs `scikit-learn`, `numpy` and `joblib` installed **on the server**.
The Admin client does not need those ML dependencies. Large datasets and SVM
training can consume substantial CPU/RAM; only one training job runs at a time.

```bash
python3 tests/test_multi_algorithm_training.py
```

This test generates a synthetic dataset solely to verify the training API,
artifacts and model loading. It is **not** evidence of real-world detection
accuracy.
