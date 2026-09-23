import json
import queue
import socket
import threading
import time

import auth_protocol
import db


AUTH_FAILURE_WINDOW_SEC = 60.0
AUTH_MAX_FAILURES = 5
AUTH_LOCK_SEC = 30.0
HTTP_NONCE_TTL_SEC = 600.0
HTTP_NONCE_LIMIT = 4096


class ClientConnection(object):
    def __init__(self, user_id, sock, address):
        self.user_id = user_id
        self.sock = sock
        self.address = address


class RealtimeHub:
    def __init__(self, host="0.0.0.0", port=8081, event_queue=None):
        self.host = host
        self.port = port
        self.event_queue = event_queue or queue.Queue()
        self._server = None
        self._running = threading.Event()
        self._clients = {}
        self._lock = threading.RLock()
        # Users running synthetic traffic are intentionally reconnecting.
        # Suppress presence storms for them until the test ends.
        self._experiment_presence_users = set()
        self._user_snapshot = None
        self._sessions = {}
        self._auth_failures = {}
        self.experiment_status_callback = None

    def start(self):
        self._running.set()
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self._server.listen(50)
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._registry_watch_loop, daemon=True).start()
        self.event_queue.put(("status", "Socket :%s started" % self.port))

    def stop(self):
        self._running.clear()
        try:
            self._server.close()
        except Exception:
            pass
        with self._lock:
            for conn in list(self._clients.values()):
                try:
                    conn.sock.close()
                except Exception:
                    pass
            self._clients.clear()
            self._sessions.clear()

    def online_users(self):
        with self._lock:
            return set(self._clients.keys())

    def _current_user_snapshot(self):
        rows = db.list_all_users()
        return tuple(
            (
                row["user_id"],
                row["name"],
                row["ip"] or "",
                row["role"],
                int(row["active"]),
                row["auth_status"],
                row["token_id"] or "",
                row["password_verifier"] or "",
                row["token_verifier"] or ""
            )
            for row in rows
        )

    def _registry_watch_loop(self):
        while self._running.is_set():
            try:
                snapshot = self._current_user_snapshot()
                if self._user_snapshot is None:
                    self._user_snapshot = snapshot
                elif snapshot != self._user_snapshot:
                    self._user_snapshot = snapshot
                    self._apply_user_registry()
                    self.broadcast_presence()
                    self.event_queue.put(("user_registry_changed",))
            except Exception as exc:
                self.event_queue.put(
                    ("debug", "User registry watch: %s" % exc)
                )

            for _ in range(10):
                if not self._running.is_set():
                    return
                threading.Event().wait(0.1)

    def _apply_user_registry(self):
        rows = db.list_all_users()
        users = {row["user_id"]: row for row in rows}

        with self._lock:
            current = list(self._clients.items())

        for user_id, conn in current:
            row = users.get(user_id)
            code = None
            message = None

            if row is None:
                code = "AUTH_REQUIRED"
                message = "This client authorization no longer exists."
            elif row["auth_status"] == "BLOCKED":
                code = "USER_BLOCKED"
                message = "Access was blocked by the administrator."
            elif row["auth_status"] == "REJECTED":
                code = "AUTH_REJECTED"
                message = "Access was rejected by the administrator."
            elif row["auth_status"] != "APPROVED" or not row["active"]:
                code = "AUTH_PENDING"
                message = "Access is waiting for administrator approval."

            if code:
                self.revoke_user_sessions(user_id)
                try:
                    self._send_raw(conn.sock, {
                        "type": "error",
                        "fatal": True,
                        "code": code,
                        "message": message
                    })
                except Exception:
                    pass
                try:
                    conn.sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    conn.sock.close()
                except Exception:
                    pass

    def _accept_loop(self):
        while self._running.is_set():
            try:
                sock, addr = self._server.accept()
            except OSError:
                break
            threading.Thread(
                target=self._client_loop,
                args=(sock, addr),
                daemon=True
            ).start()

    def _auth_payload(self, row):
        if row is None:
            return {
                "type": "auth_required",
                "status": "UNKNOWN",
                "message": "This client has not requested access yet."
            }

        status = row["auth_status"]
        base = {
            "status": status,
            "user_id": row["user_id"],
            "name": row["name"]
        }

        if status == "APPROVED" and row["active"]:
            base.update({
                "type": "auth_approved",
                "message": "Access approved. Enter your password to sign in."
            })
            return base
        if status == "PENDING":
            base.update({
                "type": "auth_pending",
                "message": "Waiting for administrator approval."
            })
            return base
        if status == "BLOCKED":
            base.update({
                "type": "auth_blocked",
                "message": "Access was blocked by the administrator."
            })
            return base
        if status == "REJECTED":
            base.update({
                "type": "auth_rejected",
                "message": "Access was rejected by the administrator."
            })
            return base

        base.update({
            "type": "auth_required",
            "message": "A new authorization request is required."
        })
        return base

    def _failure_state(self, token_identifier):
        now = time.monotonic()
        with self._lock:
            state = self._auth_failures.get(token_identifier)
            if not state:
                return 0.0
            locked_until = float(state.get("locked_until", 0.0))
            if locked_until > now:
                return locked_until - now
            attempts = [
                value for value in state.get("attempts", [])
                if now - value <= AUTH_FAILURE_WINDOW_SEC
            ]
            if attempts:
                state["attempts"] = attempts
            else:
                self._auth_failures.pop(token_identifier, None)
            return 0.0

    def _record_auth_failure(self, token_identifier):
        now = time.monotonic()
        with self._lock:
            state = self._auth_failures.setdefault(
                token_identifier,
                {"attempts": [], "locked_until": 0.0}
            )
            attempts = [
                value for value in state["attempts"]
                if now - value <= AUTH_FAILURE_WINDOW_SEC
            ]
            attempts.append(now)
            state["attempts"] = attempts
            if len(attempts) >= AUTH_MAX_FAILURES:
                state["locked_until"] = now + AUTH_LOCK_SEC
                state["attempts"] = []

    def _clear_auth_failures(self, token_identifier):
        with self._lock:
            self._auth_failures.pop(token_identifier, None)

    def _create_http_session(self, user_id, session_key):
        session_id = auth_protocol.new_session_id()
        now = time.monotonic()
        with self._lock:
            self._cleanup_sessions_locked(now)
            self._sessions[session_id] = {
                "user_id": user_id,
                "key": bytes(session_key),
                "created": now,
                "last_seen": now,
                "nonces": {}
            }
        return session_id

    def _cleanup_sessions_locked(self, now=None):
        if now is None:
            now = time.monotonic()
        expired = []
        for session_id, state in self._sessions.items():
            if now - state["last_seen"] > auth_protocol.SESSION_TTL_SEC:
                expired.append(session_id)
        for session_id in expired:
            self._sessions.pop(session_id, None)

    def revoke_user_sessions(self, user_id):
        with self._lock:
            remove = [
                session_id
                for session_id, state in self._sessions.items()
                if state["user_id"] == user_id
            ]
            for session_id in remove:
                self._sessions.pop(session_id, None)

    def verify_http_session(self, user_id, session_id, nonce,
                            supplied_mac, method, path, extra, ip):
        user_id = str(user_id or "")
        session_id = str(session_id or "")
        nonce = str(nonce or "")
        supplied_mac = str(supplied_mac or "")

        if not user_id or len(session_id) != 48 or len(nonce) != 32:
            return None

        now = time.monotonic()
        with self._lock:
            self._cleanup_sessions_locked(now)
            state = self._sessions.get(session_id)
            if not state or state["user_id"] != user_id:
                return None

            nonces = state["nonces"]
            stale = [
                value for value, created in nonces.items()
                if now - created > HTTP_NONCE_TTL_SEC
            ]
            for value in stale:
                nonces.pop(value, None)
            if nonce in nonces:
                return None

            expected = auth_protocol.http_request_mac(
                state["key"],
                method,
                path,
                user_id,
                nonce,
                extra
            )
            if not auth_protocol.verify_hex_mac(
                expected,
                supplied_mac
            ):
                return None

            nonces[nonce] = now
            if len(nonces) > HTTP_NONCE_LIMIT:
                oldest = sorted(
                    nonces.items(),
                    key=lambda item: item[1]
                )[:len(nonces) - HTTP_NONCE_LIMIT]
                for value, _ in oldest:
                    nonces.pop(value, None)
            state["last_seen"] = now

        row = db.get_user(user_id)
        if not row:
            return None
        if row["auth_status"] != "APPROVED" or not row["active"]:
            self.revoke_user_sessions(user_id)
            return None
        return db.touch_user(user_id, ip)

    def _begin_auth(self, msg, addr):
        token_identifier = str(msg.get("token_id", "")).strip().lower()
        failure_key = "%s|%s" % (token_identifier, addr[0])
        wait = self._failure_state(failure_key)
        if wait > 0:
            return None, {
                "type": "auth_error",
                "code": "AUTH_RATE_LIMIT",
                "message": "Too many failed sign-in attempts. Try again later."
            }

        row = db.get_auth_user(token_identifier)
        if row is None:
            return None, {
                "type": "auth_error",
                "code": "AUTH_REQUIRED",
                "message": "This client is not registered."
            }

        status = row["auth_status"]
        if status == "PENDING":
            return None, self._auth_payload(row)
        if status == "BLOCKED":
            return None, self._auth_payload(row)
        if status == "REJECTED":
            return None, self._auth_payload(row)
        if status != "APPROVED" or not row["active"]:
            return None, self._auth_payload(row)

        try:
            dh_client = auth_protocol.parse_group_value(
                msg.get("dh_client")
            )
            password_commitment = auth_protocol.parse_group_value(
                msg.get("password_commitment")
            )
            token_commitment = auth_protocol.parse_group_value(
                msg.get("token_commitment")
            )
            password_verifier = auth_protocol.parse_group_value(
                row["password_verifier"]
            )
            token_verifier = auth_protocol.parse_group_value(
                row["token_verifier"]
            )
            iterations = int(row["kdf_iterations"])
        except Exception:
            self._record_auth_failure(failure_key)
            return None, {
                "type": "auth_error",
                "code": "AUTH_FAILED",
                "message": "Authentication failed."
            }

        dh_private = auth_protocol.new_private_scalar()
        dh_server = auth_protocol.public_value(dh_private)
        challenge = auth_protocol.new_challenge_scalar()
        transcript_hash = auth_protocol.auth_transcript(
            token_identifier,
            row["user_id"],
            dh_client,
            dh_server,
            password_commitment,
            token_commitment,
            challenge,
            row["password_salt"],
            iterations
        )

        state = {
            "row": row,
            "token_id": token_identifier,
            "failure_key": failure_key,
            "dh_client": dh_client,
            "dh_private": dh_private,
            "dh_server": dh_server,
            "password_commitment": password_commitment,
            "token_commitment": token_commitment,
            "challenge": challenge,
            "password_verifier": password_verifier,
            "token_verifier": token_verifier,
            "transcript_hash": transcript_hash,
        }

        response = {
            "type": "auth_challenge",
            "protocol": auth_protocol.PROTOCOL_VERSION,
            "user_id": row["user_id"],
            "name": row["name"],
            "password_salt": row["password_salt"],
            "kdf_iterations": iterations,
            "dh_server": auth_protocol.int_hex(dh_server),
            "challenge": auth_protocol.int_hex(challenge)
        }
        return state, response

    def _finish_auth(self, pending, msg, addr):
        if pending is None:
            return None, {
                "type": "auth_error",
                "code": "AUTH_SEQUENCE",
                "message": "Authentication sequence is invalid."
            }

        token_identifier = pending["token_id"]
        failure_key = pending["failure_key"]
        try:
            password_response = auth_protocol.parse_scalar(
                msg.get("password_response")
            )
            token_response = auth_protocol.parse_scalar(
                msg.get("token_response")
            )
            client_proof = str(msg.get("client_proof", ""))
            password_ok = auth_protocol.verify_secret_proof(
                pending["password_commitment"],
                pending["challenge"],
                password_response,
                pending["password_verifier"]
            )
            token_ok = auth_protocol.verify_secret_proof(
                pending["token_commitment"],
                pending["challenge"],
                token_response,
                pending["token_verifier"]
            )
            shared_secret = pow(
                pending["dh_client"],
                pending["dh_private"],
                auth_protocol.P
            )
            session_key = auth_protocol.derive_session_key(
                shared_secret,
                pending["transcript_hash"]
            )
            expected_client_proof = auth_protocol.client_auth_proof(
                session_key,
                pending["transcript_hash"],
                password_response,
                token_response
            )
            mac_ok = auth_protocol.verify_hex_mac(
                expected_client_proof,
                client_proof
            )
        except Exception:
            password_ok = False
            token_ok = False
            mac_ok = False
            session_key = None
            password_response = 0
            token_response = 0

        if not password_ok or not token_ok or not mac_ok:
            self._record_auth_failure(failure_key)
            return None, {
                "type": "auth_error",
                "code": "AUTH_FAILED",
                "message": "Authentication failed. Check your password."
            }

        self._clear_auth_failures(failure_key)
        row = db.touch_user(
            pending["row"]["user_id"],
            addr[0]
        )
        session_id = self._create_http_session(
            row["user_id"],
            session_key
        )
        server_proof = auth_protocol.server_auth_proof(
            session_key,
            pending["transcript_hash"],
            password_response,
            token_response
        )
        return {
            "row": row,
            "session_key": session_key,
            "session_id": session_id
        }, {
            "type": "auth_ok",
            "user_id": row["user_id"],
            "name": row["name"],
            "session_id": session_id,
            "server_proof": server_proof
        }

    def _client_loop(self, sock, addr):
        user_id = None
        pending_auth = None
        buffer = b""
        sock.settimeout(1.0)

        try:
            while self._running.is_set():
                try:
                    data = sock.recv(65536)
                    if not data:
                        break
                    buffer += data
                except socket.timeout:
                    continue

                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    if not raw.strip():
                        continue
                    msg = json.loads(raw.decode("utf-8"))

                    if user_id is None:
                        kind = msg.get("type")

                        if kind == "auth_register":
                            try:
                                token_verifier = auth_protocol.parse_group_value(
                                    msg.get("token_verifier")
                                )
                                password_verifier = auth_protocol.parse_group_value(
                                    msg.get("password_verifier")
                                )
                                token_identifier = (
                                    auth_protocol.token_identifier_from_verifier(
                                        token_verifier
                                    )
                                )
                                supplied_token_id = str(
                                    msg.get("token_id", "")
                                ).strip().lower()
                                if token_identifier != supplied_token_id:
                                    raise ValueError(
                                        "Client token identifier is invalid"
                                    )
                                row = db.register_client_access(
                                    msg.get("name"),
                                    token_identifier,
                                    auth_protocol.int_hex(token_verifier),
                                    msg.get("password_salt"),
                                    msg.get("kdf_iterations"),
                                    auth_protocol.int_hex(password_verifier),
                                    addr[0]
                                )
                                self._send_raw(
                                    sock,
                                    self._auth_payload(row)
                                )
                                self.event_queue.put(
                                    ("auth_request", row["user_id"])
                                )
                            except Exception as exc:
                                self._send_raw(sock, {
                                    "type": "auth_error",
                                    "status": "ERROR",
                                    "message": str(exc)
                                })
                            return

                        if kind == "auth_status":
                            row = db.get_client_auth_status(
                                msg.get("token_id")
                            )
                            self._send_raw(
                                sock,
                                self._auth_payload(row)
                            )
                            return

                        if kind == "auth_begin":
                            pending_auth, response = self._begin_auth(
                                msg,
                                addr
                            )
                            self._send_raw(sock, response)
                            if pending_auth is None:
                                return
                            continue

                        if kind == "auth_proof":
                            auth_result, response = self._finish_auth(
                                pending_auth,
                                msg,
                                addr
                            )
                            self._send_raw(sock, response)
                            if auth_result is None:
                                return

                            row = auth_result["row"]
                            user_id = row["user_id"]
                            pending_auth = None

                            with self._lock:
                                old = self._clients.get(user_id)
                                if old:
                                    try:
                                        old.sock.close()
                                    except Exception:
                                        pass
                                self._clients[user_id] = ClientConnection(
                                    user_id,
                                    sock,
                                    addr
                                )

                            with self._lock:
                                suppress_presence = (
                                    user_id in self._experiment_presence_users
                                )
                            if not suppress_presence:
                                self.event_queue.put(
                                    ("presence", user_id, True, addr[0])
                                )
                                self.broadcast_presence()
                            continue

                        return

                    self._handle_message(user_id, msg)

        except Exception as exc:
            self.event_queue.put(("debug", "%s: %s" % (addr, exc)))
        finally:
            if user_id:
                with self._lock:
                    current = self._clients.get(user_id)
                    if current and current.sock is sock:
                        self._clients.pop(user_id, None)
                with self._lock:
                    suppress_presence = (
                        user_id in self._experiment_presence_users
                    )
                if not suppress_presence:
                    self.event_queue.put(
                        ("presence", user_id, False, addr[0])
                    )
                    self.broadcast_presence()
            try:
                sock.close()
            except Exception:
                pass

    def _handle_message(self, sender_id, msg):
        kind = msg.get("type")

        if kind == "message":
            recipient = msg.get("to")
            text = (msg.get("text") or "").strip()
            client_msg_id = msg.get("client_msg_id")
            is_experiment = bool(msg.get("experiment"))
            experiment_run_id = msg.get("experiment_run_id")
            if not recipient or not text:
                return
            if not db.get_user(recipient):
                self.send_to(sender_id, {
                    "type": "error",
                    "message": "Recipient not found"
                })
                return

            # Baseline experiment messages must look like ordinary socket
            # traffic on the wire, but they must not flood the user's chat
            # history or the server GUI.  Restrict this quiet path to the
            # server recipient and an integer experiment id.  Positive ids
            # are normal PCAP experiments; negative ids are live model tests.
            if is_experiment:
                try:
                    experiment_run_id = int(experiment_run_id)
                except Exception:
                    return
                if recipient != "server":
                    return
                if experiment_run_id >= 0:
                    run = db.get_experiment_run(experiment_run_id)
                    if (not run or run["target_user_id"] != sender_id or
                            run["status"] not in ("starting", "running")):
                        return

                self.send_to(sender_id, {
                    "type": "message_ack",
                    "id": None,
                    "from": sender_id,
                    "to": recipient,
                    "message_type": "text",
                    "text": text,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "client_msg_id": client_msg_id,
                    "experiment": True,
                    "experiment_run_id": experiment_run_id,
                })
                return

            mid = db.add_message(
                sender_id, recipient, text,
                client_msg_id=client_msg_id
            )
            row = db.get_message(mid)
            payload = {
                "type": "message",
                "id": mid,
                "from": sender_id,
                "to": recipient,
                "message_type": "text",
                "text": text,
                "created_at": row["created_at"],
                "client_msg_id": client_msg_id
            }

            if recipient == "server":
                db.mark_message_delivered(mid)
                self.event_queue.put(("message", payload))
            else:
                if self.send_to(recipient, payload):
                    db.mark_message_delivered(mid)

            self.send_to(sender_id, {
                "type": "message_ack",
                "id": mid,
                "from": sender_id,
                "to": recipient,
                "message_type": "text",
                "text": text,
                "created_at": row["created_at"],
                "client_msg_id": client_msg_id
            })

        elif kind == "experiment_status":
            callback = self.experiment_status_callback
            if callback:
                callback(sender_id, msg)
            self.event_queue.put(("experiment_status", sender_id, msg))

            if str(msg.get("status", "")) in ("completed", "stopped", "error"):
                with self._lock:
                    self._experiment_presence_users.discard(sender_id)
                # Publish one final authoritative presence snapshot instead of
                # hundreds of transient reconnect snapshots.
                self.broadcast_presence()

        elif kind == "ping":
            self.send_to(sender_id, {"type": "pong"})

    def send_to(self, user_id, payload):
        if user_id == "server":
            self.event_queue.put(("socket_event", payload))
            return True

        payload_type = payload.get("type") if isinstance(payload, dict) else None
        if payload_type == "experiment_force_stop":
            # A force-stop also releases presence suppression even if the
            # client socket is already gone.
            with self._lock:
                self._experiment_presence_users.discard(user_id)

        with self._lock:
            conn = self._clients.get(user_id)
            if not conn:
                return False
            try:
                self._send_raw(conn.sock, payload)
                if payload_type == "experiment_start":
                    self._experiment_presence_users.add(user_id)
                return True
            except Exception:
                return False

    def notify_task(self, user_id, transfer_id):
        self.send_to(user_id, {
            "type": "task_available",
            "transfer_id": transfer_id
        })

    def notify_transfer_status(self, user_id, transfer_id, status, text,
                               peer, message_id=None, created_at=None,
                               sender_id=None, recipient_id=None):
        self.send_to(user_id, {
            "type": "transfer_status",
            "transfer_id": transfer_id,
            "status": status,
            "text": text,
            "peer": peer,
            "message_id": message_id,
            "created_at": created_at,
            "sender_id": sender_id,
            "recipient_id": recipient_id
        })

    def broadcast_presence(self):
        online = self.online_users()
        users = []
        for row in db.list_users():
            uid = row["user_id"]
            users.append({
                "user_id": uid,
                "name": row["name"],
                "role": row["role"],
                "online": True if uid == "server" else uid in online
            })
        payload = {"type": "presence", "users": users}
        with self._lock:
            targets = list(self._clients.values())
        for conn in targets:
            try:
                self._send_raw(conn.sock, payload)
            except Exception:
                pass
        self.event_queue.put(("presence_snapshot", users))

    @staticmethod
    def _send_raw(sock, payload):
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        sock.sendall(data)
