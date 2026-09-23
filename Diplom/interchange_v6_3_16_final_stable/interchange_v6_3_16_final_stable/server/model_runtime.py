"""Thread-safe ML model loading and one-second live inference."""
from collections import deque
from pathlib import Path
import threading
import time

from traffic_features import (
    FEATURE_COLUMNS, FIXED_WINDOW_SEC, MODEL_AVAILABLE_FEATURES,
    feature_values,
)


class ModelLoadError(RuntimeError):
    pass


class ModelManager(object):
    """Owns the trusted local model and recent inference state."""

    def __init__(self, history_seconds=60, event_limit=200):
        self._lock = threading.RLock()
        self._model = None
        self._path = None
        self._feature_names = []
        self._classes = []
        self._class_names = None
        self._loaded_at = None
        self._error = None
        self._latest = {}
        self._history = {}
        self._events = deque(maxlen=int(event_limit))
        self._history_seconds = int(history_seconds)

    def _event(self, message, level="info", client_id=None):
        event = {
            "epoch": time.time(),
            "time": time.strftime("%H:%M:%S"),
            "level": str(level),
            "message": str(message),
        }
        if client_id is not None:
            event["client_id"] = str(client_id)
        with self._lock:
            self._events.append(event)

    def is_loaded(self):
        with self._lock:
            return self._model is not None

    @staticmethod
    def _unwrap_loaded_object(obj):
        """Accept a plain estimator or an optional Interchange model package.

        A package is a joblib/pickle dictionary with at least ``model`` and may
        additionally contain ``feature_names`` and ``class_names``.
        """
        if isinstance(obj, dict) and "model" in obj:
            return (
                obj["model"],
                obj.get("feature_names"),
                obj.get("class_names"),
            )
        return obj, None, None

    @staticmethod
    def _resolve_features(model, package_features=None):
        if package_features:
            names = [str(value) for value in package_features]
        elif getattr(model, "feature_names_in_", None) is not None:
            names = [str(value) for value in list(model.feature_names_in_)]
        else:
            count = getattr(model, "n_features_in_", None)
            if count is None:
                raise ModelLoadError(
                    "The model does not expose n_features_in_ or feature_names_in_. "
                    "Save an Interchange model package with feature_names."
                )
            count = int(count)
            if count == len(FEATURE_COLUMNS):
                names = list(FEATURE_COLUMNS)
            elif count == len(FEATURE_COLUMNS) + 1:
                names = ["window_duration_sec"] + list(FEATURE_COLUMNS)
            else:
                raise ModelLoadError(
                    "Model expects %d features, but Interchange live runtime can "
                    "provide %d canonical metrics (or %d including the fixed "
                    "window_duration_sec)." % (
                        count, len(FEATURE_COLUMNS), len(FEATURE_COLUMNS) + 1
                    )
                )

        unknown = [name for name in names if name not in MODEL_AVAILABLE_FEATURES]
        if unknown:
            raise ModelLoadError(
                "Model contains unsupported features: %s" % ", ".join(unknown)
            )
        if len(set(names)) != len(names):
            raise ModelLoadError("Model feature list contains duplicates")
        return names

    @staticmethod
    def _raw_classes(model):
        raw = getattr(model, "classes_", None)
        if raw is None:
            return []
        try:
            return list(raw)
        except Exception:
            return []

    @staticmethod
    def _display_class(raw_value, class_names):
        if class_names is None:
            return str(raw_value)

        if isinstance(class_names, dict):
            # JSON/joblib packages often have stringified integer keys.
            if raw_value in class_names:
                return str(class_names[raw_value])
            key = str(raw_value)
            if key in class_names:
                return str(class_names[key])
            return str(raw_value)

        try:
            index = int(raw_value)
            if float(raw_value) == float(index) and 0 <= index < len(class_names):
                return str(class_names[index])
        except Exception:
            pass
        return str(raw_value)

    def load(self, path):
        model_path = Path(path).expanduser().resolve()
        if not model_path.is_file():
            raise ModelLoadError("Model file not found: %s" % model_path)

        try:
            import joblib
        except ImportError:
            raise ModelLoadError(
                "joblib is not installed. Install server/requirements.txt first."
            )

        try:
            loaded = joblib.load(str(model_path))
        except Exception as exc:
            raise ModelLoadError("Cannot load model: %s" % exc)

        model, package_features, package_class_names = self._unwrap_loaded_object(loaded)
        if not callable(getattr(model, "predict", None)):
            raise ModelLoadError("Selected file does not contain a predict-capable model")

        feature_names = self._resolve_features(model, package_features)
        raw_classes = self._raw_classes(model)
        display_classes = [
            self._display_class(value, package_class_names)
            for value in raw_classes
        ]

        # Fail during loading, not during the first real traffic second.
        zero_metrics = dict((name, 0.0) for name in FEATURE_COLUMNS)
        test_row = [feature_values(zero_metrics, feature_names)]
        try:
            test_prediction = model.predict(test_row)
            if len(test_prediction) < 1:
                raise ValueError("empty prediction")
            if callable(getattr(model, "predict_proba", None)):
                test_prob = model.predict_proba(test_row)
                if len(test_prob) < 1:
                    raise ValueError("empty probability vector")
        except Exception as exc:
            raise ModelLoadError(
                "Model is not compatible with the Interchange live feature vector: %s"
                % exc
            )

        with self._lock:
            self._model = model
            self._path = str(model_path)
            self._feature_names = list(feature_names)
            self._classes = display_classes
            self._class_names = package_class_names
            self._loaded_at = time.time()
            self._error = None
            self._latest.clear()
            self._history.clear()

        self._event(
            "Model loaded: %s (%d features, classes: %s)" % (
                model_path.name,
                len(feature_names),
                ", ".join(display_classes) if display_classes else "unknown",
            )
        )
        return self.status()

    def unload(self):
        with self._lock:
            old_path = self._path
            self._model = None
            self._path = None
            self._feature_names = []
            self._classes = []
            self._class_names = None
            self._loaded_at = None
            self._error = None
            self._latest.clear()
            self._history.clear()
        self._event(
            "Model unloaded%s" % (" (%s)" % Path(old_path).name if old_path else "")
        )

    def set_runtime_error(self, text):
        with self._lock:
            self._error = str(text) if text else None

    def clear_runtime_error(self):
        with self._lock:
            self._error = None

    def status(self):
        with self._lock:
            return {
                "loaded": self._model is not None,
                "path": self._path,
                "file_name": Path(self._path).name if self._path else None,
                "loaded_at": self._loaded_at,
                "feature_count": len(self._feature_names),
                "feature_names": list(self._feature_names),
                "classes": list(self._classes),
                "window_sec": FIXED_WINDOW_SEC,
                "observation_only": True,
                "runtime_error": self._error,
            }

    def predict_window(self, client_id, client_ip, window_start_epoch, metrics):
        with self._lock:
            model = self._model
            feature_names = list(self._feature_names)
            class_names = self._class_names
            raw_classes = self._raw_classes(model) if model is not None else []

        if model is None:
            return None

        row = [feature_values(metrics, feature_names)]
        try:
            raw_prediction = model.predict(row)[0]
            display_prediction = self._display_class(raw_prediction, class_names)

            probabilities = {}
            confidence = None
            if callable(getattr(model, "predict_proba", None)):
                raw_probs = list(model.predict_proba(row)[0])
                for index, value in enumerate(raw_probs):
                    if index < len(raw_classes):
                        name = self._display_class(raw_classes[index], class_names)
                    elif index < len(self._classes):
                        name = self._classes[index]
                    else:
                        name = "class_%d" % index
                    probabilities[str(name)] = float(value)

                if probabilities:
                    if display_prediction in probabilities:
                        confidence = probabilities[display_prediction]
                    else:
                        confidence = max(probabilities.values())

            status = (
                "NORMAL" if str(display_prediction).strip().upper() == "NORMAL"
                else "ANOMALY"
            )
            result = {
                "client_id": str(client_id),
                "client_ip": str(client_ip),
                "window_start_epoch": float(window_start_epoch),
                "window_end_epoch": float(window_start_epoch) + FIXED_WINDOW_SEC,
                "window_duration_sec": FIXED_WINDOW_SEC,
                "status": status,
                "prediction": str(display_prediction),
                "anomaly_type": (
                    None if status == "NORMAL" else str(display_prediction)
                ),
                "confidence": confidence,
                "class_probabilities": probabilities,
                "features": dict(metrics),
            }
        except Exception as exc:
            self.set_runtime_error("Inference failed: %s" % exc)
            self._event(
                "Inference error for %s: %s" % (client_id, exc),
                level="error", client_id=client_id
            )
            raise

        with self._lock:
            previous = self._latest.get(str(client_id))
            self._latest[str(client_id)] = result
            history = self._history.get(str(client_id))
            if history is None:
                history = deque(maxlen=self._history_seconds)
                self._history[str(client_id)] = history
            history.append(result)
            self._error = None

        # Avoid a noisy log for every normal second.  Log anomaly transitions,
        # anomaly type changes, and recovery to NORMAL.
        prev_prediction = previous.get("prediction") if previous else None
        if result["status"] == "ANOMALY" and prev_prediction != result["prediction"]:
            message = "%s: %s" % (client_id, result["prediction"])
            if confidence is not None:
                message += " (%.1f%%)" % (confidence * 100.0)
            self._event(message, level="anomaly", client_id=client_id)
        elif (previous and previous.get("status") == "ANOMALY" and
              result["status"] == "NORMAL"):
            self._event(
                "%s: traffic returned to NORMAL" % client_id,
                level="info", client_id=client_id
            )
        return result

    def latest_for(self, client_id):
        with self._lock:
            value = self._latest.get(str(client_id))
            return dict(value) if value else None

    def history_for(self, client_id):
        with self._lock:
            return [dict(item) for item in self._history.get(str(client_id), [])]

    def events(self, limit=50):
        limit = max(1, min(int(limit), 200))
        with self._lock:
            values = list(self._events)[-limit:]
        return [dict(item) for item in values]
