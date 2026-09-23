import argparse
import json
import os
import queue
import shutil
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import auth_protocol
import db
from server_core import RealtimeHub
from pcap_manager import PcapCaptureError, PcapManager
from model_runtime import ModelLoadError, ModelManager
from live_monitor import LiveTrafficMonitor
from model_test import ModelTestManager
from transfer_utils import CHUNK_SIZE, make_folder_zip, safe_extract, sha256_file
from py_compat import safe_unlink
from server_config import (
    default_config_path, is_server_config_complete, load_server_config
)

APP = {
    "hub": None,
    "dest": None,
    "spool": None,
    "events": None,
    "pcap": None,
    "model_manager": None,
    "traffic_monitor": None,
    "model_test_manager": None,
    "experiment_lock": threading.RLock(),
    "experiment_timers": {},
}


def json_response(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def add_file_status(sender, recipient, text, transfer_id, status):
    mid = db.add_message(
        sender, recipient, text, "file_status",
        {"transfer_id": transfer_id, "status": status}
    )
    row = db.get_message(mid)
    return mid, row["created_at"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/health":
            return json_response(self, {"status": "ok"})
        if parsed.path == "/experiment/request":
            return self.handle_experiment_request()
        if parsed.path == "/experiment/small-stream":
            return self.handle_experiment_small_stream()
        if parsed.path == "/users":
            return self.handle_users()
        if parsed.path == "/admin/model/monitor":
            return self.handle_admin_model_monitor()
        if parsed.path == "/admin/model/client":
            return self.handle_admin_model_client(q)
        if parsed.path == "/admin/model/test/status":
            return self.handle_admin_model_test_status()
        if parsed.path == "/history":
            return self.handle_history(q)
        if parsed.path == "/tasks":
            return self.handle_tasks(q)
        if parsed.path == "/download":
            return self.handle_download(q)
        return json_response(self, {"error": "not found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/upload":
            return self.handle_upload()
        if parsed.path == "/complete":
            return self.handle_complete()
        if parsed.path == "/experiment/payload":
            return self.handle_experiment_payload()
        if parsed.path == "/admin/experiment/start":
            return self.handle_admin_experiment_start()
        if parsed.path == "/admin/experiment/stop":
            return self.handle_admin_experiment_stop()
        if parsed.path == "/admin/experiment/delete":
            return self.handle_admin_experiment_delete()
        if parsed.path == "/admin/model/load":
            return self.handle_admin_model_load()
        if parsed.path == "/admin/model/unload":
            return self.handle_admin_model_unload()
        if parsed.path == "/admin/model/test/start":
            return self.handle_admin_model_test_start()
        if parsed.path == "/admin/model/test/stop":
            return self.handle_admin_model_test_stop()
        return json_response(self, {"error": "not found"}, 404)

    def handle_users(self):
        if not self._is_local_admin():
            user_id = self.headers.get("X-Auth-User-ID")
            if not self._authenticated_user(user_id):
                return json_response(
                    self,
                    {"error": "unauthorized"},
                    403
                )
        online = APP["hub"].online_users()
        result = []
        for row in db.list_users():
            uid = row["user_id"]
            result.append({
                "user_id": uid,
                "name": row["name"],
                "role": row["role"],
                "online": True if uid == "server" else uid in online
            })
        json_response(self, {"users": result})

    def handle_history(self, q):
        user_id = (q.get("user_id") or [None])[0]
        peer = (q.get("peer") or [None])[0]
        limit = (q.get("limit") or ["50"])[0]
        if not user_id or not peer:
            return json_response(self, {"error": "user_id and peer required"}, 400)
        try:
            limit = max(1, min(int(limit), 200))
        except ValueError:
            limit = 50

        extra = auth_protocol.canonical_extra([peer, limit])
        if not self._authenticated_user(user_id, extra):
            return json_response(self, {"error": "unauthorized"}, 403)

        rows = db.get_history(user_id, peer, limit)
        messages = []
        for r in rows:
            messages.append({
                "id": r["id"],
                "from": r["sender_id"],
                "to": r["recipient_id"],
                "type": r["message_type"],
                "text": r["text"],
                "created_at": r["created_at"]
            })
        json_response(self, {"messages": messages})

    def handle_tasks(self, q):
        user_id = (q.get("user_id") or [None])[0]
        if not user_id:
            return json_response(self, {"error": "user_id required"}, 400)
        if not self._authenticated_user(user_id):
            return json_response(self, {"error": "unauthorized"}, 403)
        rows = db.list_waiting_transfers(user_id)
        json_response(self, {"tasks": [dict(r) for r in rows]})

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 1024 * 1024:
            raise ValueError("invalid request body length")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _is_local_admin(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _authenticated_user(self, user_id, extra=""):
        if not user_id:
            return None
        return APP["hub"].verify_http_session(
            user_id,
            self.headers.get("X-Session-ID"),
            self.headers.get("X-Request-Nonce"),
            self.headers.get("X-Request-MAC"),
            self.command,
            urllib.parse.urlparse(self.path).path,
            extra,
            self.client_address[0]
        )

    def _active_timeline_phase(self, expected_label):
        user_id = self.headers.get("X-User-ID")
        run_id = self.headers.get("X-Experiment-Run-ID")

        if not user_id:
            return None, "X-User-ID required"

        try:
            run_id = int(run_id)
        except Exception:
            return None, "X-Experiment-Run-ID required"

        extra = auth_protocol.canonical_extra([run_id])
        user = self._authenticated_user(user_id, extra)
        if not user:
            return None, "unauthorized user"

        run = db.get_experiment_run(run_id)
        if not run:
            manager = APP.get("model_test_manager")
            if manager is not None:
                return manager.active_phase(user_id, run_id, expected_label)
            return None, "experiment run is not active"
        if (run["target_user_id"] != user_id or
                run["status"] not in ("starting", "running")):
            return None, "experiment run is not active"

        if run["anomaly_type"] != "TIMELINE":
            return None, "timeline experiment required"

        start_epoch = run["experiment_start_epoch"]
        if start_epoch is None:
            return None, "experiment start time is not available"

        try:
            run_params = json.loads(run["params_json"] or "{}")
            timeline = run_params.get("timeline") or []
            relative = time.time() - float(start_epoch)

            for phase in timeline:
                start_sec = float(phase["start_sec"])
                end_sec = float(phase["end_sec"])
                if relative >= start_sec and relative < end_sec:
                    if phase["label"] != expected_label:
                        return None, "requested anomaly phase is not active"

                    result = dict(phase)
                    result["_relative_sec"] = relative
                    result["_run_start_epoch"] = float(start_epoch)
                    return result, None
        except Exception:
            return None, "invalid experiment timeline"

        return None, "experiment phase is not active"

    def handle_experiment_request(self):
        phase, error = self._active_timeline_phase(
            "HIGH_REQUEST_RATE"
        )
        if phase is None:
            return json_response(self, {"error": error}, 403)



        body = b"OK"
        self.close_connection = False
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "keep-alive")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def handle_experiment_small_stream(self):
        phase, error = self._active_timeline_phase(
            "HIGH_FREQUENCY_SMALL_TRANSFERS"
        )
        if phase is None:
            return json_response(self, {"error": error}, 403)

        params = phase.get("params") or {}

        try:
            rate = float(params.get("transfers_per_sec", 5.0))
        except Exception:
            rate = 5.0
        rate = max(0.5, min(20.0, rate))

        try:
            payload_size = int(params.get("payload_bytes", 512))
        except Exception:
            payload_size = 512
        payload_size = max(16, min(65536, payload_size))

        phase_end_epoch = (
            phase["_run_start_epoch"] + float(phase["end_sec"])
        )
        remaining = max(0.0, phase_end_epoch - time.time())
        if remaining <= 0:
            return json_response(
                self, {"error": "small-transfer phase already ended"}, 403
            )




        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Experiment-Payload-Bytes", str(payload_size))
        self.send_header("X-Experiment-Transfers-Per-Sec", str(rate))
        self.end_headers()

        payload = b"X" * payload_size
        interval = 1.0 / rate
        end_monotonic = time.monotonic() + remaining
        next_send = time.monotonic()

        while time.monotonic() < end_monotonic:
            try:
                self.wfile.write(payload)
                self.wfile.flush()
            except Exception:
                break

            next_send += interval
            delay = next_send - time.monotonic()
            if delay > 0:
                time.sleep(delay)

    def handle_experiment_payload(self):
        user_id = self.headers.get("X-User-ID")
        run_id = self.headers.get("X-Experiment-Run-ID")
        length = int(self.headers.get("Content-Length", "0"))

        if not user_id:
            return json_response(self, {"error": "X-User-ID required"}, 400)
        try:
            run_id = int(run_id)
        except Exception:
            return json_response(
                self, {"error": "X-Experiment-Run-ID required"}, 400
            )
        if length < 0 or length > 65536:
            return json_response(self, {"error": "payload too large"}, 413)

        extra = auth_protocol.canonical_extra([run_id, length])
        user = self._authenticated_user(user_id, extra)
        if not user:
            return json_response(self, {"error": "unauthorized"}, 403)

        run = db.get_experiment_run(run_id)
        if (not run or run["target_user_id"] != user_id or
                run["status"] not in ("starting", "running")):
            return json_response(
                self, {"error": "experiment run is not active"}, 403
            )

        allowed_small_transfer = False

        if run["anomaly_type"] == "HIGH_FREQUENCY_SMALL_TRANSFERS":
            allowed_small_transfer = True

        elif run["anomaly_type"] == "TIMELINE":
            try:
                params = json.loads(run["params_json"] or "{}")
                timeline = params.get("timeline") or []
                start_epoch = run["experiment_start_epoch"]
                if start_epoch is not None:
                    relative = time.time() - float(start_epoch)
                    for phase in timeline:
                        if (relative >= float(phase["start_sec"]) and
                                relative < float(phase["end_sec"])):
                            allowed_small_transfer = (
                                phase["label"]
                                == "HIGH_FREQUENCY_SMALL_TRANSFERS"
                            )
                            break
            except Exception:
                allowed_small_transfer = False

        if not allowed_small_transfer:
            return json_response(
                self,
                {"error": "small-transfer phase is not active"},
                403
            )

        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)

        if remaining != 0:
            return json_response(self, {"error": "incomplete payload"}, 400)

        return json_response(self, {"status": "ok", "bytes": length})

    def handle_admin_experiment_start(self):
        if not self._is_local_admin():
            return json_response(self, {"error": "local admin only"}, 403)
        try:
            data = self._read_json_body()
            target_user_id = str(data.get("target_user_id", "")).strip()
            baseline_dir = str(data.get("baseline_dir", "")).strip()
            timeline = data.get("timeline") or []
            result = start_timeline_experiment(
                target_user_id,
                baseline_dir,
                timeline
            )
            return json_response(self, result)
        except PcapCaptureError as exc:
            return json_response(self, {"error": str(exc)}, 409)
        except Exception as exc:
            return json_response(self, {"error": str(exc)}, 400)

    def handle_admin_experiment_stop(self):
        if not self._is_local_admin():
            return json_response(self, {"error": "local admin only"}, 403)
        try:
            data = self._read_json_body()
            run_id = int(data["run_id"])
            result = stop_experiment(run_id)
            return json_response(self, result)
        except Exception as exc:
            return json_response(self, {"error": str(exc)}, 400)

    def handle_admin_experiment_delete(self):
        if not self._is_local_admin():
            return json_response(self, {"error": "local admin only"}, 403)
        try:
            data = self._read_json_body()
            run_id = int(data["run_id"])
            delete_files = bool(data.get("delete_files", True))
            result = delete_experiment(run_id, delete_files=delete_files)
            return json_response(self, result)
        except Exception as exc:
            return json_response(self, {"error": str(exc)}, 400)

    def handle_admin_model_monitor(self):
        if not self._is_local_admin():
            return json_response(self, {"error": "local admin only"}, 403)
        monitor = APP.get("traffic_monitor")
        if monitor is None:
            return json_response(
                self, {"error": "live model monitor is not initialized"}, 503
            )
        try:
            return json_response(self, monitor.snapshot())
        except Exception as exc:
            return json_response(self, {"error": str(exc)}, 500)

    def handle_admin_model_client(self, q):
        if not self._is_local_admin():
            return json_response(self, {"error": "local admin only"}, 403)
        user_id = (q.get("user_id") or [None])[0]
        if not user_id:
            return json_response(self, {"error": "user_id required"}, 400)
        monitor = APP.get("traffic_monitor")
        if monitor is None:
            return json_response(
                self, {"error": "live model monitor is not initialized"}, 503
            )
        return json_response(self, monitor.client_details(user_id))

    def handle_admin_model_load(self):
        if not self._is_local_admin():
            return json_response(self, {"error": "local admin only"}, 403)
        manager = APP.get("model_manager")
        if manager is None:
            return json_response(self, {"error": "model manager is not initialized"}, 503)
        try:
            data = self._read_json_body()
            path = str(data.get("path", "")).strip()
            if not path:
                return json_response(self, {"error": "model path required"}, 400)
            result = manager.load(path)
            return json_response(self, {"status": "ok", "model": result})
        except ModelLoadError as exc:
            return json_response(self, {"error": str(exc)}, 409)
        except Exception as exc:
            return json_response(self, {"error": str(exc)}, 400)

    def handle_admin_model_unload(self):
        if not self._is_local_admin():
            return json_response(self, {"error": "local admin only"}, 403)
        manager = APP.get("model_manager")
        if manager is None:
            return json_response(self, {"error": "model manager is not initialized"}, 503)
        manager.unload()
        return json_response(self, {"status": "ok", "model": manager.status()})

    def handle_admin_model_test_status(self):
        if not self._is_local_admin():
            return json_response(self, {"error": "local admin only"}, 403)
        manager = APP.get("model_test_manager")
        if manager is None:
            return json_response(self, {"error": "model test manager is not initialized"}, 503)
        return json_response(self, manager.snapshot())

    def handle_admin_model_test_start(self):
        if not self._is_local_admin():
            return json_response(self, {"error": "local admin only"}, 403)
        manager = APP.get("model_test_manager")
        if manager is None:
            return json_response(self, {"error": "model test manager is not initialized"}, 503)
        try:
            data = self._read_json_body()
            target_user_id = str(data.get("target_user_id", "")).strip()
            baseline_dir = str(data.get("baseline_dir", "")).strip()
            timeline = _normalize_timeline(data.get("timeline") or [])
            result = manager.start(target_user_id, baseline_dir, timeline)
            return json_response(self, result)
        except Exception as exc:
            return json_response(self, {"error": str(exc)}, 400)

    def handle_admin_model_test_stop(self):
        if not self._is_local_admin():
            return json_response(self, {"error": "local admin only"}, 403)
        manager = APP.get("model_test_manager")
        if manager is None:
            return json_response(self, {"error": "model test manager is not initialized"}, 503)
        try:
            return json_response(self, manager.stop())
        except Exception as exc:
            return json_response(self, {"error": str(exc)}, 400)

    def handle_upload(self):
        sender = self.headers.get("X-Sender-ID")
        recipient = self.headers.get("X-Recipient-ID")
        raw_name = self.headers.get("X-Item-Name")
        item_name = urllib.parse.unquote(raw_name) if raw_name else None
        item_type = self.headers.get("X-Item-Type", "file")
        length = int(self.headers.get("Content-Length", "0"))
        experiment_run_raw = self.headers.get("X-Experiment-Run-ID")
        experiment_run_id = None
        if experiment_run_raw not in (None, ""):
            try:
                experiment_run_id = int(experiment_run_raw)
            except Exception:
                return json_response(
                    self, {"error": "invalid experiment run id"}, 400
                )

        if not sender or not recipient or not item_name or item_type not in ("file", "folder"):
            return json_response(self, {"error": "invalid upload metadata"}, 400)
        encoded_name = self.headers.get("X-Item-Name") or ""
        declared_digest = str(self.headers.get("X-Body-SHA256") or "").lower()
        extra_values = [
            recipient, encoded_name, item_type, length, declared_digest
        ]
        if experiment_run_id is not None:
            extra_values.append(experiment_run_id)
        extra = auth_protocol.canonical_extra(extra_values)
        if not self._authenticated_user(sender, extra):
            return json_response(self, {"error": "unauthorized"}, 403)
        if not db.get_user(recipient):
            return json_response(self, {"error": "unknown user"}, 404)

        # Quiet experiment uploads exercise the same authenticated HTTP body
        # path as normal file traffic but do not create transfers, chat rows or
        # permanent files.  Positive ids must match an active PCAP experiment;
        # negative ids are in-memory live model tests.
        if experiment_run_id is not None:
            if recipient != "server":
                return json_response(
                    self, {"error": "experiment upload must target server"}, 403
                )
            if experiment_run_id >= 0:
                run = db.get_experiment_run(experiment_run_id)
                if (not run or run["target_user_id"] != sender or
                        run["status"] not in ("starting", "running")):
                    return json_response(
                        self, {"error": "experiment run is not active"}, 403
                    )

        fd, tmp_name = tempfile.mkstemp(
            prefix="upload_",
            suffix=".zip" if item_type == "folder" else ".bin",
            dir=str(APP["spool"])
        )
        os.close(fd)
        tmp_path = Path(tmp_name)

        remaining = length
        with tmp_path.open("wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)

        if remaining != 0:
            safe_unlink(tmp_path)
            return json_response(self, {"error": "incomplete upload"}, 400)

        digest = sha256_file(tmp_path)
        if not declared_digest or digest.lower() != declared_digest:
            safe_unlink(tmp_path)
            return json_response(self, {"error": "SHA-256 mismatch"}, 400)

        if experiment_run_id is not None:
            safe_unlink(tmp_path)
            return json_response(self, {
                "status": "experiment_received",
                "bytes": length,
                "experiment_run_id": experiment_run_id,
            })

        if recipient == "server":
            try:
                if item_type == "file":
                    final = APP["dest"] / item_name
                    final.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(tmp_path), str(final))
                else:
                    safe_extract(tmp_path, APP["dest"])
                    final = APP["dest"] / item_name
                    safe_unlink(tmp_path)

                tid = db.add_transfer(
                    sender, recipient, item_name, item_type, str(final),
                    stored_archive=False, delete_after=False, sha256=digest
                )
                db.complete_transfer(tid, "server")
                text = f"{item_name}: received by server"
                mid, created = add_file_status(
                    sender, "server", text, tid, "received"
                )
                APP["events"].put(("file_received", sender, item_name, str(final)))
                APP["hub"].notify_transfer_status(
                    sender, tid, "received", text,
                    peer="server", message_id=mid, created_at=created,
                    sender_id=sender, recipient_id="server"
                )
                return json_response(self, {
                    "status": "received",
                    "transfer_id": tid,
                    "message_id": mid,
                    "created_at": created
                })
            except Exception:
                safe_unlink(tmp_path)
                raise

        tid = db.add_transfer(
            sender, recipient, item_name, item_type, str(tmp_path),
            stored_archive=(item_type == "folder"),
            delete_after=True, sha256=digest
        )
        text = f"{item_name}: sent"
        mid, created = add_file_status(
            sender, recipient, text, tid, "uploaded"
        )


        APP["hub"].notify_transfer_status(
            sender, tid, "uploaded", text,
            peer=recipient, message_id=mid, created_at=created,
            sender_id=sender, recipient_id=recipient
        )
        APP["hub"].notify_transfer_status(
            recipient, tid, "uploaded", text,
            peer=sender, message_id=mid, created_at=created,
            sender_id=sender, recipient_id=recipient
        )


        APP["hub"].notify_task(recipient, tid)
        APP["events"].put(("upload", sender, recipient, item_name))
        json_response(self, {
            "status": "uploaded",
            "transfer_id": tid,
            "message_id": mid,
            "created_at": created
        })

    def handle_download(self, q):
        transfer_id = (q.get("id") or [None])[0]
        user_id = (q.get("user_id") or [None])[0]
        if not transfer_id or not user_id:
            return json_response(self, {"error": "id and user_id required"}, 400)
        try:
            transfer_id = int(transfer_id)
        except ValueError:
            return json_response(self, {"error": "invalid id"}, 400)

        extra = auth_protocol.canonical_extra([transfer_id])
        if not self._authenticated_user(user_id, extra):
            return json_response(self, {"error": "unauthorized"}, 403)

        row = db.get_transfer(transfer_id)
        if not row or row["recipient_id"] != user_id or row["status"] == "completed":
            return json_response(self, {"error": "transfer unavailable"}, 404)

        source = Path(row["source_path"])
        if not source.exists():
            return json_response(self, {"error": "source missing"}, 404)

        temp_zip = None
        try:
            if row["item_type"] == "folder" and not row["stored_archive"]:
                temp_zip = make_folder_zip(source)
                send_path = temp_zip
            else:
                send_path = source

            digest = row["sha256"] or sha256_file(send_path)
            size = send_path.stat().st_size

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/zip" if row["item_type"] == "folder"
                else "application/octet-stream"
            )
            self.send_header("Content-Length", str(size))
            self.send_header("X-SHA256", digest)
            self.send_header("X-Item-Name", urllib.parse.quote(row["item_name"], safe=""))
            self.send_header("X-Item-Type", row["item_type"])
            self.end_headers()

            with send_path.open("rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        finally:
            if temp_zip:
                safe_unlink(temp_zip)

    def handle_complete(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            transfer_id = int(data["id"])
            user_id = data["user_id"]
        except Exception:
            return json_response(self, {"error": "invalid json"}, 400)

        extra = auth_protocol.canonical_extra([transfer_id])
        if not self._authenticated_user(user_id, extra):
            return json_response(self, {"error": "unauthorized"}, 403)

        row = db.complete_transfer(transfer_id, user_id)
        if not row:
            return json_response(self, {"error": "transfer not found"}, 404)

        item_name = row["item_name"]
        sender = row["sender_id"]
        recipient = row["recipient_id"]
        text = f"{item_name}: received"




        mid, created = add_file_status(
            recipient, sender, text, transfer_id, "received"
        )

        canonical_sender = recipient
        canonical_recipient = sender

        APP["hub"].notify_transfer_status(
            sender, transfer_id, "received", text,
            peer=recipient, message_id=mid, created_at=created,
            sender_id=canonical_sender, recipient_id=canonical_recipient
        )
        APP["hub"].notify_transfer_status(
            recipient, transfer_id, "received", text,
            peer=sender, message_id=mid, created_at=created,
            sender_id=canonical_sender, recipient_id=canonical_recipient
        )
        APP["events"].put(("transfer_complete", sender, recipient, item_name))

        if row["delete_after"]:
            try:
                safe_unlink(Path(row["source_path"]))
            except Exception:
                pass

        json_response(self, {
            "status": "ok",
            "message_id": mid,
            "created_at": created,
            "sender_id": canonical_sender,
            "recipient_id": canonical_recipient
        })

    def log_message(self, fmt, *args):
        pass


DATASET_WINDOW_SEC = 1


ALLOWED_TIMELINE_LABELS = {
    "NORMAL",
    "HIGH_REQUEST_RATE",
    "FREQUENT_RECONNECT",
    "HIGH_FREQUENCY_SMALL_TRANSFERS",
}


def _normalize_timeline(raw_timeline):
    if not isinstance(raw_timeline, list) or not raw_timeline:
        raise RuntimeError("Timeline must contain at least one phase")

    normalized = []
    previous_end = 0

    for index, raw in enumerate(raw_timeline):
        if not isinstance(raw, dict):
            raise RuntimeError("Timeline phase #%d is invalid" % (index + 1))

        try:
            raw_start = float(raw.get("start_sec"))
            raw_end = float(raw.get("end_sec"))
            if not raw_start.is_integer() or not raw_end.is_integer():
                raise ValueError("fractional second")
            start_sec = int(raw_start)
            end_sec = int(raw_end)
        except Exception:
            raise RuntimeError(
                "Timeline phase #%d start/end must be whole seconds"
                % (index + 1)
            )

        label = str(raw.get("label", "")).strip().upper()
        params = raw.get("params") or {}
        if not isinstance(params, dict):
            raise RuntimeError(
                "Timeline phase #%d parameters must be JSON object"
                % (index + 1)
            )

        if label not in ALLOWED_TIMELINE_LABELS:
            raise RuntimeError(
                "Timeline phase #%d has unsupported label" % (index + 1)
            )
        if start_sec != previous_end:
            raise RuntimeError(
                "Timeline must be continuous: phase #%d must start at %d"
                % (index + 1, previous_end)
            )
        if end_sec <= start_sec:
            raise RuntimeError(
                "Timeline phase #%d end must be greater than start"
                % (index + 1)
            )
        normalized.append({
            "start_sec": start_sec,
            "end_sec": end_sec,
            "label": label,
            "params": params,
        })
        previous_end = end_sec

    if normalized[0]["start_sec"] != 0:
        raise RuntimeError("Timeline must start at 0 seconds")
    if previous_end > 3600:
        raise RuntimeError("Timeline cannot exceed 3600 seconds")

    return normalized


def _dataset_duration_for_run(row, planned_duration):
    """Return complete one-second windows safe for dataset parsing."""
    planned_duration = max(0, int(planned_duration or 0))
    status = str(row["status"] or "")
    if status not in ("completed", "stopped", "error", "timeout"):
        return planned_duration

    started = row["experiment_start_epoch"]
    finished = row["experiment_end_epoch"]
    if started is None or finished is None:
        return planned_duration if status == "completed" else 0

    try:
        elapsed = max(0.0, float(finished) - float(started))
    except Exception:
        return planned_duration if status == "completed" else 0

    # Completed runs are defined by the planned whole-second timeline.
    if status == "completed":
        return planned_duration

    # Stopped/error runs keep only complete seconds; a trailing partial second
    # would otherwise make count/rate metrics incomparable with normal rows.
    return min(planned_duration, int(elapsed))


def _write_run_metadata(run_id):
    row = db.get_experiment_run(run_id)
    if not row or not row["pcap_path"] or not APP.get("pcap"):
        return

    try:
        params = json.loads(row["params_json"] or "{}")
    except Exception:
        params = {}

    user = db.get_user(row["target_user_id"])
    timeline = params.get("timeline") or []
    total_duration = timeline[-1]["end_sec"] if timeline else 0

    APP["pcap"].write_metadata(
        row["pcap_path"],
        {
            "schema_version": 4,
            "clock_source": "server",
            "timing_model": "server_epoch_client_monotonic",
            "run_id": row["id"],
            "experiment_id": row["id"],
            "target_user_id": row["target_user_id"],
            "target_client_ip": user["ip"] if user else None,
            "experiment_type": "TIMELINE",
            "timeline": timeline,
            "baseline": {
                "baseline_dir": params.get("baseline_dir"),
                "message_interval_min_sec": params.get(
                    "baseline_message_interval_min_sec"
                ),
                "message_interval_max_sec": params.get(
                    "baseline_message_interval_max_sec"
                ),
                "message_length_min": params.get(
                    "baseline_message_length_min"
                ),
                "message_length_max": params.get(
                    "baseline_message_length_max"
                ),
                "file_interval_min_sec": params.get(
                    "baseline_file_interval_min_sec"
                ),
                "file_interval_max_sec": params.get(
                    "baseline_file_interval_max_sec"
                ),
            },
            "window_sec": DATASET_WINDOW_SEC,
            "planned_duration_sec": total_duration,
            "dataset_duration_sec": _dataset_duration_for_run(
                row, total_duration
            ),
            "total_duration_sec": total_duration,
            "server_http_port": APP["pcap"].http_port,
            "server_socket_port": APP["pcap"].socket_port,
            "status": row["status"],
            "pcap_path": row["pcap_path"],
            "capture_backend": row["capture_backend"],
            "capture_interface": row["capture_interface"],
            "error": row["error"],
            "db_started_at": row["started_at"],
            "db_finished_at": row["finished_at"],
            "experiment_start_epoch": row["experiment_start_epoch"],
            "experiment_end_epoch": row["experiment_end_epoch"],
        }
    )


def _finish_experiment(run_id, status, error=None, end_epoch=None):
    if end_epoch is None:
        end_epoch = time.time()

    with APP["experiment_lock"]:
        row = db.get_experiment_run(run_id)
        if not row:
            return
        if row["status"] in ("completed", "stopped", "error", "timeout"):
            return

        timer = APP["experiment_timers"].pop(int(run_id), None)
        if timer:
            try:
                timer.cancel()
            except Exception:
                pass

        if APP.get("pcap"):
            APP["pcap"].stop(run_id)

        db.update_experiment_run(
            run_id,
            status=status,
            error=error,
            experiment_end_epoch=end_epoch,
            finish=True
        )
        _write_run_metadata(run_id)
        APP["events"].put(("experiment_finished", int(run_id), status, error))


def _experiment_watchdog(run_id):
    row = db.get_experiment_run(run_id)
    if not row:
        return
    if row["status"] in ("completed", "stopped", "error", "timeout"):
        return

    APP["hub"].send_to(
        row["target_user_id"],
        {"type": "experiment_stop", "run_id": int(run_id)}
    )
    _finish_experiment(
        run_id,
        "timeout",
        "Experiment did not finish before the watchdog timeout",
        end_epoch=time.time()
    )


def handle_experiment_status(sender_id, msg):
    try:
        run_id = int(msg.get("run_id"))
    except Exception:
        return

    row = db.get_experiment_run(run_id)
    if not row:
        manager = APP.get("model_test_manager")
        if manager is not None and manager.handle_status(sender_id, msg):
            return
        return
    if row["target_user_id"] != sender_id:
        return

    status = msg.get("status")
    error = msg.get("error")

    if status == "running":




        db.update_experiment_run(
            run_id,
            status="running"
        )
        _write_run_metadata(run_id)

    elif status == "phase":



        APP["events"].put((
            "experiment_phase",
            int(run_id),
            msg.get("phase_index"),
            msg.get("label"),
            time.time()
        ))

    elif status in ("completed", "stopped", "error"):

        _finish_experiment(
            run_id,
            status,
            error=error,
            end_epoch=time.time()
        )


def start_timeline_experiment(target, baseline_dir, raw_timeline):
    if not target:
        raise RuntimeError("Target client is required")
    if not str(baseline_dir or "").strip():
        raise RuntimeError("Client baseline folder path is required")

    timeline = _normalize_timeline(raw_timeline)

    user = db.get_user(target)
    if not user or not user["active"]:
        raise RuntimeError("Target user is not active")
    if not user["ip"]:
        raise RuntimeError("Target user must have a registered IP")
    if target not in APP["hub"].online_users():
        raise RuntimeError("Target client is offline")

    active = db.get_active_experiment_for_user(target)
    if active:
        raise RuntimeError(
            "Target client already has active experiment run #%s"
            % active["id"]
        )
    model_test = APP.get("model_test_manager")
    if model_test is not None and model_test.active_for_user(target):
        raise RuntimeError("Target client already has an active model test")

    params = {
        "baseline_dir": str(baseline_dir).strip(),
        "baseline_message_interval_min_sec": 1.0,
        "baseline_message_interval_max_sec": 4.0,
        "baseline_message_length_min": 8,
        "baseline_message_length_max": 80,
        "baseline_file_interval_min_sec": 3.0,
        "baseline_file_interval_max_sec": 8.0,
        "timeline": timeline,
    }

    total_duration = int(timeline[-1]["end_sec"])
    run_id = db.create_experiment_run(
        None,
        target,
        "TIMELINE",
        params
    )

    try:
        capture = APP["pcap"].start(
            run_id,
            target,
            user["ip"],
            "TIMELINE"
        )
        db.update_experiment_run(
            run_id,
            pcap_path=capture["pcap_path"],
            capture_backend=capture["backend"],
            capture_interface=capture["interface"]
        )






        server_start_epoch = time.time()
        db.update_experiment_run(
            run_id,
            experiment_start_epoch=server_start_epoch
        )
        _write_run_metadata(run_id)

        sent = APP["hub"].send_to(
            target,
            {
                "type": "experiment_start",
                "run_id": int(run_id),
                "timeline": timeline,
                "params": params,
                "timing_source": "server"
            }
        )
        if not sent:
            raise RuntimeError("Cannot send experiment command to client")



        timer = threading.Timer(
            total_duration + 150.0,
            _experiment_watchdog,
            args=(int(run_id),)
        )
        timer.daemon = True
        APP["experiment_timers"][int(run_id)] = timer
        timer.start()

        APP["events"].put(
            ("experiment_started", int(run_id), target, "TIMELINE")
        )
        return {
            "status": "starting",
            "run_id": int(run_id),
            "pcap_path": capture["pcap_path"],
            "capture_interface": capture["interface"],
            "capture_backend": capture["backend"],
            "total_duration_sec": total_duration
        }

    except Exception as exc:
        try:
            if APP.get("pcap"):
                APP["pcap"].stop(run_id)
        except Exception:
            pass
        db.update_experiment_run(
            run_id,
            status="error",
            error=str(exc),
            experiment_end_epoch=time.time(),
            finish=True
        )
        _write_run_metadata(run_id)
        raise


def stop_experiment(run_id):
    """Stop an experiment authoritatively from the server side.

    Older builds waited indefinitely for the client to acknowledge the stop.
    If the client worker was stuck in I/O, the run remained in ``stopping``
    and also kept the PCAP capture alive.  The server is the owner of the
    experiment record, so an admin stop now finalizes it immediately after
    sending the cooperative stop command to the client.
    """
    row = db.get_experiment_run(run_id)
    if not row:
        raise RuntimeError("Experiment run not found")

    if row["status"] not in ("starting", "running", "stopping"):
        return {"status": row["status"], "run_id": int(run_id)}

    db.update_experiment_run(run_id, status="stopping")
    client_notified = APP["hub"].send_to(
        row["target_user_id"],
        {"type": "experiment_stop", "run_id": int(run_id)}
    )

    # Do not wait for a possibly wedged client.  This also stops the capture,
    # cancels the watchdog and releases the DB active-run slot immediately.
    _finish_experiment(
        run_id,
        "stopped",
        end_epoch=time.time()
    )
    return {
        "status": "stopped",
        "run_id": int(run_id),
        "client_notified": bool(client_notified)
    }


def _experiment_artifact_paths(row):
    if not row or not row["pcap_path"]:
        return []
    pcap_path = Path(str(row["pcap_path"]))
    return [
        pcap_path,
        pcap_path.with_suffix(".json"),
        pcap_path.with_suffix(".json.tmp"),
        pcap_path.with_suffix(".capture.log"),
    ]


def delete_experiment(run_id, delete_files=True):
    """Force-stop and remove an experiment, including a hung active run.

    The client receives a force-stop/reset command, the local packet capture
    is terminated, the watchdog is cancelled, and the DB row is deleted.
    By default the partial PCAP/metadata/capture log are removed as well.
    """
    run_id = int(run_id)
    deleted_files = []

    with APP["experiment_lock"]:
        row = db.get_experiment_run(run_id)
        if not row:
            raise RuntimeError("Experiment run not found")

        timer = APP["experiment_timers"].pop(run_id, None)
        if timer:
            try:
                timer.cancel()
            except Exception:
                pass

        active = row["status"] in ("starting", "running", "stopping")
        client_notified = False
        if active and APP.get("hub"):
            client_notified = APP["hub"].send_to(
                row["target_user_id"],
                {"type": "experiment_force_stop", "run_id": run_id}
            )

        if APP.get("pcap"):
            try:
                APP["pcap"].stop(run_id)
            except Exception:
                # Deletion must still succeed even when a stale capture entry
                # or OS-level capture process cannot be queried cleanly.
                pass

        artifact_paths = _experiment_artifact_paths(row) if delete_files else []
        db.delete_experiment_run(run_id)

    # Remove files only after the DB row is gone, so a late client status can
    # no longer recreate metadata for this deleted run.
    for path in artifact_paths:
        try:
            if path.exists() and path.is_file():
                path.unlink()
                deleted_files.append(str(path))
        except Exception:
            # A file locked by an external viewer/capture process should not
            # make the run undeletable.  It can be cleaned manually later.
            pass

    if APP.get("events") is not None:
        APP["events"].put(("experiment_deleted", run_id))
    return {
        "status": "deleted",
        "run_id": run_id,
        "client_notified": bool(client_notified),
        "deleted_files": deleted_files,
    }


def create_server_transfer(recipient_id: str, path: str):
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    item_type = "folder" if source.is_dir() else "file"
    tid = db.add_transfer(
        "server", recipient_id, source.name, item_type, str(source),
        stored_archive=False, delete_after=False
    )
    text = f"{source.name}: sent by server"
    mid, created = add_file_status(
        "server", recipient_id, text, tid, "waiting"
    )
    APP["hub"].notify_task(recipient_id, tid)
    APP["hub"].notify_transfer_status(
        recipient_id, tid, "waiting", text,
        peer="server", message_id=mid, created_at=created,
        sender_id="server", recipient_id=recipient_id
    )
    return tid


def start_http(port):
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    APP["events"].put(("status", f"HTTP :{port} started"))
    return server


def run_gui(config_path, app=None):
    from qt_compat import (
        QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget,
        QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
        QPushButton, QTimer, QVBoxLayout, QWidget, Qt, app_exec, QDialog
    )
    from server_setup import ServerSetupDialog, dialog_exec

    class ServerWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Interchange Server")
            self.resize(760, 520)
            self.current_peer = None

            settings_menu = self.menuBar().addMenu("Settings")
            settings_action = settings_menu.addAction("Server settings...")
            settings_action.triggered.connect(self.open_settings)

            central = QWidget()
            self.setCentralWidget(central)
            layout = QVBoxLayout(central)

            self.status = QLabel("Server running")
            layout.addWidget(self.status)

            body = QHBoxLayout()
            layout.addLayout(body, 1)

            self.users = QListWidget()
            self.users.setMaximumWidth(250)
            self.users.itemSelectionChanged.connect(self.select_user)
            body.addWidget(self.users)

            right = QVBoxLayout()
            body.addLayout(right, 1)

            self.chat = QPlainTextEdit()
            self.chat.setReadOnly(True)
            right.addWidget(self.chat, 1)

            row = QHBoxLayout()
            self.input = QPlainTextEdit()
            self.input.setMaximumHeight(70)
            row.addWidget(self.input, 1)
            send_btn = QPushButton("Send")
            send_btn.clicked.connect(self.send_message)
            row.addWidget(send_btn)
            right.addLayout(row)

            files = QHBoxLayout()
            b1 = QPushButton("Send file")
            b1.clicked.connect(lambda: self.send_path(False))
            b2 = QPushButton("Send folder")
            b2.clicked.connect(lambda: self.send_path(True))
            files.addWidget(b1)
            files.addWidget(b2)
            files.addStretch()
            right.addLayout(files)

            self.events = QPlainTextEdit()
            self.events.setReadOnly(True)
            self.events.setMaximumHeight(100)
            layout.addWidget(self.events)

            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(250)

            self.user_refresh_timer = QTimer(self)
            self.user_refresh_timer.timeout.connect(self.refresh_users)
            self.user_refresh_timer.start(1000)

            self.refresh_users()

        def open_settings(self):
            values = load_server_config(config_path)
            dialog = ServerSetupDialog(
                config_path, values, first_run=False, parent=self
            )
            if dialog_exec(dialog) == QDialog.Accepted:
                QMessageBox.information(
                    self, "Interchange Server",
                    "Settings saved. Restart Interchange Server to apply them."
                )

        def refresh_users(self):
            selected = self.current_peer
            online = APP["hub"].online_users()
            self.users.clear()
            for row in db.list_users():
                if row["user_id"] == "server":
                    continue
                state = "Online" if row["user_id"] in online else "Offline"
                item = QListWidgetItem(
                    f"{row['name']} ({row['user_id']}) - {state}"
                )
                item.setData(Qt.UserRole, row["user_id"])
                self.users.addItem(item)
                if selected == row["user_id"]:
                    item.setSelected(True)

        def select_user(self):
            items = self.users.selectedItems()
            if not items:
                return
            self.current_peer = items[0].data(Qt.UserRole)
            self.load_history()

        def load_history(self):
            self.chat.clear()
            if not self.current_peer:
                return
            for row in db.get_history("server", self.current_peer, 50):
                if row["message_type"] == "file_status":
                    self.chat.appendPlainText(
                        f"{row['created_at']}  [File] {row['text']}"
                    )
                else:
                    who = "Server" if row["sender_id"] == "server" else row["sender_id"]
                    self.chat.appendPlainText(
                        f"{row['created_at']}  {who}: {row['text']}"
                    )

        def send_message(self):
            if not self.current_peer:
                return
            text = self.input.toPlainText().strip()
            if not text:
                return
            mid = db.add_message("server", self.current_peer, text)
            row = db.get_message(mid)
            APP["hub"].send_to(self.current_peer, {
                "type": "message",
                "id": mid,
                "from": "server",
                "to": self.current_peer,
                "message_type": "text",
                "text": text,
                "created_at": row["created_at"]
            })
            self.input.clear()
            self.load_history()

        def send_path(self, folder):
            if not self.current_peer:
                QMessageBox.information(
                    self, "Recipient", "Select a user first."
                )
                return
            path = (
                QFileDialog.getExistingDirectory(self, "Select folder")
                if folder else
                QFileDialog.getOpenFileName(self, "Select file")[0]
            )
            if not path:
                return
            try:
                create_server_transfer(self.current_peer, path)
                self.load_history()
            except Exception as exc:
                QMessageBox.warning(self, "Error", str(exc))

        def tick(self):
            changed = False
            reload_history = False
            while True:
                try:
                    event = APP["events"].get_nowait()
                except queue.Empty:
                    break

                kind = event[0]
                if kind in ("presence", "presence_snapshot", "user_registry_changed"):
                    changed = True
                elif kind == "message":
                    payload = event[1]
                    if payload.get("from") == self.current_peer:
                        reload_history = True
                elif kind == "file_received":
                    self.events.appendPlainText(
                        f"Received from {event[1]}: {event[2]}"
                    )
                    if self.current_peer == event[1]:
                        reload_history = True
                elif kind == "transfer_complete":
                    self.events.appendPlainText(
                        f"{event[1]} -> {event[2]}: {event[3]} received"
                    )
                elif kind == "experiment_started":
                    self.events.appendPlainText(
                        "Experiment #%s started: %s / %s"
                        % (event[1], event[2], event[3])
                    )
                elif kind == "experiment_phase":
                    self.events.appendPlainText(
                        "Experiment #%s phase %s: %s"
                        % (event[1], event[2], event[3])
                    )
                elif kind == "experiment_finished":
                    self.events.appendPlainText(
                        "Experiment #%s finished: %s"
                        % (event[1], event[2])
                    )
                elif kind == "status":
                    self.events.appendPlainText(event[1])

            if changed:
                self.refresh_users()
            if reload_history:
                self.load_history()

    if app is None:
        app = QApplication([])
    w = ServerWindow()
    w.show()
    return app_exec(app)


def parse_args():
    p = argparse.ArgumentParser(description="Interchange Server")
    p.add_argument("--config", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--socket-port", type=int, default=None)
    p.add_argument("--db", default=None)
    p.add_argument("--dest", default=None)
    p.add_argument("--spool", default=None)
    p.add_argument("--gui", dest="gui", action="store_true")
    p.add_argument("--no-gui", dest="gui", action="store_false")
    p.set_defaults(gui=None)
    return p.parse_args()


def resolve_settings(cli_args, config_values):
    values = dict(config_values)
    if cli_args.port is not None:
        values["http_port"] = cli_args.port
    if cli_args.socket_port is not None:
        values["socket_port"] = cli_args.socket_port
    if cli_args.db:
        values["db_file"] = cli_args.db
    if cli_args.dest:
        values["destination_dir"] = cli_args.dest
    if cli_args.spool:
        values["spool_dir"] = cli_args.spool
    if cli_args.gui is not None:
        values["show_gui"] = cli_args.gui
    return values


def main():
    if (
        os.name == "posix"
        and hasattr(os, "geteuid")
        and os.geteuid() == 0
    ):
        raise RuntimeError(
            "Do not run Interchange Server as root. "
            "Use ./run_server.sh without sudo."
        )

    cli_args = parse_args()
    config_path = Path(cli_args.config or default_config_path()).expanduser()
    values = resolve_settings(cli_args, load_server_config(config_path))

    app = None
    if not config_path.exists() or not is_server_config_complete(values):
        if cli_args.gui is False:
            raise RuntimeError(
                "Server configuration is missing or incomplete. "
                "Run configure_server.py as the normal desktop user first."
            )

        from qt_compat import QApplication, QDialog
        from server_setup import ServerSetupDialog, dialog_exec
        app = QApplication([])
        app.setApplicationName("Interchange Server")
        dialog = ServerSetupDialog(
            config_path, values, first_run=True, parent=None
        )
        if dialog_exec(dialog) != QDialog.Accepted:
            return
        values = dialog.saved_values

    db.configure_db(values["db_file"])
    db.init_db()
    repaired = db.repair_file_status_directions()
    if repaired:
        print("Repaired legacy file_status messages:", repaired)

    APP["dest"] = Path(values["destination_dir"]).expanduser().resolve()
    APP["dest"].mkdir(parents=True, exist_ok=True)
    APP["spool"] = Path(values["spool_dir"]).expanduser().resolve()
    APP["spool"].mkdir(parents=True, exist_ok=True)
    APP["events"] = queue.Queue()
    APP["pcap"] = PcapManager(
        values["pcap_dir"],
        interface=values.get("capture_interface", "auto"),
        http_port=int(values["http_port"]),
        socket_port=int(values["socket_port"])
    )
    APP["model_manager"] = ModelManager(history_seconds=60)

    hub = RealtimeHub(
        port=int(values["socket_port"]), event_queue=APP["events"]
    )
    APP["hub"] = hub
    hub.experiment_status_callback = handle_experiment_status
    hub.start()
    APP["traffic_monitor"] = LiveTrafficMonitor(
        hub, APP["pcap"], APP["model_manager"]
    )
    APP["model_test_manager"] = ModelTestManager(
        hub, APP["model_manager"], APP["traffic_monitor"]
    )
    APP["traffic_monitor"].start()
    http = start_http(int(values["http_port"]))

    print("HTTP:   0.0.0.0:%s" % values["http_port"])
    print("Socket: 0.0.0.0:%s" % values["socket_port"])
    print("Server destination: %s" % APP["dest"])

    try:
        if values.get("show_gui", True):
            run_gui(config_path, app=app)
        else:
            threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if APP.get("traffic_monitor"):
                APP["traffic_monitor"].stop()
        except Exception:
            pass
        try:
            if APP.get("pcap"):
                APP["pcap"].stop_all()
        except Exception:
            pass
        hub.stop()
        http.shutdown()


if __name__ == "__main__":
    main()
