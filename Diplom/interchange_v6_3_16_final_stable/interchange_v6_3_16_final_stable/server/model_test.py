"""Scenario-driven live model validation without PCAP/CSV files.

The test reuses the client's normal experiment traffic generator, but no
training capture is started and no experiment row is created.  The already
running LiveTrafficMonitor supplies the exact same fixed one-second feature
vectors used during production inference.
"""
import math
import threading
import time

import db


ACTIVE_STATES = ("starting", "running", "stopping", "finalizing")
TERMINAL_STATES = ("completed", "stopped", "error", "timeout")


class ModelTestManager(object):
    def __init__(self, hub, model_manager, traffic_monitor):
        self.hub = hub
        self.model = model_manager
        self.monitor = traffic_monitor
        self._lock = threading.RLock()
        self._state = None
        self._next_id = -1
        self._collector = None

    def active_for_user(self, user_id):
        with self._lock:
            state = self._state
            return bool(
                state and state.get("target_user_id") == str(user_id)
                and state.get("status") in ACTIVE_STATES
            )

    def _capture_ready_for(self, user_id):
        snapshot = self.monitor.snapshot()
        if not snapshot.get("model", {}).get("loaded"):
            raise RuntimeError("Load a model before starting a model test")
        capture = snapshot.get("capture") or {}
        if capture.get("state") != "running":
            detail = capture.get("error") or capture.get("state") or "not running"
            raise RuntimeError("Live traffic capture is not ready: %s" % detail)
        clients = snapshot.get("clients") or []
        if not any(str(item.get("user_id")) == str(user_id) for item in clients):
            raise RuntimeError("Selected client is not available in live monitoring")

    def start(self, target_user_id, baseline_dir, timeline):
        target_user_id = str(target_user_id or "").strip()
        baseline_dir = str(baseline_dir or "").strip()
        if not target_user_id:
            raise RuntimeError("Target client is required")
        if not baseline_dir:
            raise RuntimeError("Client baseline folder path is required")
        if not timeline:
            raise RuntimeError("Model test timeline is empty")

        user = db.get_user(target_user_id)
        if not user or not user["active"]:
            raise RuntimeError("Target user is not active")
        if target_user_id not in self.hub.online_users():
            raise RuntimeError("Target client is offline")
        if db.get_active_experiment_for_user(target_user_id):
            raise RuntimeError("Target client already has a training experiment")
        self._capture_ready_for(target_user_id)

        with self._lock:
            if self._state and self._state.get("status") in ACTIVE_STATES:
                raise RuntimeError(
                    "Model test #%s is already active" % self._state.get("test_id")
                )
            test_id = self._next_id
            self._next_id -= 1
            total_duration = int(timeline[-1]["end_sec"])
            params = {
                "baseline_dir": baseline_dir,
                "baseline_message_interval_min_sec": 1.0,
                "baseline_message_interval_max_sec": 4.0,
                "baseline_message_length_min": 8,
                "baseline_message_length_max": 80,
                "baseline_file_interval_min_sec": 3.0,
                "baseline_file_interval_max_sec": 8.0,
                "timeline": timeline,
                "run_mode": "MODEL_TEST",
                "record_pcap": False,
            }
            now = time.time()
            self._state = {
                "test_id": int(test_id),
                "target_user_id": target_user_id,
                "baseline_dir": baseline_dir,
                "timeline": list(timeline),
                "params": params,
                "status": "starting",
                "error": None,
                "request_epoch": now,
                "start_epoch": None,
                "finished_epoch": None,
                "total_duration_sec": total_duration,
                "current_phase_index": None,
                "current_phase": None,
                "results": [],
                "seen_windows": set(),
                "ignored_boundary_windows": 0,
                "finalize_after": None,
                "watchdog_epoch": now + float(total_duration) + 45.0,
            }

        sent = self.hub.send_to(
            target_user_id,
            {
                "type": "experiment_start",
                "run_id": int(test_id),
                "timeline": timeline,
                "params": params,
                "timing_source": "server",
            }
        )
        if not sent:
            with self._lock:
                self._state["status"] = "error"
                self._state["error"] = "Cannot send model test command to client"
                self._state["finished_epoch"] = time.time()
            raise RuntimeError("Cannot send model test command to client")

        collector = threading.Thread(
            target=self._collector_loop,
            args=(int(test_id),),
            name="InterchangeModelTest",
            daemon=True,
        )
        with self._lock:
            self._collector = collector
        collector.start()
        return self.snapshot()

    def _phase_for_window(self, state, window_start, window_end):
        origin = state.get("start_epoch")
        if origin is None:
            return None
        # Only score a window when the complete fixed 1-second interval belongs
        # to one scenario phase.  A boundary-crossing window is intentionally
        # ignored instead of giving the model an ambiguous expected label.
        epsilon = 1e-6
        for index, phase in enumerate(state.get("timeline") or []):
            phase_start = float(origin) + float(phase["start_sec"])
            phase_end = float(origin) + float(phase["end_sec"])
            if (float(window_start) + epsilon >= phase_start and
                    float(window_end) - epsilon <= phase_end):
                return index, phase
        return None

    def _collect_results(self, test_id):
        with self._lock:
            state = self._state
            if not state or int(state.get("test_id")) != int(test_id):
                return
            target = state.get("target_user_id")
            start_epoch = state.get("start_epoch")
            if start_epoch is None:
                return

        history = self.model.history_for(target)
        for entry in history:
            try:
                window_start = float(entry.get("window_start_epoch"))
                window_end = float(entry.get("window_end_epoch"))
            except Exception:
                continue
            key = "%.6f" % window_start
            with self._lock:
                state = self._state
                if not state or int(state.get("test_id")) != int(test_id):
                    return
                if key in state["seen_windows"]:
                    continue
                state["seen_windows"].add(key)
                origin = float(state.get("start_epoch") or 0.0)
                total = float(state.get("total_duration_sec") or 0.0)
                if window_end <= origin or window_start >= origin + total:
                    continue
                phase_info = self._phase_for_window(
                    state, window_start, window_end
                )
                if phase_info is None:
                    state["ignored_boundary_windows"] += 1
                    continue
                phase_index, phase = phase_info
                expected = str(phase.get("label") or "")
                predicted = str(entry.get("prediction") or "")
                confidence = entry.get("confidence")
                matched = expected.strip().upper() == predicted.strip().upper()
                relative = max(0.0, window_start - origin)
                state["results"].append({
                    "window_start_epoch": window_start,
                    "window_end_epoch": window_end,
                    "relative_sec": relative,
                    "phase_index": int(phase_index),
                    "expected": expected,
                    "prediction": predicted,
                    "confidence": confidence,
                    "match": bool(matched),
                })

    def _collector_loop(self, test_id):
        while True:
            self._collect_results(test_id)
            now = time.time()
            with self._lock:
                state = self._state
                if not state or int(state.get("test_id")) != int(test_id):
                    return
                status = state.get("status")
                finalize_after = state.get("finalize_after")
                watchdog_epoch = state.get("watchdog_epoch")
                if status == "finalizing" and finalize_after is not None and now >= float(finalize_after):
                    state["status"] = "completed"
                    state["finished_epoch"] = now
                    return
                if status in TERMINAL_STATES:
                    return
                if watchdog_epoch is not None and now >= float(watchdog_epoch):
                    target = state.get("target_user_id")
                    run_id = int(state.get("test_id"))
                    state["status"] = "timeout"
                    state["error"] = "Model test did not finish before watchdog timeout"
                    state["finished_epoch"] = now
                else:
                    target = None
                    run_id = None
            if target is not None:
                self.hub.send_to(
                    target,
                    {"type": "experiment_force_stop", "run_id": run_id}
                )
                return
            time.sleep(0.20)

    def handle_status(self, sender_id, msg):
        try:
            run_id = int(msg.get("run_id"))
        except Exception:
            return False
        with self._lock:
            state = self._state
            if (not state or int(state.get("test_id")) != run_id or
                    str(state.get("target_user_id")) != str(sender_id)):
                return False
            status = str(msg.get("status") or "")
            if status == "running":
                if state.get("start_epoch") is None:
                    state["start_epoch"] = time.time()
                state["status"] = "running"
            elif status == "phase":
                try:
                    state["current_phase_index"] = int(msg.get("phase_index"))
                except Exception:
                    state["current_phase_index"] = None
                state["current_phase"] = str(msg.get("label") or "")
            elif status == "completed":
                # LiveTrafficMonitor publishes a complete second only when the
                # next second begins.  Keep a short finalizing state so the
                # final inference window can still be collected.
                state["status"] = "finalizing"
                state["finalize_after"] = time.time() + 1.25
            elif status in ("stopped", "error"):
                state["status"] = status
                state["error"] = str(msg.get("error") or "") or None
                state["finished_epoch"] = time.time()
            return True

    def stop(self):
        with self._lock:
            state = self._state
            if not state:
                raise RuntimeError("No model test has been started")
            if state.get("status") not in ACTIVE_STATES:
                return self.snapshot()
            target = state.get("target_user_id")
            run_id = int(state.get("test_id"))
            state["status"] = "stopped"
            state["finished_epoch"] = time.time()
        # Release the shared client scenario slot authoritatively.  There is no
        # PCAP process to finalize for a model test.
        self.hub.send_to(
            target,
            {"type": "experiment_force_stop", "run_id": run_id}
        )
        self._collect_results(run_id)
        return self.snapshot()

    def active_phase(self, user_id, run_id, expected_label):
        with self._lock:
            state = self._state
            if (not state or int(state.get("test_id")) != int(run_id) or
                    str(state.get("target_user_id")) != str(user_id) or
                    state.get("status") != "running" or
                    state.get("start_epoch") is None):
                return None, "model test is not active"
            origin = float(state["start_epoch"])
            relative = time.time() - origin
            for phase in state.get("timeline") or []:
                start_sec = float(phase["start_sec"])
                end_sec = float(phase["end_sec"])
                if relative >= start_sec and relative < end_sec:
                    if str(phase.get("label")) != str(expected_label):
                        return None, "requested anomaly phase is not active"
                    result = dict(phase)
                    result["_relative_sec"] = relative
                    result["_run_start_epoch"] = origin
                    return result, None
        return None, "model test phase is not active"

    @staticmethod
    def _summary(results):
        scored = len(results)
        correct = sum(1 for item in results if item.get("match"))
        confidences = [
            float(item["confidence"]) for item in results
            if item.get("confidence") is not None
        ]
        by_class = {}
        for item in results:
            name = str(item.get("expected") or "-")
            entry = by_class.setdefault(name, {"total": 0, "correct": 0})
            entry["total"] += 1
            if item.get("match"):
                entry["correct"] += 1
        for entry in by_class.values():
            entry["accuracy"] = (
                float(entry["correct"]) / float(entry["total"])
                if entry["total"] else None
            )
        return {
            "scored_windows": scored,
            "correct_windows": correct,
            "accuracy": float(correct) / float(scored) if scored else None,
            "average_confidence": (
                sum(confidences) / float(len(confidences))
                if confidences else None
            ),
            "by_class": by_class,
        }

    def snapshot(self):
        with self._lock:
            state = self._state
            if not state:
                return {
                    "status": "idle",
                    "progress_percent": 0,
                    "results": [],
                    "summary": self._summary([]),
                }
            start_epoch = state.get("start_epoch")
            total = max(1, int(state.get("total_duration_sec") or 1))
            status = str(state.get("status") or "idle")
            now = time.time()
            elapsed = 0.0 if start_epoch is None else max(0.0, now - float(start_epoch))
            if status == "completed":
                progress = 100
            elif status in ACTIVE_STATES:
                progress = min(99, max(0, int((elapsed / float(total)) * 100.0)))
            else:
                progress = min(100, max(0, int((elapsed / float(total)) * 100.0)))

            current_phase = state.get("current_phase")
            current_phase_index = state.get("current_phase_index")
            if start_epoch is not None and status in ACTIVE_STATES:
                relative = min(max(0.0, elapsed), float(total))
                for index, phase in enumerate(state.get("timeline") or []):
                    if relative >= float(phase["start_sec"]) and relative < float(phase["end_sec"]):
                        current_phase = str(phase.get("label") or "")
                        current_phase_index = index
                        break

            results = [dict(item) for item in state.get("results") or []]
            latest = dict(results[-1]) if results else None
            return {
                "test_id": int(state.get("test_id")),
                "target_user_id": state.get("target_user_id"),
                "status": status,
                "error": state.get("error"),
                "start_epoch": start_epoch,
                "finished_epoch": state.get("finished_epoch"),
                "total_duration_sec": int(state.get("total_duration_sec") or 0),
                "elapsed_sec": min(float(total), elapsed),
                "remaining_sec": max(0.0, float(total) - elapsed),
                "progress_percent": progress,
                "current_phase": current_phase,
                "current_phase_index": current_phase_index,
                "timeline": [dict(item) for item in state.get("timeline") or []],
                "latest": latest,
                "ignored_boundary_windows": int(state.get("ignored_boundary_windows") or 0),
                "results": results[-500:],
                "summary": self._summary(results),
                "record_pcap": False,
                "record_csv": False,
            }
