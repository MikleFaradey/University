#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Train the Interchange multiclass Random Forest model.

Project invariants
------------------
* every traffic sample is exactly one complete second;
* feature order comes from server/traffic_features.py;
* train/test splitting is done by whole experiment/PCAP groups, never by
  neighboring one-second rows;
* labels are multiclass strings (NORMAL or an anomaly/scenario class);
* the saved joblib dictionary is directly loadable by ModelManager.

Python 3.7+.
"""

from __future__ import print_function

import argparse
import csv
import hashlib
import json
import math
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
SERVER_DIR = THIS_FILE.parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from traffic_features import FEATURE_COLUMNS, FIXED_WINDOW_SEC  # noqa: E402


INTERCHANGE_MODEL_FORMAT = "interchange_random_forest"
MODEL_PACKAGE_VERSION = 1
DATASET_SCHEMA_VERSION = 4
_EPSILON = 1e-9

BASE_REQUIRED_COLUMNS = {
    "experiment_id",
    "window_index",
    "window_duration_sec",
    "label",
}.union(FEATURE_COLUMNS)


def _load_ml_dependencies():
    try:
        import joblib
        import numpy as np
        import sklearn
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import (
            accuracy_score,
            balanced_accuracy_score,
            classification_report,
            confusion_matrix,
            f1_score,
        )
        from sklearn.model_selection import GroupShuffleSplit
    except ImportError as exc:
        raise RuntimeError(
            "ML dependencies are not installed (%s). Install them with: "
            "python3 -m pip install -r server/requirements.txt" % exc
        )

    return {
        "joblib": joblib,
        "np": np,
        "sklearn": sklearn,
        "RandomForestClassifier": RandomForestClassifier,
        "accuracy_score": accuracy_score,
        "balanced_accuracy_score": balanced_accuracy_score,
        "classification_report": classification_report,
        "confusion_matrix": confusion_matrix,
        "f1_score": f1_score,
        "GroupShuffleSplit": GroupShuffleSplit,
    }


def _json_safe(value, np_module=None):
    if isinstance(value, dict):
        return {str(key): _json_safe(item, np_module) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, np_module) for item in value]
    if np_module is not None:
        if isinstance(value, np_module.integer):
            return int(value)
        if isinstance(value, np_module.floating):
            return float(value)
        if isinstance(value, np_module.ndarray):
            return [_json_safe(item, np_module) for item in value.tolist()]
    return value


def _parse_float(value, column, source_file, row_number):
    try:
        number = float(value)
    except Exception:
        raise RuntimeError(
            "%s row %d: column '%s' is not numeric: %r"
            % (source_file, row_number, column, value)
        )
    if not math.isfinite(number):
        raise RuntimeError(
            "%s row %d: column '%s' contains NaN/Inf"
            % (source_file, row_number, column)
        )
    return number


def discover_csv_files(dataset_path):
    path = Path(dataset_path).expanduser().resolve()
    if not path.exists():
        raise RuntimeError("Dataset path does not exist: %s" % path)
    if path.is_file():
        if path.suffix.lower() != ".csv":
            raise RuntimeError("Dataset file must be CSV: %s" % path)
        return [path]

    files = sorted(path.rglob("*.csv"))
    if not files:
        raise RuntimeError("No CSV files found in: %s" % path)
    return files


def _experiment_group(raw, source_file):
    """Return a stable group id for whole-run splitting.

    Current parser CSVs contain both experiment_id and source_pcap.  The pair
    remains stable if the same dataset is exported twice while also avoiding
    collisions when a fresh database later reuses a numeric experiment id.
    """
    experiment_id = str(raw.get("experiment_id", "")).strip()
    source_pcap = str(raw.get("source_pcap", "")).strip()
    if source_pcap:
        return "%s|%s" % (experiment_id, source_pcap)
    return experiment_id


def load_dataset(dataset_path):
    """Load one parser CSV or recursively load a directory of parser CSVs."""
    files = discover_csv_files(dataset_path)
    explicit_file = Path(dataset_path).expanduser().resolve().is_file()

    rows = []
    unique_rows = {}
    accepted_files = []

    for csv_path in files:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                continue

            available = set(reader.fieldnames)
            missing = BASE_REQUIRED_COLUMNS - available
            if missing:
                if explicit_file:
                    raise RuntimeError(
                        "CSV is not an Interchange dataset. Missing columns: %s"
                        % ", ".join(sorted(missing))
                    )
                # A directory may also contain confusion/importance reports.
                continue

            accepted_files.append(csv_path)

            for row_number, raw in enumerate(reader, start=2):
                experiment_id = str(raw.get("experiment_id", "")).strip()
                if not experiment_id:
                    raise RuntimeError(
                        "%s row %d: empty experiment_id" % (csv_path, row_number)
                    )

                label = str(raw.get("label", "")).strip().upper()
                if not label:
                    raise RuntimeError(
                        "%s row %d: empty label" % (csv_path, row_number)
                    )
                if label == "MIXED":
                    raise RuntimeError(
                        "%s row %d: MIXED windows cannot be used for training"
                        % (csv_path, row_number)
                    )

                duration = _parse_float(
                    raw.get("window_duration_sec"),
                    "window_duration_sec",
                    csv_path,
                    row_number,
                )
                if abs(duration - FIXED_WINDOW_SEC) > _EPSILON:
                    raise RuntimeError(
                        "%s row %d: window_duration_sec=%s; Interchange requires "
                        "exactly %.1f second"
                        % (csv_path, row_number, duration, FIXED_WINDOW_SEC)
                    )

                try:
                    window_index = int(float(raw.get("window_index")))
                except Exception:
                    raise RuntimeError(
                        "%s row %d: invalid window_index" % (csv_path, row_number)
                    )

                feature_values = []
                for feature_name in FEATURE_COLUMNS:
                    feature_values.append(
                        _parse_float(
                            raw.get(feature_name),
                            feature_name,
                            csv_path,
                            row_number,
                        )
                    )

                group_id = _experiment_group(raw, csv_path)
                item = {
                    "experiment_id": experiment_id,
                    "group_id": group_id,
                    "source_pcap": str(raw.get("source_pcap", "")).strip(),
                    "window_index": window_index,
                    "label": label,
                    "features": feature_values,
                    "source_file": str(csv_path),
                }

                # Re-exporting the same run into another combined CSV must not
                # silently duplicate one-second samples.
                unique_key = (group_id, window_index)
                previous = unique_rows.get(unique_key)
                if previous is not None:
                    same = (
                        previous["label"] == item["label"]
                        and previous["features"] == item["features"]
                    )
                    if not same:
                        raise RuntimeError(
                            "Conflicting duplicate row: experiment=%s window=%d"
                            % (group_id, window_index)
                        )
                    continue

                unique_rows[unique_key] = item
                rows.append(item)

    if not accepted_files:
        raise RuntimeError("No valid Interchange dataset CSV files were found")
    if not rows:
        raise RuntimeError("Dataset contains no training rows")

    return rows, accepted_files


def validate_dataset(rows):
    classes = sorted(set(row["label"] for row in rows))
    groups = sorted(set(row["group_id"] for row in rows))

    if "NORMAL" not in classes:
        raise RuntimeError("Dataset must contain NORMAL traffic")
    if len(classes) < 2:
        raise RuntimeError("At least two classes are required")
    if len(groups) < 2:
        raise RuntimeError("At least two independent experiments are required")

    class_groups = {}
    for label in classes:
        class_groups[label] = sorted(
            set(row["group_id"] for row in rows if row["label"] == label)
        )
        if len(class_groups[label]) < 2:
            raise RuntimeError(
                "Class %s appears in only %d experiment(s). At least two "
                "independent experiments per class are required for honest "
                "train/test evaluation."
                % (label, len(class_groups[label]))
            )

    return classes, groups, class_groups


def make_grouped_split(X, y, groups, test_size, random_state, deps):
    """Find a whole-experiment split that contains all classes on both sides."""
    all_classes = set(y.tolist())
    splitter = deps["GroupShuffleSplit"](
        n_splits=500,
        test_size=test_size,
        random_state=random_state,
    )

    for train_index, test_index in splitter.split(X, y, groups=groups):
        if (
            set(y[train_index].tolist()) == all_classes
            and set(y[test_index].tolist()) == all_classes
        ):
            return train_index, test_index

    raise RuntimeError(
        "Could not build a whole-experiment train/test split containing every "
        "class on both sides. Add more independent runs for each class or "
        "change --test-size."
    )


def dataset_fingerprint(files):
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: str(item)):
        digest.update(str(path.name).encode("utf-8"))
        with Path(path).open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    return digest.hexdigest()


def feature_schema_fingerprint():
    payload = json.dumps(
        {
            "window_sec": FIXED_WINDOW_SEC,
            "features": list(FEATURE_COLUMNS),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def print_distribution(title, labels):
    counts = Counter(labels)
    print(title)
    for label in sorted(counts):
        print("  %-36s %7d" % (label, counts[label]))


def print_confusion(classes, matrix):
    width = max(20, max(len(name) for name in classes) + 2)
    print()
    print("CONFUSION MATRIX")
    print()
    header = "actual \\ predicted".ljust(width)
    for label in classes:
        header += label[:12].rjust(14)
    print(header)
    for label, row in zip(classes, matrix):
        line = label.ljust(width)
        for value in row:
            line += str(int(value)).rjust(14)
        print(line)


def save_confusion_csv(path, classes, matrix):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["actual/predicted"] + list(classes))
        for label, row in zip(classes, matrix):
            writer.writerow([label] + [int(value) for value in row])


def save_feature_importance_csv(path, feature_names, importances):
    pairs = list(zip(feature_names, importances))
    pairs.sort(key=lambda item: item[1], reverse=True)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["rank", "feature", "importance"])
        for rank, pair in enumerate(pairs, start=1):
            writer.writerow([rank, pair[0], "%.10f" % float(pair[1])])


def train(args):
    deps = _load_ml_dependencies()
    np = deps["np"]

    print("=" * 76)
    print("INTERCHANGE RANDOM FOREST TRAINING")
    print("=" * 76)
    print()

    rows, source_files = load_dataset(args.dataset)
    classes, experiment_groups, class_groups = validate_dataset(rows)

    X = np.asarray([row["features"] for row in rows], dtype=np.float64)
    y = np.asarray([row["label"] for row in rows], dtype=object)
    groups = np.asarray([row["group_id"] for row in rows], dtype=object)

    print("Dataset")
    print("  source CSV files: %d" % len(source_files))
    print("  experiment groups: %d" % len(experiment_groups))
    print("  one-second windows: %d" % len(rows))
    print("  features: %d" % len(FEATURE_COLUMNS))
    print("  window: %.1f second" % FIXED_WINDOW_SEC)
    print("  classes: %d" % len(classes))
    print()
    print_distribution("FULL DATASET", y.tolist())

    train_index, test_index = make_grouped_split(
        X,
        y,
        groups,
        test_size=args.test_size,
        random_state=args.random_state,
        deps=deps,
    )

    X_train = X[train_index]
    X_test = X[test_index]
    y_train = y[train_index]
    y_test = y[test_index]
    groups_train = groups[train_index]
    groups_test = groups[test_index]

    train_groups = sorted(set(groups_train.tolist()))
    test_groups = sorted(set(groups_test.tolist()))

    print()
    print("TRAIN")
    print("  experiments: %d" % len(train_groups))
    print("  windows: %d" % len(train_index))
    print_distribution("  class distribution", y_train.tolist())
    print()
    print("TEST")
    print("  experiments: %d" % len(test_groups))
    print("  windows: %d" % len(test_index))
    print_distribution("  class distribution", y_test.tolist())

    max_depth = None if args.max_depth <= 0 else int(args.max_depth)

    print()
    print("Training Random Forest (%d trees)..." % args.trees)
    model = deps["RandomForestClassifier"](
        n_estimators=int(args.trees),
        criterion="gini",
        max_depth=max_depth,
        min_samples_split=int(args.min_samples_split),
        min_samples_leaf=int(args.min_samples_leaf),
        max_features="sqrt",
        class_weight="balanced_subsample",
        bootstrap=True,
        oob_score=True,
        n_jobs=-1,
        random_state=int(args.random_state),
        verbose=0,
    )
    model.fit(X_train, y_train)

    train_prediction = model.predict(X_train)
    test_prediction = model.predict(X_test)

    train_accuracy = deps["accuracy_score"](y_train, train_prediction)
    test_accuracy = deps["accuracy_score"](y_test, test_prediction)
    balanced_accuracy = deps["balanced_accuracy_score"](y_test, test_prediction)
    macro_f1 = deps["f1_score"](
        y_test, test_prediction, average="macro", zero_division=0
    )
    weighted_f1 = deps["f1_score"](
        y_test, test_prediction, average="weighted", zero_division=0
    )
    report = deps["classification_report"](
        y_test,
        test_prediction,
        labels=classes,
        output_dict=True,
        zero_division=0,
    )
    matrix = deps["confusion_matrix"](
        y_test, test_prediction, labels=classes
    )

    print()
    print("=" * 76)
    print("RESULTS")
    print("=" * 76)
    print("Train accuracy:       %7.3f %%" % (train_accuracy * 100.0))
    print("Test accuracy:        %7.3f %%" % (test_accuracy * 100.0))
    print("Balanced accuracy:    %7.3f %%" % (balanced_accuracy * 100.0))
    print("Macro F1:             %7.3f %%" % (macro_f1 * 100.0))
    print("Weighted F1:          %7.3f %%" % (weighted_f1 * 100.0))
    if hasattr(model, "oob_score_"):
        print("OOB score:            %7.3f %%" % (float(model.oob_score_) * 100.0))

    print()
    print("PER CLASS")
    for label in classes:
        values = report.get(label, {})
        print(
            "%-36s precision=%6.2f%%  recall=%6.2f%%  F1=%6.2f%%  support=%d"
            % (
                label,
                float(values.get("precision", 0.0)) * 100.0,
                float(values.get("recall", 0.0)) * 100.0,
                float(values.get("f1-score", 0.0)) * 100.0,
                int(values.get("support", 0)),
            )
        )

    print_confusion(classes, matrix)

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    metrics = {
        "train_accuracy": float(train_accuracy),
        "test_accuracy": float(test_accuracy),
        "balanced_accuracy": float(balanced_accuracy),
        "macro_f1": float(macro_f1),
        "weighted_f1": float(weighted_f1),
        "oob_score": float(model.oob_score_) if hasattr(model, "oob_score_") else None,
        "classification_report": _json_safe(report, np),
        "confusion_matrix": _json_safe(matrix, np),
    }

    package = {
        "format": INTERCHANGE_MODEL_FORMAT,
        "package_version": MODEL_PACKAGE_VERSION,
        "model_type": "RandomForestClassifier",
        "interchange_version": "6.3.16",
        "schema_version": DATASET_SCHEMA_VERSION,
        "window_sec": FIXED_WINDOW_SEC,
        "feature_names": list(FEATURE_COLUMNS),
        "feature_schema_sha256": feature_schema_fingerprint(),
        "classes": [str(value) for value in model.classes_],
        "model": model,
        "training": {
            "trained_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "python_version": platform.python_version(),
            "sklearn_version": deps["sklearn"].__version__,
            "numpy_version": np.__version__,
            "dataset_sha256": dataset_fingerprint(source_files),
            "dataset_rows": len(rows),
            "experiment_count": len(experiment_groups),
            "class_experiment_counts": {
                label: len(class_groups[label]) for label in classes
            },
            "train_windows": len(train_index),
            "test_windows": len(test_index),
            "train_experiments": train_groups,
            "test_experiments": test_groups,
            "random_state": int(args.random_state),
            "test_size": float(args.test_size),
            "parameters": {
                "n_estimators": int(args.trees),
                "max_depth": max_depth,
                "min_samples_split": int(args.min_samples_split),
                "min_samples_leaf": int(args.min_samples_leaf),
                "max_features": "sqrt",
                "class_weight": "balanced_subsample",
            },
        },
        "metrics": metrics,
    }

    deps["joblib"].dump(package, str(output_path), compress=3)

    metrics_path = output_path.with_suffix(".metrics.json")
    confusion_path = output_path.with_suffix(".confusion.csv")
    importance_path = output_path.with_suffix(".feature_importance.csv")

    with metrics_path.open("w", encoding="utf-8") as handle:
        json.dump(
            _json_safe(
                {
                    "format": INTERCHANGE_MODEL_FORMAT,
                    "classes": classes,
                    "feature_names": list(FEATURE_COLUMNS),
                    "feature_schema_sha256": package["feature_schema_sha256"],
                    "window_sec": FIXED_WINDOW_SEC,
                    "training": package["training"],
                    "metrics": metrics,
                },
                np,
            ),
            handle,
            indent=2,
            ensure_ascii=False,
        )

    save_confusion_csv(confusion_path, classes, matrix)
    save_feature_importance_csv(
        importance_path, FEATURE_COLUMNS, model.feature_importances_
    )

    print()
    print("=" * 76)
    print("SAVED")
    print("=" * 76)
    print("Model:              %s" % output_path)
    print("Metrics:            %s" % metrics_path)
    print("Confusion matrix:   %s" % confusion_path)
    print("Feature importance: %s" % importance_path)
    print()
    print("The .joblib can be loaded directly in Admin -> Model & traffic.")

    return {
        "model_path": str(output_path),
        "metrics_path": str(metrics_path),
        "confusion_path": str(confusion_path),
        "importance_path": str(importance_path),
        "metrics": metrics,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Train the Interchange multiclass Random Forest"
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Parser dataset CSV or directory containing dataset CSV files",
    )
    parser.add_argument(
        "--output",
        default="models/interchange_random_forest.joblib",
        help="Output .joblib model package",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.20,
        help="Fraction of whole experiments reserved for test (default 0.20)",
    )
    parser.add_argument(
        "--trees",
        type=int,
        default=500,
        help="Number of trees (default 500)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=0,
        help="Maximum tree depth; 0 means unlimited (default 0)",
    )
    parser.add_argument(
        "--min-samples-split",
        type=int,
        default=4,
        help="Minimum samples needed to split a node (default 4)",
    )
    parser.add_argument(
        "--min-samples-leaf",
        type=int,
        default=2,
        help="Minimum samples in a leaf (default 2)",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed (default 42)",
    )

    args = parser.parse_args(argv)
    if not 0.05 <= args.test_size <= 0.50:
        parser.error("--test-size must be between 0.05 and 0.50")
    if args.trees < 10:
        parser.error("--trees must be at least 10")
    if args.max_depth < 0:
        parser.error("--max-depth cannot be negative")
    if args.min_samples_split < 2:
        parser.error("--min-samples-split must be at least 2")
    if args.min_samples_leaf < 1:
        parser.error("--min-samples-leaf must be at least 1")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        train(args)
    except KeyboardInterrupt:
        print("\nTraining interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
