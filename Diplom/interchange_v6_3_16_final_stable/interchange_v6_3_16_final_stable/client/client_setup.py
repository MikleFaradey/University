import json
import socket
from pathlib import Path

import auth_protocol
from client_config import (
    TOKEN_LENGTH,
    generate_client_token,
    save_client_config
)
from qt_compat import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTimer, QVBoxLayout, QWidget
)


class ClientSetupDialog(QDialog):
    def __init__(self, config_path, values, first_run=False, parent=None,
                 reauth=False, error_message=None, cache_path=None):
        QDialog.__init__(self, parent)
        self.config_path = Path(config_path).expanduser()
        self.first_run = first_run
        self.reauth = reauth
        self.error_message = error_message
        self.cache_path = (
            Path(cache_path).expanduser()
            if cache_path
            else None
        )
        self.saved_values = None
        self.assigned_user_id = str(values.get("user_id", "")).strip()
        self.client_token = str(values.get("client_token", "")).strip()
        self._waiting_after_request = False
        self._poll_busy = False

        if (
            len(self.client_token) != TOKEN_LENGTH
            or not self.client_token.isalnum()
        ):
            self.client_token = generate_client_token()
            self.assigned_user_id = ""

        self.setWindowTitle("Interchange Sign In")
        self.setMinimumWidth(580)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        self.title = QLabel("")
        self.title.setStyleSheet("font-size:20px; font-weight:700;")
        root.addWidget(self.title)

        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#596579;")
        root.addWidget(self.hint)

        form = QFormLayout()
        form.setSpacing(10)

        self.server_ip = QLineEdit(
            str(values.get("server_ip", ""))
        )
        self.server_ip.setPlaceholderText("Example: 10.100.3.20")

        self.display_name = QLineEdit(
            str(values.get("display_name", ""))
        )
        self.display_name.setPlaceholderText("Example: Ivan")

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Enter password")

        self.password_confirm_label = QLabel("Confirm password:")
        self.password_confirm = QLineEdit()
        self.password_confirm.setEchoMode(QLineEdit.Password)
        self.password_confirm.setPlaceholderText("Repeat password")

        self.download_dir = QLineEdit(
            str(values.get("download_dir", ""))
        )

        browse_row = QWidget()
        browse_layout = QHBoxLayout(browse_row)
        browse_layout.setContentsMargins(0, 0, 0, 0)
        browse_layout.setSpacing(7)
        browse_layout.addWidget(self.download_dir, 1)

        browse = QPushButton("Browse...")
        browse.clicked.connect(self.browse_download_dir)
        browse_layout.addWidget(browse)

        self.http_port = QSpinBox()
        self.http_port.setRange(1, 65535)
        self.http_port.setValue(
            int(values.get("http_port", 8080))
        )

        self.socket_port = QSpinBox()
        self.socket_port.setRange(1, 65535)
        self.socket_port.setValue(
            int(values.get("socket_port", 8081))
        )

        form.addRow("Name:", self.display_name)
        form.addRow("Server IP / host:", self.server_ip)
        form.addRow("Password:", self.password)
        form.addRow(
            self.password_confirm_label,
            self.password_confirm
        )
        form.addRow("Download folder:", browse_row)
        form.addRow("HTTP port:", self.http_port)
        form.addRow("Socket port:", self.socket_port)
        root.addLayout(form)

        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        if error_message:
            self._set_error(error_message)
        root.addWidget(self.test_result)

        buttons = QHBoxLayout()

        test = QPushButton("Test server")
        test.clicked.connect(self.test_server)
        buttons.addWidget(test)
        buttons.addStretch()

        self.switch_button = QPushButton("Use another account")
        self.switch_button.clicked.connect(self.use_another_account)
        buttons.addWidget(self.switch_button)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        self.request_button = QPushButton("")
        self.request_button.clicked.connect(self.primary_action)
        self.request_button.setDefault(True)
        buttons.addWidget(self.request_button)

        root.addLayout(buttons)

        self.setStyleSheet("""
            QDialog {
                background:#F7F9FC;
                color:#172033;
            }
            QLabel, QCheckBox {
                color:#172033;
                background:transparent;
            }
            QLineEdit, QSpinBox {
                color:#172033;
                background:#FFFFFF;
                border:1px solid #CBD5E1;
                border-radius:7px;
                padding:7px;
            }
            QPushButton {
                color:#172033;
                background:#FFFFFF;
                border:1px solid #CBD5E1;
                border-radius:7px;
                padding:8px 13px;
            }
            QPushButton:hover {
                color:#172033;
                background:#EEF4FF;
            }
            QPushButton:disabled {
                color:#94A3B8;
                background:#F8FAFC;
            }
        """)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1000)
        self.poll_timer.timeout.connect(self.poll_status)

        self._update_mode()
        self.password.setFocus()

        if self.assigned_user_id and self.server_ip.text().strip():
            QTimer.singleShot(250, self.check_existing_status)

    def _registration_mode(self):
        return not bool(self.assigned_user_id)

    def _update_mode(self):
        registration = self._registration_mode()
        self.password_confirm_label.setVisible(registration)
        self.password_confirm.setVisible(registration)

        self.display_name.setReadOnly(not registration)

        if registration:
            self.title.setText("Request Interchange access")
            self.hint.setText(
                "Choose a password. A private device token is generated "
                "automatically and is never shown or sent in plain form."
            )
            self.request_button.setText("Request access")
            self.request_button.setEnabled(True)
        else:
            self.title.setText("Sign in to Interchange")
            self.hint.setText(
                "This computer already has an approved device identity. "
                "Enter your password to complete authentication."
            )
            self.request_button.setText("Sign in")

        self.switch_button.setVisible(not registration)

    def _delete_old_cache(self):
        if self.cache_path is None:
            return

        base = str(self.cache_path)
        for suffix in ("", "-wal", "-shm"):
            path = Path(base + suffix)
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass

    def _reset_for_new_account(self):
        self.poll_timer.stop()
        self._poll_busy = False
        self._waiting_after_request = False
        self.saved_values = None
        self.error_message = None
        self.reauth = False

        self.assigned_user_id = ""
        self.client_token = generate_client_token()

        self.display_name.setReadOnly(False)
        self.display_name.setEnabled(True)
        self.password.setEnabled(True)
        self.password_confirm.setEnabled(True)
        self.server_ip.setEnabled(True)
        self.download_dir.setEnabled(True)
        self.http_port.setEnabled(True)
        self.socket_port.setEnabled(True)

        self.display_name.clear()
        self.password.clear()
        self.password_confirm.clear()

        self.request_button.setEnabled(True)
        self.request_button.setDefault(True)
        self.switch_button.setEnabled(True)

        self.test_result.clear()
        self._update_mode()

    def prepare_new_account(self):
        """Commit the already-confirmed local account reset.

        This method intentionally contains no confirmation dialog so callers
        can guarantee that a rejected confirmation has zero side effects.
        """
        self._delete_old_cache()
        self._reset_for_new_account()

        values = self.values()
        try:
            self._save(values)
        except Exception as exc:
            self._set_error(
                "Cannot reset account settings: %s" % exc
            )
            return False

        self.display_name.setFocus()
        return True

    def use_another_account(self):
        answer = QMessageBox.question(
            self,
            "Interchange",
            "Switch to a new account?\n\n"
            "The local chat history of the current account will be "
            "permanently deleted. A new device identity will be created "
            "and the administrator will need to approve it again.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if answer != QMessageBox.Yes:
            return False

        return self.prepare_new_account()

    def values(self):
        return {
            "server_ip": self.server_ip.text().strip(),
            "display_name": self.display_name.text().strip(),
            "client_token": self.client_token,
            "user_id": self.assigned_user_id,
            "download_dir": self.download_dir.text().strip(),
            "http_port": int(self.http_port.value()),
            "socket_port": int(self.socket_port.value()),
        }

    def validate_common(self):
        values = self.values()

        if not values["display_name"]:
            QMessageBox.warning(
                self,
                "Interchange",
                "Enter your name."
            )
            return None

        if not values["server_ip"]:
            QMessageBox.warning(
                self,
                "Interchange",
                "Enter the server IP or host name."
            )
            return None

        if not values["download_dir"]:
            QMessageBox.warning(
                self,
                "Interchange",
                "Select a download folder."
            )
            return None

        token = values["client_token"]
        if len(token) != TOKEN_LENGTH or not token.isalnum():
            QMessageBox.warning(
                self,
                "Interchange",
                "Client authorization token is invalid."
            )
            return None

        return values

    def validate_password(self, registration=False):
        password = self.password.text()
        try:
            auth_protocol.validate_password(password)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Interchange",
                str(exc)
            )
            return None

        if registration and password != self.password_confirm.text():
            QMessageBox.warning(
                self,
                "Interchange",
                "Passwords do not match."
            )
            return None

        return password

    def browse_download_dir(self):
        current = (
            self.download_dir.text().strip()
            or str(Path.home())
        )
        path = QFileDialog.getExistingDirectory(
            self,
            "Select download folder",
            current
        )
        if path:
            self.download_dir.setText(path)

    def _open_socket(self, values):
        sock = socket.create_connection(
            (
                values["server_ip"],
                values["socket_port"]
            ),
            timeout=4.0
        )
        sock.settimeout(4.0)
        return sock

    @staticmethod
    def _send(sock, payload):
        sock.sendall(
            (
                json.dumps(
                    payload,
                    ensure_ascii=True
                )
                + "\n"
            ).encode("utf-8")
        )

    @staticmethod
    def _recv(sock):
        buffer = b""
        while b"\n" not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
        if b"\n" not in buffer:
            raise RuntimeError("No response from server")
        raw = buffer.split(b"\n", 1)[0]
        return json.loads(raw.decode("utf-8"))

    def _save(self, values):
        Path(values["download_dir"]).expanduser().mkdir(
            parents=True,
            exist_ok=True
        )
        save_client_config(
            values,
            self.config_path
        )

    def _set_error(self, message):
        self.test_result.setStyleSheet(
            "color:#B42318; font-weight:600;"
        )
        self.test_result.setText(message)

    def _set_success(self, message):
        self.test_result.setStyleSheet(
            "color:#15803D; font-weight:600;"
        )
        self.test_result.setText(message)

    def _set_neutral(self, message):
        self.test_result.setStyleSheet(
            "color:#596579; font-weight:600;"
        )
        self.test_result.setText(message)

    def _status_exchange(self, values):
        sock = None
        try:
            sock = self._open_socket(values)
            self._send(sock, {
                "type": "auth_status",
                "token_id": auth_protocol.token_id(
                    values["client_token"]
                )
            })
            return self._recv(sock)
        except Exception as exc:
            return {
                "type": "auth_error",
                "message": str(exc)
            }
        finally:
            try:
                if sock is not None:
                    sock.close()
            except Exception:
                pass

    def _register(self, values, password):
        material = auth_protocol.registration_material(
            password,
            values["client_token"]
        )
        sock = None
        try:
            sock = self._open_socket(values)
            self._send(sock, {
                "type": "auth_register",
                "name": values["display_name"],
                "token_id": material["token_id"],
                "password_salt": material["password_salt"],
                "kdf_iterations": material["kdf_iterations"],
                "token_verifier": material["token_verifier"],
                "password_verifier": material["password_verifier"]
            })
            response = self._recv(sock)
            response["password_secret"] = material["password_secret"]
            return response
        except Exception as exc:
            return {
                "type": "auth_error",
                "message": str(exc)
            }
        finally:
            try:
                if sock is not None:
                    sock.close()
            except Exception:
                pass

    def _authenticate(self, values, password):
        sock = None
        try:
            token_identifier = auth_protocol.token_id(
                values["client_token"]
            )
            material = auth_protocol.new_client_auth_material()
            sock = self._open_socket(values)
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
            challenge = self._recv(sock)
            if challenge.get("type") != "auth_challenge":
                return challenge

            password_secret = auth_protocol.derive_password_secret(
                password,
                values["client_token"],
                challenge.get("password_salt"),
                challenge.get("kdf_iterations")
            )
            token_secret = auth_protocol.derive_token_secret(
                values["client_token"]
            )
            state = auth_protocol.client_finish_auth(
                material,
                password_secret,
                token_secret,
                token_identifier,
                challenge
            )
            self._send(sock, {
                "type": "auth_proof",
                "password_response": state["password_response_hex"],
                "token_response": state["token_response_hex"],
                "client_proof": state["client_proof"]
            })
            result = self._recv(sock)
            if result.get("type") != "auth_ok":
                return result

            auth_protocol.verify_server_finish(
                state,
                result
            )
            result["password_secret"] = password_secret
            return result
        except Exception as exc:
            return {
                "type": "auth_error",
                "message": str(exc)
            }
        finally:
            try:
                if sock is not None:
                    sock.close()
            except Exception:
                pass

    def _store_user_id(self, response):
        user_id = str(response.get("user_id", "")).strip()
        if user_id:
            self.assigned_user_id = user_id
            values = self.values()
            try:
                self._save(values)
            except Exception as exc:
                self._set_error(
                    "Cannot save settings: %s" % exc
                )
                return False
            self._update_mode()
        return True

    def _finish_success(self, values, response):
        user_id = str(response.get("user_id", "")).strip()
        password_secret = response.get("password_secret")
        if not user_id or password_secret is None:
            self._set_error("Authentication result is incomplete.")
            return

        self.assigned_user_id = user_id
        server_name = str(response.get("name", "")).strip()
        if server_name:
            self.display_name.setText(server_name)
        values = self.values()

        try:
            self._save(values)
        except Exception as exc:
            self._set_error(
                "Cannot save settings: %s" % exc
            )
            return

        values["password_secret"] = int(password_secret)
        self.saved_values = values
        self.poll_timer.stop()
        self.password.clear()
        self.password_confirm.clear()
        self._set_success(
            "Authentication successful. Opening Interchange..."
        )
        QTimer.singleShot(350, self.accept)

    def _handle_status(self, response, from_poll=False):
        kind = response.get("type")

        if kind in (
            "auth_pending",
            "auth_approved",
            "auth_blocked",
            "auth_rejected"
        ):
            if not self._store_user_id(response):
                return

        if kind == "auth_pending":
            self._set_neutral(
                "Waiting for administrator approval..."
            )
            self.request_button.setEnabled(False)
            if not self.poll_timer.isActive():
                self.poll_timer.start()
            return

        if kind == "auth_approved":
            self.poll_timer.stop()
            self.request_button.setEnabled(True)
            self._update_mode()
            self._set_success(
                "Access approved. Enter your password to sign in."
            )
            if (
                from_poll
                and self._waiting_after_request
                and self.password.text()
            ):
                self.sign_in()
            return

        if kind == "auth_blocked":
            self.poll_timer.stop()
            self.request_button.setEnabled(False)
            self._set_error(
                "Access blocked by administrator."
            )
            return

        if kind == "auth_rejected":
            self.poll_timer.stop()
            self.client_token = generate_client_token()
            self.assigned_user_id = ""
            self._waiting_after_request = False
            self.request_button.setEnabled(True)
            self._update_mode()
            self._set_error(
                "Access request rejected. A new private device identity "
                "was generated. You can submit a new request."
            )
            try:
                self._save(self.values())
            except Exception:
                pass
            return

        if kind == "auth_required":
            self.poll_timer.stop()
            self.assigned_user_id = ""
            self._waiting_after_request = False
            self.request_button.setEnabled(True)
            self._update_mode()
            try:
                self._save(self.values())
            except Exception:
                pass
            if from_poll:
                self._set_neutral(
                    "This device is not registered. Request access."
                )
            return

        if kind == "auth_error":
            if not from_poll:
                self._set_error(
                    response.get(
                        "message",
                        "Authorization failed."
                    )
                )
            return

    def test_server(self):
        values = self.validate_common()
        if not values:
            return

        sock = None
        try:
            sock = self._open_socket(values)
            self._set_success("Server is reachable.")
        except Exception as exc:
            self._set_error(
                "Server is unavailable: %s" % exc
            )
        finally:
            try:
                if sock is not None:
                    sock.close()
            except Exception:
                pass

    def primary_action(self):
        if self._registration_mode():
            self.request_access()
        else:
            self.sign_in()

    def request_access(self):
        values = self.validate_common()
        if not values:
            return
        password = self.validate_password(registration=True)
        if password is None:
            return

        self._set_neutral("Sending authorization request...")
        response = self._register(values, password)
        kind = response.get("type")

        if kind in ("auth_pending", "auth_approved"):
            if not self._store_user_id(response):
                return
            self._waiting_after_request = True

        if kind == "auth_approved":
            auth_result = self._authenticate(
                self.values(),
                password
            )
            if auth_result.get("type") == "auth_ok":
                self._finish_success(
                    self.values(),
                    auth_result
                )
                return
            self._handle_status(auth_result)
            return

        self._handle_status(response)

    def sign_in(self):
        values = self.validate_common()
        if not values:
            return
        password = self.validate_password(registration=False)
        if password is None:
            return

        self._set_neutral("Authenticating...")
        response = self._authenticate(values, password)

        if response.get("type") == "auth_ok":
            self._finish_success(values, response)
            return

        self._handle_status(response)
        if response.get("type") == "auth_error":
            self._set_error(
                response.get(
                    "message",
                    "Authentication failed."
                )
            )

    def check_existing_status(self):
        values = self.validate_common()
        if not values:
            return
        response = self._status_exchange(values)
        self._handle_status(response)

    def poll_status(self):
        if self._poll_busy:
            return
        self._poll_busy = True
        try:
            response = self._status_exchange(
                self.values()
            )
            if response.get("type") == "auth_error":
                self._set_neutral(
                    "Waiting for server..."
                )
                return
            self._handle_status(
                response,
                from_poll=True
            )
        finally:
            self._poll_busy = False


def dialog_exec(dialog):
    if hasattr(dialog, "exec"):
        return dialog.exec()
    return dialog.exec_()
