"""End-to-end training comparison contract on synthetic independent experiments."""
import csv
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from ml.train_compare import ALGORITHMS, train_comparison  # noqa: E402
from ml.training_jobs import TrainingBusyError, TrainingJobManager  # noqa: E402
from model_runtime import ModelManager  # noqa: E402
from traffic_features import FEATURE_COLUMNS  # noqa: E402


def make_dataset(path):
    columns = (
        ["experiment_id", "source_pcap", "window_index",
         "window_duration_sec", "label"] + list(FEATURE_COLUMNS)
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for cls, label in enumerate(("NORMAL", "HIGH_REQUEST_RATE")):
            for run in range(5):
                for window in range(12):
                    row = {
                        "experiment_id": "%s-%d" % (label, run),
                        "source_pcap": "%s-%d.pcap" % (label, run),
                        "window_index": window,
                        "window_duration_sec": "1.0",
                        "label": label,
                    }
                    row.update({
                        name: "%.3f" % (
                            cls * 15.0 + run * 0.1 + window * 0.02 +
                            feature * 0.005
                        )
                        for feature, name in enumerate(FEATURE_COLUMNS)
                    })
                    writer.writerow(row)


def test_full_comparison():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        dataset = root / "training.csv"
        make_dataset(dataset)
        events = []
        result = train_comparison(
            str(dataset), str(root / "models"), ALGORITHMS,
            progress=lambda percent, message, rows:
                events.append((percent, message, len(rows))),
        )
        assert result["recommended_algorithm"] in ALGORITHMS
        assert set(result["dataset"]["train_experiments"]).isdisjoint(
            result["dataset"]["test_experiments"]
        )
        assert len(result["results"]) == len(ALGORITHMS)
        assert result["results"][0]["macro_f1"] >= result["results"][-1]["macro_f1"]
        assert events[-1][0] == 100
        assert pathlib.Path(result["summary_path"]).is_file()
        assert pathlib.Path(result["comparison_csv"]).is_file()

        for row in result["results"]:
            assert 0 <= row["macro_f1"] <= 1
            assert 0 <= row["balanced_accuracy"] <= 1
            assert pathlib.Path(row["metrics_path"]).is_file()
            assert pathlib.Path(row["confusion_path"]).is_file()
            manager = ModelManager()
            status = manager.load(row["model_path"])
            assert status["algorithm"] == row["algorithm"]
            assert status["feature_count"] == len(FEATURE_COLUMNS)

        job = TrainingJobManager()
        started = job.start(str(dataset), str(root / "jobs"), ["random_forest"])
        assert started["state"] in ("queued", "running", "completed")
        try:
            job.start(str(dataset), str(root / "jobs2"), ["extra_trees"])
        except TrainingBusyError:
            pass
        else:
            # A very fast machine may already have completed the tiny job.
            assert job.snapshot()["state"] == "completed"
        deadline = time.monotonic() + 90
        while job.snapshot()["state"] in ("queued", "running"):
            if time.monotonic() >= deadline:
                raise AssertionError("Background training exceeded deadline")
            time.sleep(0.1)
        assert job.snapshot()["state"] == "completed", job.snapshot()
        assert len(job.snapshot()["results"]) == 1


if __name__ == "__main__":
    test_full_comparison()
    print("OK: multiclass model comparison, package loading and background job")
