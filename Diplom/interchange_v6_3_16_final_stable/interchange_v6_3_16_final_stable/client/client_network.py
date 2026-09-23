import json
import logging
import queue
import random
import socket
import string
import tempfile
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

import requests

import auth_protocol
from qt_compat import QObject, Signal
from transfer_utils import CHUNK_SIZE, make_folder_zip, safe_extract, sha256_file
from py_compat import safe_unlink

log = logging.getLogger("lan_exchange.client")







class FatalAuthError(Exception):
    pass


HEARTBEAT_INTERVAL = 3.0
HEARTBEAT_TIMEOUT = 9.0
RECONNECT_DELAY = 2.0
EXPERIMENT_RECONNECT_DELAY = 0.05
TRANSFER_PROGRESS_MIN_INTERVAL = 0.10


class ClientNetwork(QObject):
    connection_changed = Signal(bool)
    presence_changed = Signal(list)
    message_received = Signal(dict)
    message_sent = Signal(dict)
    history_synced = Signal(str, list)
    transfer_progress = Signal(str, int)
    transfer_status = Signal(dict)
    user_error = Signal(str)
    fatal_error = Signal(str)
    experiment_changed = Signal(dict)

    def __init__(self, server, http_port, socket_port, user_id,
                 client_token, password_secret, dest):
        super().__init__()
        self.server = server
        self.http_port = http_port
        self.socket_port = socket_port
        self.user_id = user_id
        self.client_token = client_token
        self.password_secret = int(password_secret)
        self.token_secret = auth_protocol.derive_token_secret(
            client_token
        )
        self.dest = Path(dest).expanduser().resolve()
        self.dest.mkdir(parents=True, exist_ok=True)

        self.http_base = f"http://{server}:{http_port}"
        self._stop = threading.Event()
        self._out = queue.Queue()
        self._sock = None
        self._connected = False
        self._pending_messages = {}
        self._experiment_lock = threading.RLock()
        self._experiment_stop = threading.Event()
        self._experiment_thread = None
        self._experiment_run_id = None
        # Run ids force-reset by the administrator.  A detached old worker may
        # finish later, but its stale status must not leak into the UI/server.
        self._cancelled_experiment_runs = set()
        self._session_lock = threading.RLock()
        self._session_id = None
        self._session_key = None

    def start(self):
        threading.Thread(target=self._socket_loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        self._experiment_stop.set()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass

    def _experiment_is_active(self):
        with self._experiment_lock:
            return self._experiment_run_id is not None

    def send_message(self, recipient, text):
        client_msg_id = uuid.uuid4().hex
        payload = {
            "type": "message",
            "to": recipient,
            "text": text,
            "client_msg_id": client_msg_id
        }
        self._pending_messages[client_msg_id] = {
            "peer": recipient,
            "text": text
        }
        self._out.put(payload)

    def send_experiment_message(self, run_id, recipient, text):
        """Send normal-looking socket traffic without touching chat history/UI."""
        payload = {
            "type": "message",
            "to": recipient,
            "text": text,
            "client_msg_id": uuid.uuid4().hex,
            "experiment": True,
            "experiment_run_id": int(run_id),
        }
        self._out.put(payload)

    def refresh_users(self):
        threading.Thread(target=self._refresh_users, daemon=True).start()

    def sync_history(self, peer):
        threading.Thread(target=self._sync_history, args=(peer,), daemon=True).start()

    def sync_histories(self, peers):
        threading.Thread(
            target=self._sync_histories_worker,
            args=(list(peers),),
            daemon=True
        ).start()

    def send_path(self, recipient, path):
        threading.Thread(
            target=self._upload_path,
            args=(recipient, path),
            daemon=True
        ).start()

    def fetch_tasks(self):
        threading.Thread(target=self._fetch_tasks, daemon=True).start()

    def _set_connected(self, value):
        if self._connected != value:
            self._connected = value
            # FREQUENT_RECONNECT deliberately toggles the socket many times
            # per second. Keep the true internal state but do not flood Qt's
            # event queue with cosmetic connection-state changes.
            if not self._experiment_is_active():
                self.connection_changed.emit(value)

    def _recv_auth_message(self, sock):
        buffer = b""
        while b"\n" not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("socket closed during authentication")
            buffer += chunk
        raw = buffer.split(b"\n", 1)[0]
        return json.loads(raw.decode("utf-8"))

    def _authenticate_socket(self, sock):
        material = auth_protocol.new_client_auth_material()
        token_identifier = auth_protocol.token_id(
            self.client_token
        )

        previous_timeout = sock.gettimeout()
        sock.settimeout(4.0)
        try:
            self._send(sock, {
                "type": "auth_begin",
                "token_id": token_identifier,
                "dh_client": auth_protocol.int_hex(
                    material["dh_public"]
                ),
                "password_commitment": auth_protocol.int_hex(
                    material["password_commitment"]
                ),
                "token_commitment": auth_protocol.int_hex(
                    material["token_commitment"]
                )
            })
            challenge = self._recv_auth_message(sock)

            if challenge.get("type") != "auth_challenge":
                raise FatalAuthError(
                    challenge.get(
                        "message",
                        "Client authorization failed."
                    )
                )

            state = auth_protocol.client_finish_auth(
                material,
                self.password_secret,
                self.token_secret,
                token_identifier,
                challenge
            )
            self._send(sock, {
                "type": "auth_proof",
                "password_response": state["password_response_hex"],
                "token_response": state["token_response_hex"],
                "client_proof": state["client_proof"]
            })
            result = self._recv_auth_message(sock)

            if result.get("type") != "auth_ok":
                raise FatalAuthError(
                    result.get(
                        "message",
                        "Client authentication failed."
                    )
                )

            auth_protocol.verify_server_finish(
                state,
                result
            )

            returned_user_id = str(
                result.get("user_id", "")
            ).strip()
            if returned_user_id != self.user_id:
                raise FatalAuthError(
                    "Stored authorization does not match "
                    "the server client identity."
                )

            with self._session_lock:
                self._session_id = result["session_id"]
                self._session_key = state["session_key"]

            return result
        finally:
            sock.settimeout(previous_timeout)

    def _clear_session(self):
        with self._session_lock:
            self._session_id = None
            self._session_key = None

    def _http_headers(self, method, path, extra=""):
        with self._session_lock:
            session_id = self._session_id
            session_key = self._session_key

        if not session_id or not session_key:
            raise RuntimeError("Authenticated session is not available")

        nonce = auth_protocol.new_http_nonce()
        mac = auth_protocol.http_request_mac(
            session_key,
            method,
            path,
            self.user_id,
            nonce,
            extra
        )
        return {
            "X-Auth-User-ID": self.user_id,
            "X-Session-ID": session_id,
            "X-Request-Nonce": nonce,
            "X-Request-MAC": mac
        }

    def _socket_loop(self):
        while not self._stop.is_set():
            try:
                sock = socket.create_connection(
                    (self.server, self.socket_port),
                    timeout=4
                )
                sock.settimeout(0.5)
                self._enable_tcp_keepalive(sock)
                self._sock = sock
                self._set_connected(False)

                self._authenticate_socket(sock)
                self._set_connected(True)
                # Intentional reconnect tests can establish many sessions per
                # second.  Do not trigger users/history/task refresh on every
                # synthetic reconnect; one refresh is performed after the test.
                if not self._experiment_is_active():
                    self.refresh_users()
                    self.fetch_tasks()

                buffer = b""
                now = time.monotonic()
                last_rx = now
                last_ping = now

                while not self._stop.is_set():
                    while True:
                        try:
                            payload = self._out.get_nowait()
                        except queue.Empty:
                            break
                        self._send(sock, payload)

                    try:
                        data = sock.recv(65536)
                        if not data:
                            raise ConnectionError("socket closed")
                        buffer += data
                        last_rx = time.monotonic()
                    except socket.timeout:
                        pass

                    while b"\n" in buffer:
                        raw, buffer = buffer.split(b"\n", 1)
                        if raw.strip():
                            self._handle_socket_event(
                                json.loads(raw.decode("utf-8"))
                            )

                    now = time.monotonic()

                    if now - last_ping >= HEARTBEAT_INTERVAL:
                        self._send(sock, {"type": "ping"})
                        last_ping = now

                    if now - last_rx >= HEARTBEAT_TIMEOUT:
                        raise ConnectionError("heartbeat timeout")

            except FatalAuthError as exc:
                self._stop.set()
                self._set_connected(False)
                self._clear_session()
                self.fatal_error.emit(str(exc))
            except Exception:
                log.exception("Socket connection failed")
                self._set_connected(False)
                self._clear_session()
                if not self._stop.is_set():
                    delay = (
                        EXPERIMENT_RECONNECT_DELAY
                        if self._experiment_is_active()
                        else RECONNECT_DELAY
                    )
                    self._stop.wait(delay)
            finally:
                self._set_connected(False)
                try:
                    if self._sock:
                        self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def _handle_socket_event(self, msg):
        kind = msg.get("type")

        if kind == "presence":
            # FREQUENT_RECONNECT intentionally produces a presence storm.
            # Suppress those synthetic updates while the test is active.
            if self._experiment_is_active():
                return
            users = msg.get("users", [])
            self.presence_changed.emit(users)

        elif kind == "message":
            if not msg.get("experiment"):
                self.message_received.emit(msg)

        elif kind == "message_ack":
            client_msg_id = msg.get("client_msg_id")
            self._pending_messages.pop(client_msg_id, None)
            if not msg.get("experiment"):
                self.message_sent.emit(msg)

        elif kind == "task_available":
            if not self._experiment_is_active():
                self.fetch_tasks()

        elif kind == "transfer_status":
            self.transfer_status.emit(msg)

        elif kind == "experiment_start":
            self._start_experiment(msg)

        elif kind == "experiment_stop":
            self._stop_experiment(msg.get("run_id"))

        elif kind == "experiment_force_stop":
            self._force_stop_experiment(msg.get("run_id"))

        elif kind == "pong":

            pass

        elif kind == "error":
            message = msg.get("message", "Error")
            if msg.get("fatal"):


                self._stop.set()
                self._set_connected(False)
                self._clear_session()
                self.fatal_error.emit(message)
                try:
                    if self._sock:
                        self._sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
            else:
                self.user_error.emit(message)

    def _send_experiment_status(self, run_id, status, error=None,
                                **extra):
        try:
            run_key = int(run_id)
        except Exception:
            return
        with self._experiment_lock:
            if run_key in self._cancelled_experiment_runs:
                return
        payload = {
            "type": "experiment_status",
            "run_id": run_key,
            "status": status
        }
        if error:
            payload["error"] = str(error)
        payload.update(extra)
        self._out.put(payload)
        self.experiment_changed.emit(dict(payload))

    def _start_experiment(self, msg):
        run_id = msg.get("run_id")
        timeline = msg.get("timeline") or []
        params = msg.get("params") or {}

        try:
            run_id = int(run_id)
        except Exception:
            return

        with self._experiment_lock:
            if (self._experiment_thread is not None and
                    self._experiment_thread.is_alive()):
                self._send_experiment_status(
                    run_id, "error", "Another experiment is already active"
                )
                return

            stop_event = threading.Event()
            self._experiment_stop = stop_event
            self._experiment_run_id = run_id
            self._cancelled_experiment_runs.discard(run_id)
            self._experiment_thread = threading.Thread(
                target=self._experiment_worker,
                args=(run_id, timeline, params, stop_event),
                daemon=True
            )
            self._experiment_thread.start()

    def _stop_experiment(self, run_id=None):
        with self._experiment_lock:
            if self._experiment_run_id is None:
                return
            if run_id is not None:
                try:
                    if int(run_id) != int(self._experiment_run_id):
                        return
                except Exception:
                    return
            self._experiment_stop.set()

    def _force_stop_experiment(self, run_id=None):
        """Detach a wedged experiment immediately.

        The worker gets its own immutable stop_event, so clearing the active
        slot here is safe: a newly started experiment cannot accidentally
        reactivate the old worker by replacing ``self._experiment_stop``.
        """
        with self._experiment_lock:
            if self._experiment_run_id is None:
                return
            try:
                active_id = int(self._experiment_run_id)
                requested_id = active_id if run_id is None else int(run_id)
            except Exception:
                return
            if requested_id != active_id:
                return

            self._cancelled_experiment_runs.add(active_id)
            self._experiment_stop.set()
            # Do not join here.  A requests call may still be inside an OS I/O
            # wait.  Detaching releases the client for the next test at once.
            self._experiment_run_id = None
            self._experiment_thread = None

    @staticmethod
    def _float_param(params, name, default, minimum, maximum):
        try:
            value = float(params.get(name, default))
        except Exception:
            value = float(default)
        return max(float(minimum), min(float(maximum), value))

    @staticmethod
    def _int_param(params, name, default, minimum, maximum):
        try:
            value = int(params.get(name, default))
        except Exception:
            value = int(default)
        return max(int(minimum), min(int(maximum), value))

    def _wait_experiment(self, seconds, stop_event):
        end = time.monotonic() + max(0.0, float(seconds))
        while not stop_event.is_set():
            remaining = end - time.monotonic()
            if remaining <= 0:
                return True
            stop_event.wait(min(0.2, remaining))
        return False

    def _random_wait(self, minimum, maximum, stop_event):
        minimum = max(0.0, float(minimum))
        maximum = max(minimum, float(maximum))
        delay = random.uniform(minimum, maximum)
        return stop_event.wait(delay)

    def _baseline_message_loop(self, run_id, params, stop_event):
        min_interval = self._float_param(
            params, "baseline_message_interval_min_sec", 1.0, 0.2, 60.0
        )
        max_interval = self._float_param(
            params, "baseline_message_interval_max_sec", 4.0,
            min_interval, 120.0
        )
        min_length = self._int_param(
            params, "baseline_message_length_min", 8, 1, 4096
        )
        max_length = self._int_param(
            params, "baseline_message_length_max", 80,
            min_length, 8192
        )

        alphabet = string.ascii_letters + string.digits

        while not stop_event.is_set():
            length = random.randint(min_length, max_length)
            text = "".join(random.choice(alphabet) for _ in range(length))
            self.send_experiment_message(run_id, "server", text)

            if self._random_wait(min_interval, max_interval, stop_event):
                return

    def _baseline_file_loop(self, run_id, params, stop_event):
        baseline_dir = Path(
            str(params.get("baseline_dir", ""))
        ).expanduser().resolve()

        if not baseline_dir.exists() or not baseline_dir.is_dir():
            raise RuntimeError(
                "Baseline folder does not exist on this client: %s"
                % baseline_dir
            )

        items = [
            item for item in baseline_dir.iterdir()
            if item.is_file() or item.is_dir()
        ]
        if not items:
            raise RuntimeError(
                "Baseline folder is empty: %s" % baseline_dir
            )

        min_interval = self._float_param(
            params, "baseline_file_interval_min_sec", 3.0, 0.5, 300.0
        )
        max_interval = self._float_param(
            params, "baseline_file_interval_max_sec", 8.0,
            min_interval, 600.0
        )

        while not stop_event.is_set():
            item = random.choice(items)
            self._upload_path(
                "server", item, stop_event=stop_event,
                quiet=True, experiment_run_id=run_id
            )

            if stop_event.is_set():
                return
            if self._random_wait(min_interval, max_interval, stop_event):
                return

    def _baseline_thread_wrapper(self, target, errors, stop_event):
        try:
            target()
        except Exception as exc:
            if stop_event.is_set():
                return
            log.exception("Baseline traffic worker failed")
            errors.append(str(exc))
            stop_event.set()

    def _run_anomaly_overlay(self, run_id, anomaly_type, params, duration,
                             stop_event):
        if anomaly_type == "NORMAL":
            self._wait_experiment(duration, stop_event)
            return

        if anomaly_type == "HIGH_REQUEST_RATE":
            rate = self._float_param(
                params, "requests_per_sec", 20.0, 1.0, 100.0
            )
            interval = 1.0 / rate
            session = requests.Session()
            end = time.monotonic() + duration
            try:
                while (not stop_event.is_set() and
                       time.monotonic() < end):
                    started = time.monotonic()
                    try:
                        extra = auth_protocol.canonical_extra([run_id])
                        headers = self._http_headers(
                            "GET",
                            "/experiment/request",
                            extra
                        )
                        headers["X-User-ID"] = self.user_id
                        headers["X-Experiment-Run-ID"] = str(run_id)
                        headers["Connection"] = "keep-alive"
                        response = session.get(
                            f"{self.http_base}/experiment/request",
                            headers=headers,
                            timeout=2
                        )
                        response.close()
                    except Exception:
                        pass

                    delay = interval - (time.monotonic() - started)
                    if delay > 0:
                        stop_event.wait(delay)
            finally:
                try:
                    session.close()
                except Exception:
                    pass
            return

        if anomaly_type == "FREQUENT_RECONNECT":
            interval = self._float_param(
                params, "interval_sec", 1.0, 0.1, 10.0
            )
            end = time.monotonic() + duration

            while (not stop_event.is_set() and
                   time.monotonic() < end):
                stop_event.wait(interval)
                if stop_event.is_set():
                    break
                try:
                    sock = self._sock
                    if sock:
                        sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    if self._sock:
                        self._sock.close()
                except Exception:
                    pass
            return

        if anomaly_type == "HIGH_FREQUENCY_SMALL_TRANSFERS":
            session = requests.Session()
            response = None
            try:
                extra = auth_protocol.canonical_extra([run_id])
                headers = self._http_headers(
                    "GET",
                    "/experiment/small-stream",
                    extra
                )
                headers["X-User-ID"] = self.user_id
                headers["X-Experiment-Run-ID"] = str(run_id)
                response = session.get(
                    f"{self.http_base}/experiment/small-stream",
                    headers=headers,
                    stream=True,
                    timeout=(3, max(5.0, float(duration) + 5.0))
                )
                response.raise_for_status()

                for chunk in response.iter_content(chunk_size=8192):
                    if stop_event.is_set():
                        break
                    if not chunk:
                        continue
            except Exception:
                pass
            finally:
                try:
                    if response is not None:
                        response.close()
                except Exception:
                    pass
                try:
                    session.close()
                except Exception:
                    pass
            return

        raise RuntimeError(
            "Unsupported experiment type: %s" % anomaly_type
        )


    def _experiment_worker(self, run_id, timeline, params, stop_event):
        baseline_threads = []
        baseline_errors = []
        planned_stop = False

        try:
            baseline_dir = str(params.get("baseline_dir", "")).strip()
            if not baseline_dir:
                raise RuntimeError("Baseline folder path was not provided")

            baseline_path = Path(baseline_dir).expanduser().resolve()
            if not baseline_path.exists() or not baseline_path.is_dir():
                raise RuntimeError(
                    "Baseline folder does not exist on this client: %s"
                    % baseline_path
                )
            if not any(
                item.is_file() or item.is_dir()
                for item in baseline_path.iterdir()
            ):
                raise RuntimeError(
                    "Baseline folder is empty: %s" % baseline_path
                )

            if not timeline:
                raise RuntimeError("Experiment timeline is empty")

            total_duration = float(timeline[-1]["end_sec"])
            origin_monotonic = time.monotonic()




            self._send_experiment_status(
                run_id,
                "running"
            )

            message_thread = threading.Thread(
                target=self._baseline_thread_wrapper,
                args=(
                    lambda: self._baseline_message_loop(run_id, params, stop_event),
                    baseline_errors,
                    stop_event
                ),
                daemon=True
            )
            file_thread = threading.Thread(
                target=self._baseline_thread_wrapper,
                args=(
                    lambda: self._baseline_file_loop(run_id, params, stop_event),
                    baseline_errors,
                    stop_event
                ),
                daemon=True
            )
            baseline_threads = [message_thread, file_thread]

            for thread in baseline_threads:
                thread.start()

            for phase_index, phase in enumerate(timeline):
                if stop_event.is_set():
                    planned_stop = True
                    break

                start_sec = float(phase["start_sec"])
                end_sec = float(phase["end_sec"])
                label = str(phase["label"])
                phase_params = dict(phase.get("params") or {})



                while not stop_event.is_set():
                    remaining = (
                        origin_monotonic + start_sec - time.monotonic()
                    )
                    if remaining <= 0:
                        break
                    stop_event.wait(min(0.2, remaining))

                if stop_event.is_set():
                    planned_stop = True
                    break

                self._send_experiment_status(
                    run_id,
                    "phase",
                    phase_index=int(phase_index),
                    label=label
                )

                remaining_duration = max(
                    0.0,
                    origin_monotonic + end_sec - time.monotonic()
                )
                self._run_anomaly_overlay(
                    run_id,
                    label,
                    phase_params,
                    remaining_duration,
                    stop_event
                )

                if stop_event.is_set():
                    planned_stop = True
                    break


            if not planned_stop:
                remaining = origin_monotonic + total_duration - time.monotonic()
                if remaining > 0:
                    if stop_event.wait(remaining):
                        planned_stop = True

            stop_event.set()




            deadline = time.monotonic() + 120.0
            for thread in baseline_threads:
                remaining = max(0.0, deadline - time.monotonic())
                thread.join(remaining)

            if any(thread.is_alive() for thread in baseline_threads):
                raise RuntimeError(
                    "Baseline file transfer did not finish in time"
                )

            if baseline_errors:
                raise RuntimeError(baseline_errors[0])

            if planned_stop:
                self._send_experiment_status(
                    run_id,
                    "stopped"
                )
            else:
                self._send_experiment_status(
                    run_id,
                    "completed"
                )

        except Exception as exc:
            log.exception("Experiment failed")
            stop_event.set()
            for thread in baseline_threads:
                try:
                    thread.join(2.0)
                except Exception:
                    pass
            self._send_experiment_status(
                run_id,
                "error",
                exc
            )
        finally:
            should_refresh = False
            with self._experiment_lock:
                if self._experiment_run_id == run_id:
                    self._experiment_run_id = None
                    self._experiment_thread = None
                    should_refresh = True
                self._cancelled_experiment_runs.discard(int(run_id))

            # Re-enable normal presence/history/task synchronization only once
            # after synthetic traffic has finished.
            if should_refresh and not self._stop.is_set():
                self.connection_changed.emit(bool(self._connected))
                self.refresh_users()
                self.fetch_tasks()

    @staticmethod
    def _enable_tcp_keepalive(sock):
        """Best-effort OS keepalive in addition to application heartbeat."""
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)



            tcp_keepidle = getattr(socket, "TCP_KEEPIDLE", None)
            tcp_keepintvl = getattr(socket, "TCP_KEEPINTVL", None)
            tcp_keepcnt = getattr(socket, "TCP_KEEPCNT", None)

            if tcp_keepidle is not None:
                sock.setsockopt(socket.IPPROTO_TCP, tcp_keepidle, 10)
            if tcp_keepintvl is not None:
                sock.setsockopt(socket.IPPROTO_TCP, tcp_keepintvl, 3)
            if tcp_keepcnt is not None:
                sock.setsockopt(socket.IPPROTO_TCP, tcp_keepcnt, 3)
        except Exception:

            pass

    @staticmethod
    def _send(sock, payload):
        sock.sendall(
            (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        )

    def _refresh_users(self):
        try:
            headers = self._http_headers("GET", "/users")
            r = requests.get(
                f"{self.http_base}/users",
                headers=headers,
                timeout=5
            )
            r.raise_for_status()
            self.presence_changed.emit(r.json().get("users", []))
        except Exception:
            log.exception("Users refresh failed")

    def _sync_history(self, peer):
        try:
            extra = auth_protocol.canonical_extra([peer, 50])
            headers = self._http_headers(
                "GET",
                "/history",
                extra
            )
            r = requests.get(
                f"{self.http_base}/history",
                params={
                    "user_id": self.user_id,
                    "peer": peer,
                    "limit": 50
                },
                headers=headers,
                timeout=7
            )
            r.raise_for_status()
            self.history_synced.emit(
                peer,
                r.json().get("messages", [])
            )
        except Exception:
            log.exception("History sync failed for %s", peer)

    def _sync_histories_worker(self, peers):
        for peer in peers:
            if self._stop.is_set():
                return
            self._sync_history(peer)

    def _upload_path(self, recipient, path, stop_event=None,
                     quiet=False, experiment_run_id=None):
        path = Path(path).expanduser().resolve()
        if stop_event is not None and stop_event.is_set():
            return False
        if not path.exists():
            self.user_error.emit("File or folder not found")
            return

        tmp_zip = None
        try:
            item_type = "folder" if path.is_dir() else "file"
            send_path = path
            if item_type == "folder":
                tmp_zip = make_folder_zip(path)
                send_path = tmp_zip

            total = send_path.stat().st_size
            digest = sha256_file(send_path)
            sent = 0
            last_progress_time = [0.0]
            last_progress_percent = [-1]

            def emit_progress(percent, force=False):
                if quiet:
                    return
                now = time.monotonic()
                if (force or percent >= 100 or
                        (percent != last_progress_percent[0] and
                         now - last_progress_time[0] >=
                         TRANSFER_PROGRESS_MIN_INTERVAL)):
                    last_progress_time[0] = now
                    last_progress_percent[0] = percent
                    self.transfer_progress.emit(path.name, percent)

            def body():
                nonlocal sent
                with send_path.open("rb") as f:
                    while True:
                        if stop_event is not None and stop_event.is_set():
                            raise RuntimeError("Experiment transfer cancelled")
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        sent += len(chunk)
                        percent = int(sent * 100 / total) if total else 100
                        emit_progress(percent)
                        yield chunk


            encoded_name = urllib.parse.quote(path.name, safe="")
            extra_values = [
                recipient, encoded_name, item_type, total, digest
            ]
            if experiment_run_id is not None:
                extra_values.append(int(experiment_run_id))
            extra = auth_protocol.canonical_extra(extra_values)
            headers = self._http_headers(
                "POST",
                "/upload",
                extra
            )
            headers.update({
                "X-Sender-ID": self.user_id,
                "X-Recipient-ID": recipient,
                "X-Item-Name": encoded_name,
                "X-Item-Type": item_type,
                "X-Body-SHA256": digest,
                "Content-Length": str(total)
            })
            if experiment_run_id is not None:
                headers["X-Experiment-Run-ID"] = str(int(experiment_run_id))

            r = requests.post(
                f"{self.http_base}/upload",
                headers=headers,
                data=body(),
                timeout=(10, 20 if stop_event is not None else 600)
            )
            r.raise_for_status()
            data = r.json()

            if quiet:
                return True

            emit_progress(100, force=True)
            self.transfer_status.emit({
                "status": data.get("status", "uploaded"),
                "transfer_id": data.get("transfer_id"),
                "text": f"{path.name}: sent",
                "peer": recipient,
                "message_id": data.get("message_id"),
                "created_at": data.get("created_at"),
                "sender_id": self.user_id,
                "recipient_id": recipient,
                "direction": "outgoing"
            })
            return True

        except Exception:
            if stop_event is not None and stop_event.is_set():
                return False
            log.exception("Upload failed")
            if quiet:
                return False
            self.transfer_status.emit({
                "status": "error",
                "text": f"{path.name}: send error",
                "peer": recipient,
                "sender_id": self.user_id,
                "recipient_id": recipient,
                "direction": "outgoing"
            })
            return False
        finally:
            if tmp_zip:
                safe_unlink(tmp_zip)

    def _fetch_tasks(self):
        try:
            headers = self._http_headers("GET", "/tasks")
            r = requests.get(
                f"{self.http_base}/tasks",
                params={"user_id": self.user_id},
                headers=headers,
                timeout=7
            )
            r.raise_for_status()
            for task in r.json().get("tasks", []):
                self._download_task(task)
        except Exception:
            log.exception("Task fetch failed")

    def _download_task(self, task):
        tid = task["id"]
        item_name = task["item_name"]
        item_type = task["item_type"]
        peer = task["sender_id"]

        try:
            extra = auth_protocol.canonical_extra([tid])
            headers = self._http_headers(
                "GET",
                "/download",
                extra
            )
            r = requests.get(
                f"{self.http_base}/download",
                params={"id": tid, "user_id": self.user_id},
                headers=headers,
                stream=True,
                timeout=(10, 600)
            )
            r.raise_for_status()

            expected = r.headers.get("X-SHA256")
            total = int(r.headers.get("Content-Length", "0"))

            if item_type == "file":
                final = self._unique_path(self.dest / item_name)
                tmp = final.with_name(final.name + ".part")
            else:
                f = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
                f.close()
                tmp = Path(f.name)

            done = 0
            last_progress_time = 0.0
            last_progress_percent = -1
            with tmp.open("wb") as out:
                for chunk in r.iter_content(CHUNK_SIZE):
                    if not chunk:
                        continue
                    out.write(chunk)
                    done += len(chunk)
                    percent = int(done * 100 / total) if total else 0
                    now = time.monotonic()
                    if (percent != last_progress_percent and
                            now - last_progress_time >=
                            TRANSFER_PROGRESS_MIN_INTERVAL):
                        last_progress_time = now
                        last_progress_percent = percent
                        self.transfer_progress.emit(item_name, percent)

            if expected and sha256_file(tmp).lower() != expected.lower():
                safe_unlink(tmp)
                raise RuntimeError("SHA-256 mismatch")

            if item_type == "folder":
                safe_extract(tmp, self.dest)
                safe_unlink(tmp)
            else:
                tmp.replace(final)

            extra = auth_protocol.canonical_extra([tid])
            headers = self._http_headers(
                "POST",
                "/complete",
                extra
            )
            complete = requests.post(
                f"{self.http_base}/complete",
                json={"id": tid, "user_id": self.user_id},
                headers=headers,
                timeout=7
            )
            complete.raise_for_status()
            data = complete.json()

            self.transfer_progress.emit(item_name, 100)
            self.transfer_status.emit({
                "status": "received",
                "transfer_id": tid,
                "text": f"{item_name}: received",
                "peer": peer,
                "message_id": data.get("message_id"),
                "created_at": data.get("created_at"),


                "sender_id": data.get("sender_id", self.user_id),
                "recipient_id": data.get("recipient_id", peer),
                "direction": "outgoing"
            })



            self._sync_history(peer)

        except Exception:
            log.exception("Download failed")
            self.transfer_status.emit({
                "status": "error",
                "transfer_id": tid,
                "text": f"{item_name}: receive error",
                "peer": peer,
                "sender_id": peer,
                "recipient_id": self.user_id,
                "direction": "incoming"
            })

    @staticmethod
    def _unique_path(path: Path):
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        i = 1
        while True:
            candidate = path.with_name(f"{stem} ({i}){suffix}")
            if not candidate.exists():
                return candidate
            i += 1
