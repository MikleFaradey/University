"""Continuous one-second traffic aggregation for live ML inference.

No CSV files are used here.  Packet capture is streamed from the same capture
backend used by experiments (tcpdump/dumpcap), decoded by Scapy, aggregated in
RAM, and sent directly to ModelManager once per complete second.
"""
import math
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import db
from pcap_manager import PcapCaptureError
from traffic_features import (
    FIXED_WINDOW_SEC, add_packet, finalize_window, make_empty_window,
    packet_endpoints,
)


class LiveTrafficMonitor(object):
    def __init__(self, hub, pcap_manager, model_manager):
        self.hub = hub
        self.pcap = pcap_manager
        self.model = model_manager
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._capture_proc = None
        self._capture_log_handle = None
        self._capture_reader_thread = None
        self._capture_signature = None
        self._capture_state = "idle"
        self._capture_error = None
        self._capture_backend = None
        self._capture_interface = None
        self._capture_filter = None
        self._last_packet_epoch = None
        self._capture_full_from_second = None
        self._online_clients = {}
        # Keep a short capture grace after a socket disconnect.  This is
        # essential for FREQUENT_RECONNECT: stopping/restarting tcpdump for
        # every reconnect would erase the very traffic pattern the model must
        # classify.
        self._client_grace = {}
        self._client_grace_sec = 10.0
        self._buckets = {}
        self._last_packet_ts = {}
        self._last_finalized_second = {}

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._supervisor_loop,
                name="InterchangeLiveMonitor",
                daemon=True,
            )
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._stop_capture()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)

    def _client_snapshot(self):
        online = set(self.hub.online_users()) if self.hub is not None else set()
        now = time.time()
        rows = {}
        for row in db.list_all_users():
            user_id = str(row["user_id"])
            if user_id == "server" or not row["active"] or row["role"] != "client":
                continue
            rows[user_id] = {
                "user_id": user_id,
                "name": str(row["name"] or user_id),
                "ip": str(row["ip"] or "").strip(),
                "online": user_id in online,
            }

        with self._lock:
            for user_id, item in rows.items():
                if item["online"]:
                    self._client_grace[user_id] = {
                        "last_online": now,
                        "item": dict(item),
                    }
            for user_id in list(self._client_grace.keys()):
                entry = self._client_grace[user_id]
                if user_id not in rows:
                    self._client_grace.pop(user_id, None)
                    continue
                if now - float(entry.get("last_online") or 0.0) > self._client_grace_sec:
                    self._client_grace.pop(user_id, None)

            result = {}
            for user_id, item in rows.items():
                if item["online"]:
                    result[user_id] = dict(item)
                    continue
                entry = self._client_grace.get(user_id)
                if entry is not None:
                    retained = dict(entry.get("item") or item)
                    retained["online"] = False
                    result[user_id] = retained
        return result

    @staticmethod
    def _capture_filter(clients, http_port, socket_port):
        ips = sorted(set(
            item["ip"] for item in clients.values() if item.get("ip")
        ))
        if not ips:
            return None
        hosts = " or ".join("host %s" % ip for ip in ips)
        return "(%s) and (tcp port %d or tcp port %d)" % (
            hosts, int(http_port), int(socket_port)
        )

    def _resolve_interface(self, clients):
        ips = [item["ip"] for item in clients.values() if item.get("ip")]
        if not ips:
            raise PcapCaptureError("No active client has a known IP address")

        interfaces = []
        for ip in ips:
            value = str(self.pcap.resolve_interface(ip))
            if value not in interfaces:
                interfaces.append(value)
        if len(interfaces) != 1:
            raise PcapCaptureError(
                "Active clients are reachable through different capture "
                "interfaces (%s). Set one explicit Capture interface for the "
                "server or monitor clients on the same interface." %
                ", ".join(interfaces)
            )
        return interfaces[0]

    def _desired_signature(self, clients):
        try:
            import scapy.all  # noqa: F401
        except ImportError:
            raise PcapCaptureError(
                "Scapy is required for live monitoring. Install server/requirements.txt."
            )
        capture_filter = self._capture_filter(
            clients, self.pcap.http_port, self.pcap.socket_port
        )
        if not capture_filter:
            return None
        interface = self._resolve_interface(clients)
        backend = self.pcap.backend()
        if not backend:
            raise PcapCaptureError(
                "Live monitoring needs tcpdump or dumpcap. No capture backend was found."
            )
        return backend, interface, capture_filter

    def _build_command(self, signature):
        backend, interface, capture_filter = signature
        if backend == "dumpcap":
            binary = self.pcap._find_program("dumpcap")
            return [
                binary, "-q", "-P", "-i", str(interface),
                "-f", capture_filter, "-w", "-"
            ]
        binary = self.pcap._find_program("tcpdump")
        return [
            binary, "-n", "-U", "-s", "0", "-i", str(interface),
            "-w", "-", capture_filter
        ]

    def _start_capture(self, signature):
        self._stop_capture()
        backend, interface, capture_filter = signature
        log_path = Path(self.pcap.output_dir) / "live_monitor.capture.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("wb")
        cmd = self._build_command(signature)

        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=log_handle,
                start_new_session=(os.name == "posix"),
                creationflags=creationflags,
                bufsize=0,
            )
        except Exception:
            log_handle.close()
            raise

        time.sleep(0.20)
        if proc.poll() is not None:
            log_handle.close()
            try:
                details = log_path.read_text(
                    encoding="utf-8", errors="replace"
                ).strip()
            except Exception:
                details = ""
            raise PcapCaptureError(
                details or "Live capture process exited immediately"
            )

        with self._lock:
            self._capture_proc = proc
            self._capture_log_handle = log_handle
            self._capture_signature = signature
            # The first fractional second after starting/restarting capture is
            # intentionally discarded.  A live inference row is emitted only
            # when capture covered the entire one-second window.
            self._capture_full_from_second = int(math.floor(time.time())) + 1
            self._buckets.clear()
            self._last_packet_ts.clear()
            self._last_finalized_second.clear()
            self._capture_state = "running"
            self._capture_error = None
            self._capture_backend = backend
            self._capture_interface = str(interface)
            self._capture_filter = capture_filter

        reader = threading.Thread(
            target=self._reader_loop,
            args=(proc,),
            name="InterchangeLiveCaptureReader",
            daemon=True,
        )
        self._capture_reader_thread = reader
        reader.start()
        self.model.clear_runtime_error()

    def _stop_capture(self):
        with self._lock:
            proc = self._capture_proc
            log_handle = self._capture_log_handle
            self._capture_proc = None
            self._capture_log_handle = None
            self._capture_signature = None
            self._capture_reader_thread = None
            if self._capture_state != "error":
                self._capture_state = "idle"
            self._capture_backend = None
            self._capture_interface = None
            self._capture_filter = None
            self._capture_full_from_second = None

        if proc is not None:
            try:
                if proc.poll() is None:
                    if os.name == "posix":
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGINT)
                        except Exception:
                            proc.terminate()
                    elif hasattr(signal, "CTRL_BREAK_EVENT"):
                        try:
                            proc.send_signal(signal.CTRL_BREAK_EVENT)
                        except Exception:
                            proc.terminate()
                    else:
                        proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            except Exception:
                pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass

    def _reader_loop(self, proc):
        try:
            from scapy.all import PcapReader, IP, IPv6, TCP, UDP, Raw
        except ImportError:
            self._set_capture_error(
                "Scapy is required for live monitoring. Install server/requirements.txt."
            )
            return

        try:
            reader = PcapReader(proc.stdout)
        except Exception as exc:
            self._set_capture_error("Cannot open live packet stream: %s" % exc)
            return

        try:
            for pkt in reader:
                if self._stop.is_set():
                    break
                try:
                    ts = float(pkt.time)
                except Exception:
                    ts = time.time()
                self._accept_packet(pkt, ts, IP, IPv6, TCP, UDP, Raw)
        except Exception as exc:
            if not self._stop.is_set():
                self._set_capture_error("Live packet reader failed: %s" % exc)
        finally:
            try:
                reader.close()
            except Exception:
                pass

    def _set_capture_error(self, text):
        with self._lock:
            self._capture_state = "error"
            self._capture_error = str(text)
        self.model.set_runtime_error(str(text))

    def _accept_packet(self, pkt, ts, IP, IPv6, TCP, UDP, Raw):
        src_ip, dst_ip, ip_version = packet_endpoints(pkt, IP, IPv6)
        if src_ip is None:
            return

        with self._lock:
            clients = dict(self._online_clients)

        chosen = None
        for user_id, item in clients.items():
            ip = item.get("ip")
            if ip and (src_ip == ip or dst_ip == ip):
                chosen = (user_id, ip)
                break
        if chosen is None:
            return

        user_id, client_ip = chosen
        second = int(math.floor(float(ts)))
        with self._lock:
            last_done = self._last_finalized_second.get(user_id)
            if last_done is not None and second <= last_done:
                # Late packet for an already-published second: do not mutate a
                # model result after it has been shown to the administrator.
                return
            user_buckets = self._buckets.setdefault(user_id, {})
            bucket = user_buckets.get(second)
            if bucket is None:
                bucket = make_empty_window()
                user_buckets[second] = bucket
            previous_ts = self._last_packet_ts.get(user_id)
            interarrival = None
            if previous_ts is not None:
                delta = float(ts) - float(previous_ts)
                if delta >= 0:
                    interarrival = delta

            accepted = add_packet(
                bucket, pkt, ts, client_ip,
                self.pcap.http_port, self.pcap.socket_port,
                IP, IPv6, TCP, UDP, Raw,
                interarrival=interarrival,
            )
            if accepted:
                self._last_packet_ts[user_id] = float(ts)
                self._last_packet_epoch = float(ts)

    def _finalize_previous_second(self, clients):
        current_second = int(math.floor(time.time()))
        target_second = current_second - 1
        with self._lock:
            full_from = self._capture_full_from_second
        if full_from is None or target_second < full_from:
            return
        for user_id, item in clients.items():
            ip = item.get("ip")
            if not ip:
                continue
            with self._lock:
                last_done = self._last_finalized_second.get(user_id)
                if last_done is not None and target_second <= last_done:
                    continue
                bucket = self._buckets.setdefault(user_id, {}).pop(
                    target_second, None
                )
                if bucket is None:
                    bucket = make_empty_window()
                # Remove stale unfinalized buckets.  This can happen when a
                # capture stream restarts after a backend/interface change.
                for sec in list(self._buckets.get(user_id, {}).keys()):
                    if sec < target_second:
                        self._buckets[user_id].pop(sec, None)
                self._last_finalized_second[user_id] = target_second

            metrics = finalize_window(bucket)
            try:
                self.model.predict_window(
                    user_id, ip, float(target_second), metrics
                )
            except Exception:
                # ModelManager already records the concrete inference error.
                pass

    def _cleanup_offline_state(self, clients):
        active = set(clients.keys())
        with self._lock:
            for mapping in (
                self._buckets, self._last_packet_ts,
                self._last_finalized_second,
            ):
                for user_id in list(mapping.keys()):
                    if user_id not in active:
                        mapping.pop(user_id, None)

    def _supervisor_loop(self):
        while not self._stop.is_set():
            try:
                clients = self._client_snapshot()
                with self._lock:
                    self._online_clients = clients
                self._cleanup_offline_state(clients)

                if not self.model.is_loaded() or not clients:
                    self._stop_capture()
                    with self._lock:
                        self._capture_state = "idle"
                        self._capture_error = None
                    if not self.model.is_loaded():
                        self.model.clear_runtime_error()
                    self._stop.wait(0.25)
                    continue

                signature = self._desired_signature(clients)
                with self._lock:
                    proc = self._capture_proc
                    current_signature = self._capture_signature
                if (proc is None or proc.poll() is not None or
                        current_signature != signature):
                    self._start_capture(signature)

                self._finalize_previous_second(clients)
            except Exception as exc:
                self._set_capture_error(str(exc))
                self._stop_capture()
                # Preserve error state after _stop_capture.
                with self._lock:
                    self._capture_state = "error"
                    self._capture_error = str(exc)
                self._stop.wait(1.0)
                continue
            self._stop.wait(0.20)

    def snapshot(self):
        clients = self._client_snapshot()
        model_status = self.model.status()
        with self._lock:
            capture_state_for_rows = self._capture_state
        rows = []
        for user_id in sorted(clients.keys()):
            item = clients[user_id]
            latest = self.model.latest_for(user_id)
            row = {
                "user_id": user_id,
                "name": item.get("name") or user_id,
                "ip": item.get("ip") or "",
                "online": bool(item.get("online")),
                "status": "NO_DATA",
                "prediction": None,
                "anomaly_type": None,
                "confidence": None,
                "window_start_epoch": None,
                "window_end_epoch": None,
                "metrics": None,
                "class_probabilities": {},
            }
            if not model_status.get("loaded"):
                row["status"] = "MODEL_NOT_LOADED"
            elif capture_state_for_rows == "error" and not latest:
                row["status"] = "CAPTURE_ERROR"
            elif latest:
                row.update({
                    "status": latest.get("status"),
                    "prediction": latest.get("prediction"),
                    "anomaly_type": latest.get("anomaly_type"),
                    "confidence": latest.get("confidence"),
                    "window_start_epoch": latest.get("window_start_epoch"),
                    "window_end_epoch": latest.get("window_end_epoch"),
                    "metrics": latest.get("features"),
                    "class_probabilities": latest.get("class_probabilities") or {},
                })
            rows.append(row)

        with self._lock:
            capture = {
                "state": self._capture_state,
                "error": self._capture_error,
                "backend": self._capture_backend,
                "interface": self._capture_interface,
                "filter": self._capture_filter,
                "last_packet_epoch": self._last_packet_epoch,
            }

        return {
            "model": model_status,
            "capture": capture,
            "clients": rows,
            "events": self.model.events(60),
            "window_sec": FIXED_WINDOW_SEC,
            "observation_only": True,
        }

    def client_details(self, user_id):
        latest = self.model.latest_for(user_id)
        return {
            "latest": latest,
            "history": self.model.history_for(user_id),
        }
