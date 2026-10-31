"""Single-job, local-admin offline model training coordinator.

Training runs in a worker thread to keep HTTP and live inference responsive.
It never replaces the actively loaded model; deployment remains manual.
"""
import threading
import time

from .train_compare import ALGORITHMS, check_algorithms, train_comparison


class TrainingBusyError(RuntimeError):
    pass


class TrainingJobManager(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._job = {
            "state": "idle", "progress": 0, "message": "No training started",
            "results": [], "summary": None,
        }
        self._thread = None
        self._sequence = 0

    def snapshot(self):
        with self._lock:
            snapshot = dict(self._job)
            snapshot["results"] = [dict(item) for item in self._job["results"]]
            return snapshot

    def start(self, dataset, output_dir, algorithms=None, test_size=0.20,
              random_state=42):
        if not isinstance(dataset, str) or not dataset.strip():
            raise ValueError("Dataset CSV or directory is required")
        if not isinstance(output_dir, str) or not output_dir.strip():
            raise ValueError("Model output directory is required")
        algorithms = check_algorithms(ALGORITHMS if algorithms is None else algorithms)
        try:
            test_size = float(test_size)
            random_state = int(random_state)
        except (ValueError, TypeError):
            raise ValueError("Invalid test_size or random_state")
        if not 0.05 <= test_size <= 0.50:
            raise ValueError("test_size must be between 0.05 and 0.50")

        with self._lock:
            if self._job["state"] in ("queued", "running"):
                raise TrainingBusyError("A model comparison is already running")
            self._sequence += 1
            job_id = self._sequence
            self._job = {
                "id": job_id, "state": "queued", "progress": 0,
                "message": "Queued", "results": [], "summary": None,
                "dataset": dataset.strip(), "output_dir": output_dir.strip(),
                "algorithms": algorithms, "started_at": time.time(),
            }
            worker = threading.Thread(
                target=self._run,
                args=(job_id, dataset.strip(), output_dir.strip(), algorithms,
                      test_size, random_state),
                name="Interchange-model-training", daemon=True,
            )
            self._thread = worker
            worker.start()
            return self.snapshot()

    def _run(self, job_id, dataset, output_dir, algorithms, test_size, random_state):
        def update(pct, message, results):
            with self._lock:
                if self._job.get("id") != job_id:
                    return
                self._job.update({
                    "state": "running", "progress": int(pct),
                    "message": str(message),
                    "results": [dict(row) for row in results],
                })

        try:
            update(0, "Loading and validating dataset", [])
            summary = train_comparison(
                dataset, output_dir, algorithms, test_size, random_state,
                progress=update,
            )
            with self._lock:
                if self._job.get("id") == job_id:
                    self._job.update({
                        "state": "completed", "progress": 100,
                        "message": "Comparison finished — select and load a model",
                        "results": summary["results"],
                        "summary": summary, "finished_at": time.time(),
                    })
        except Exception as exc:
            with self._lock:
                if self._job.get("id") == job_id:
                    self._job.update({
                        "state": "error", "message": "%s" % exc,
                        "finished_at": time.time(),
                    })
