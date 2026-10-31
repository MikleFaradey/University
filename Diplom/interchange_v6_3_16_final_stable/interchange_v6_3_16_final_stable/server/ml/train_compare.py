#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare supervised classifiers on one identical experiment-grouped holdout.

No online learning, no implicit deployment. All candidate models use the
canonical Interchange fixed 1-second feature schema.
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from .train_random_forest import (
    FEATURE_COLUMNS, FIXED_WINDOW_SEC, DATASET_SCHEMA_VERSION,
    _json_safe, _load_ml_dependencies, dataset_fingerprint,
    feature_schema_fingerprint, load_dataset, make_grouped_split,
        save_confusion_csv, validate_dataset,
    )
except ImportError:
    # Direct command-line execution: python server/ml/train_compare.py
    from train_random_forest import (
        FEATURE_COLUMNS, FIXED_WINDOW_SEC, DATASET_SCHEMA_VERSION,
        _json_safe, _load_ml_dependencies, dataset_fingerprint,
        feature_schema_fingerprint, load_dataset, make_grouped_split,
        save_confusion_csv, validate_dataset,
    )

ALGORITHMS = (
    "random_forest",
    "extra_trees",
    "hist_gradient_boosting",
    "logistic_regression",
    "svm_rbf",
)
DISPLAY_NAMES = {
    "random_forest": "Random Forest",
    "extra_trees": "Extra Trees",
    "hist_gradient_boosting": "Gradient Boosting",
    "logistic_regression": "Logistic Regression",
    "svm_rbf": "SVM (RBF)",
}
MODEL_FORMAT = "interchange_classifier"
SEED = 42


def make_estimator(algorithm, seed):
    """Build estimators without global sklearn imports (fast server startup)."""
    from sklearn.ensemble import (
        ExtraTreesClassifier, HistGradientBoostingClassifier,
        RandomForestClassifier,
    )
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC

    if algorithm == "random_forest":
        return RandomForestClassifier(
            n_estimators=160, min_samples_leaf=2,
            class_weight="balanced_subsample", random_state=seed, n_jobs=-1,
        )
    if algorithm == "extra_trees":
        return ExtraTreesClassifier(
            n_estimators=160, min_samples_leaf=2,
            class_weight="balanced", random_state=seed, n_jobs=-1,
        )
    if algorithm == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            max_iter=120, max_depth=6, learning_rate=0.08,
            random_state=seed,
        )
    if algorithm == "logistic_regression":
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=1500, class_weight="balanced",
                               random_state=seed),
        )
    if algorithm == "svm_rbf":
        return make_pipeline(
            StandardScaler(),
            SVC(kernel="rbf", C=2.0, class_weight="balanced",
                probability=True, random_state=seed),
        )
    raise ValueError("Unsupported algorithm: %s" % algorithm)


def check_algorithms(algorithms):
    if isinstance(algorithms, str):
        algorithms = [name.strip() for name in algorithms.split(",")]
    values = []
    for name in algorithms:
        name = str(name).strip().lower()
        if name not in ALGORITHMS:
            raise ValueError("Unsupported algorithm: %s" % name)
        if name not in values:
            values.append(name)
    if not values:
        raise ValueError("Choose at least one algorithm")
    return values


def train_comparison(dataset, output_dir, algorithms=ALGORITHMS,
                     test_size=0.20, random_state=SEED, progress=None):
    """Train each candidate once on the same holdout; return JSON-ready report.

    Every class must be present in independent train and test experiments.
    The holdout compares baseline algorithms; it is NOT an unbiased final
    generalization estimate once a winner is chosen using that holdout.
    """
    if not 0.05 <= float(test_size) <= 0.50:
        raise ValueError("test_size must be between 0.05 and 0.50")
    algorithms = check_algorithms(algorithms)
    deps = _load_ml_dependencies()
    np = deps["np"]
    rows, source_files = load_dataset(dataset)
    classes, experiment_groups, class_groups = validate_dataset(rows)
    X = np.asarray([row["features"] for row in rows], dtype=np.float64)
    y = np.asarray([row["label"] for row in rows], dtype=object)
    groups = np.asarray([row["group_id"] for row in rows], dtype=object)
    train_index, test_index = make_grouped_split(
        X, y, groups, float(test_size), int(random_state), deps,
    )
    X_train, X_test = X[train_index], X[test_index]
    y_train, y_test = y[train_index], y[test_index]
    train_groups = sorted(set(groups[train_index].tolist()))
    test_groups = sorted(set(groups[test_index].tolist()))
    if set(train_groups) & set(test_groups):
        raise AssertionError("Experiment leakage across split")

    target = Path(output_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    dataset_info = {
        "dataset_sha256": dataset_fingerprint(source_files),
        "dataset_rows": len(rows),
        "source_csv_count": len(source_files),
        "experiment_count": len(experiment_groups),
        "class_experiment_counts": {
            label: len(class_groups[label]) for label in classes
        },
        "train_windows": len(train_index),
        "test_windows": len(test_index),
        "train_experiments": train_groups,
        "test_experiments": test_groups,
        "test_size": float(test_size),
        "random_state": int(random_state),
        "feature_schema_sha256": feature_schema_fingerprint(),
        "window_sec": FIXED_WINDOW_SEC,
        "feature_count": len(FEATURE_COLUMNS),
        "classes": classes,
    }
    results = []
    if progress is not None:
        progress(0, "Valid dataset; starting algorithms", results)
    for number, algorithm in enumerate(algorithms):
        if progress is not None:
            progress(round(100.0 * number / len(algorithms)),
                     "Training %s" % DISPLAY_NAMES[algorithm], results)
        model = make_estimator(algorithm, int(random_state))
        model.fit(X_train, y_train)
        train_predictions = model.predict(X_train)
        predictions = model.predict(X_test)
        report = deps["classification_report"](
            y_test, predictions, labels=classes, output_dict=True,
            zero_division=0,
        )
        matrix = deps["confusion_matrix"](
            y_test, predictions, labels=classes,
        )
        metrics = {
            "train_accuracy": float(deps["accuracy_score"](y_train, train_predictions)),
            "test_accuracy": float(deps["accuracy_score"](y_test, predictions)),
            "balanced_accuracy": float(deps["balanced_accuracy_score"](y_test, predictions)),
            "macro_f1": float(deps["f1_score"](
                y_test, predictions, average="macro", zero_division=0,
            )),
            "weighted_f1": float(deps["f1_score"](
                y_test, predictions, average="weighted", zero_division=0,
            )),
            "classification_report": _json_safe(report, np),
            "confusion_matrix": _json_safe(matrix, np),
        }
        path = target / ("%s.joblib" % algorithm)
        package = {
            "format": MODEL_FORMAT,
            "package_version": 1,
            "model_type": type(model).__name__,
            "algorithm": algorithm,
            "interchange_version": "6.3.16",
            "schema_version": DATASET_SCHEMA_VERSION,
            "window_sec": FIXED_WINDOW_SEC,
            "feature_names": list(FEATURE_COLUMNS),
            "feature_schema_sha256": feature_schema_fingerprint(),
            "classes": [str(value) for value in model.classes_],
            "model": model,
            "training": dict(
                dataset_info,
                trained_at_utc=datetime.now(timezone.utc).replace(
                    microsecond=0,
                ).isoformat().replace("+00:00", "Z"),
                sklearn_version=deps["sklearn"].__version__,
            ),
            "metrics": metrics,
        }
        # Never expose a partially written joblib to the Admin model loader.
        temporary = path.with_suffix(".joblib.tmp")
        try:
            deps["joblib"].dump(package, str(temporary), compress=3)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
        metrics_path = path.with_suffix(".metrics.json")
        with metrics_path.open("w", encoding="utf-8") as handle:
            json.dump({"algorithm": algorithm, "metrics": metrics,
                       "training": package["training"]},
                      handle, indent=2, ensure_ascii=False)
        confusion_path = path.with_suffix(".confusion.csv")
        save_confusion_csv(confusion_path, classes, matrix)
        result = {
            "algorithm": algorithm,
            "name": DISPLAY_NAMES[algorithm],
            "model_path": str(path),
            "metrics_path": str(metrics_path),
            "confusion_path": str(confusion_path),
            "train_accuracy": metrics["train_accuracy"],
            "test_accuracy": metrics["test_accuracy"],
            "balanced_accuracy": metrics["balanced_accuracy"],
            "macro_f1": metrics["macro_f1"],
            "weighted_f1": metrics["weighted_f1"],
            "recall_by_class": {
                label: float(report[label]["recall"]) for label in classes
            },
        }
        results.append(result)
        if progress is not None:
            progress(round(100.0 * (number + 1) / len(algorithms)),
                     "Finished %s" % DISPLAY_NAMES[algorithm], results)

    ranking = sorted(results, key=lambda r: (
        -r["macro_f1"], -r["balanced_accuracy"], r["algorithm"],
    ))
    summary = {
        "format": "interchange_model_comparison",
        "dataset": dataset_info,
        "selection_metric": "holdout_macro_f1",
        "recommended_algorithm": ranking[0]["algorithm"],
        "results": ranking,
        "note": ("The same experiment-grouped holdout was used for all models. "
                 "Selection on this holdout may bias the selected model's score; "
                 "evaluate a final selected model on untouched experiments."),
    }
    summary_path = target / "comparison.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    csv_path = target / "comparison.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "algorithm", "train_accuracy", "test_accuracy",
            "balanced_accuracy", "macro_f1", "weighted_f1", "model_path",
        ])
        for item in ranking:
            writer.writerow([item[key] for key in [
                "algorithm", "train_accuracy", "test_accuracy",
                "balanced_accuracy", "macro_f1", "weighted_f1", "model_path",
            ]])
    summary["summary_path"] = str(summary_path)
    summary["comparison_csv"] = str(csv_path)
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare Interchange classifiers using independent experiments",
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output-dir", default="./models/comparison")
    parser.add_argument("--algorithms", default=",".join(ALGORITHMS),
                        help="Comma-separated algorithm ids, or all by default")
    parser.add_argument("--test-size", type=float, default=0.20)
    parser.add_argument("--random-state", type=int, default=SEED)
    args = parser.parse_args(argv)
    try:
        args.algorithms = check_algorithms(args.algorithms)
    except ValueError as exc:
        parser.error(str(exc))
    if not 0.05 <= args.test_size <= 0.50:
        parser.error("--test-size must be between 0.05 and 0.50")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        result = train_comparison(
            args.dataset, args.output_dir, args.algorithms,
            args.test_size, args.random_state,
            progress=lambda pct, msg, rows: print("%3d%% %s" % (pct, msg), flush=True),
        )
    except (Exception, KeyboardInterrupt) as exc:
        print("Training failed: %s" % exc, file=sys.stderr)
        return 1
    print("Comparison saved: %s" % result["summary_path"])
    print("Best holdout macro F1: %s" % result["recommended_algorithm"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
