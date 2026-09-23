import argparse
import json
import sqlite3
import time
from pathlib import Path

import requests

import db
from server_config import default_config_path, load_server_config
from qt_compat import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem,
    QTimer, QVBoxLayout, QWidget, Qt, app_exec
)


APP_NAME = "Interchange Admin"

ANOMALY_TYPES = [
    ("NORMAL", "Normal traffic"),
    ("HIGH_REQUEST_RATE", "High request rate"),
    ("FREQUENT_RECONNECT", "Frequent reconnects"),
    ("HIGH_FREQUENCY_SMALL_TRANSFERS", "High-frequency small transfers"),
]

SCENARIO_PRESETS = {
    "NORMAL": {
        "duration_sec": 30
    },
    "HIGH_REQUEST_RATE": {
        "duration_sec": 30,
        "requests_per_sec": 30
    },
    "FREQUENT_RECONNECT": {
        "duration_sec": 30,
        "interval_sec": 0.1
    },
    "HIGH_FREQUENCY_SMALL_TRANSFERS": {
        "duration_sec": 30,
        "transfers_per_sec": 15,
        "payload_bytes": 32
    },
}


class AdminWindow(QMainWindow):
    def __init__(self, args):
        QMainWindow.__init__(self)
        self.args = args
        self.online_map = {}
        self.server_online = False

        db.configure_db(args.db)
        db.init_db()

        self.setWindowTitle(APP_NAME)
        self.resize(1050, 700)
        # Long admin pages are scrollable, so the window can remain usable on
        # smaller laptop/VM displays and under high-DPI scaling.
        self.setMinimumSize(760, 500)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Interchange Admin")
        title.setObjectName("Title")
        header.addWidget(title)
        header.addStretch()

        self.server_dot = QLabel()
        self.server_dot.setFixedSize(10, 10)
        self.server_status = QLabel("Server unavailable")
        self.server_status.setObjectName("ServerStatus")
        header.addWidget(self.server_dot)
        header.addSpacing(5)
        header.addWidget(self.server_status)
        layout.addLayout(header)

        live_hint = QLabel(
            "User changes are applied to the running server automatically."
        )
        live_hint.setObjectName("Hint")
        layout.addWidget(live_hint)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.users_tab = QWidget()
        self.anomalies_tab = QWidget()
        self.model_tab = QWidget()
        self.tabs.addTab(self.users_tab, "Users")
        self.tabs.addTab(self.anomalies_tab, "Experiment timeline")
        self.tabs.addTab(self.model_tab, "Model & traffic")

        self.build_users_tab()
        self.build_anomalies_tab()
        self.build_model_tab()
        self.apply_style()

        self.refresh_users()
        if hasattr(self, "runs_table"):
            self.refresh_runs()
        self.refresh_server_status()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_server_status)
        self.timer.start(2500)

        # Model results are defined per fixed one-second window, so the Admin
        # monitor refreshes at the same cadence.
        self.model_timer = QTimer(self)
        self.model_timer.timeout.connect(self.refresh_model_monitor)
        self.model_timer.timeout.connect(self.refresh_model_test)
        self.model_timer.start(1000)
        self.refresh_model_monitor()
        self.refresh_model_test()

        # Training capture progress is time-based and should feel live without
        # rebuilding the full user table several times per second.
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self.refresh_training_progress)
        self.progress_timer.start(500)
        self.refresh_training_progress()


    def build_users_tab(self):
        layout = QVBoxLayout(self.users_tab)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(12)

        form_box = QGroupBox("Selected client")
        form = QFormLayout(form_box)

        self.user_id = QLineEdit()
        self.user_id.setReadOnly(True)

        self.user_name = QLineEdit()
        self.user_name.setPlaceholderText("Display name")

        self.user_ip = QLineEdit()
        self.user_ip.setReadOnly(True)

        self.user_status = QLineEdit()
        self.user_status.setReadOnly(True)

        form.addRow("Client ID:", self.user_id)
        form.addRow("Name:", self.user_name)
        form.addRow("Last IP:", self.user_ip)
        form.addRow("Access:", self.user_status)

        buttons = QHBoxLayout()

        self.save_user_btn = QPushButton("Save name")
        self.clear_user_btn = QPushButton("Clear")

        self.save_user_btn.clicked.connect(self.save_user)
        self.clear_user_btn.clicked.connect(
            self.clear_user_form
        )

        buttons.addWidget(self.save_user_btn)
        buttons.addWidget(self.clear_user_btn)
        buttons.addStretch()

        form.addRow(buttons)
        layout.addWidget(form_box)

        self.users_table = QTableWidget(0, 7)
        self.users_table.setHorizontalHeaderLabels([
            "Client ID",
            "Name",
            "Last IP",
            "Access",
            "Network",
            "Created",
            "Last seen"
        ])
        self.users_table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )
        self.users_table.setSelectionMode(
            QAbstractItemView.SingleSelection
        )
        self.users_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.users_table.itemSelectionChanged.connect(
            self.load_selected_user
        )

        header = self.users_table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeToContents
        )
        header.setSectionResizeMode(
            1,
            QHeaderView.Stretch
        )
        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeToContents
        )
        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeToContents
        )
        header.setSectionResizeMode(
            4,
            QHeaderView.ResizeToContents
        )
        header.setSectionResizeMode(
            5,
            QHeaderView.ResizeToContents
        )
        header.setSectionResizeMode(
            6,
            QHeaderView.ResizeToContents
        )

        layout.addWidget(self.users_table, 1)

        row = QHBoxLayout()

        refresh = QPushButton("Refresh")
        approve = QPushButton("Approve")
        reject = QPushButton("Reject")
        block = QPushButton("Block")

        refresh.clicked.connect(self.refresh_users)
        approve.clicked.connect(
            lambda: self.set_selected_status("APPROVED")
        )
        reject.clicked.connect(
            lambda: self.set_selected_status("REJECTED")
        )
        block.clicked.connect(
            lambda: self.set_selected_status("BLOCKED")
        )

        row.addWidget(refresh)
        row.addWidget(approve)
        row.addWidget(reject)
        row.addWidget(block)
        row.addStretch()

        layout.addLayout(row)

    def save_user(self):
        user_id = self.user_id.text().strip()
        name = self.user_name.text().strip()

        if not user_id:
            self.warn("Select a client first.")
            return

        if user_id == "server":
            self.warn(
                "The system user server cannot be modified."
            )
            return

        if not name:
            self.warn("Enter a display name.")
            return

        try:
            db.update_user(
                user_id,
                name=name
            )
        except Exception as exc:
            self.warn(str(exc))
            return

        self.refresh_users()
        self.refresh_timeline_targets()

    def clear_user_form(self):
        self.user_id.clear()
        self.user_name.clear()
        self.user_ip.clear()
        self.user_status.clear()

    def load_selected_user(self):
        row_index = self.users_table.currentRow()
        if row_index < 0:
            return

        user_id = self.users_table.item(
            row_index,
            0
        ).text()

        row = db.get_user(user_id)
        if not row:
            return

        self.user_id.setText(row["user_id"])
        self.user_name.setText(row["name"])
        self.user_ip.setText(row["ip"] or "-")

        if row["role"] == "server":
            self.user_status.setText("SYSTEM")
        else:
            self.user_status.setText(
                row["auth_status"]
            )

    def selected_user_id(self):
        row = self.users_table.currentRow()
        if row < 0:
            return None
        return self.users_table.item(row, 0).text()

    def set_selected_status(self, status):
        user_id = self.selected_user_id()

        if not user_id:
            self.warn("Select a client first.")
            return

        if user_id == "server":
            self.warn(
                "The system user server cannot be modified."
            )
            return

        try:
            db.set_user_auth_status(
                user_id,
                status
            )
        except Exception as exc:
            self.warn(str(exc))
            return

        self.refresh_users()
        self.refresh_timeline_targets()

    def refresh_users(self):
        rows = db.list_all_users()
        self.users_table.setRowCount(len(rows))

        for r, row in enumerate(rows):
            uid = row["user_id"]

            if uid == "server":
                access = "SYSTEM"
                online = self.server_online
            else:
                access = row["auth_status"]
                online = self.online_map.get(uid)

            values = [
                uid,
                row["name"],
                row["ip"] or "-",
                access,
                self.online_text(online),
                row["created_at"] or "-",
                row["last_seen"] or "-"
            ]

            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c in (3, 4):
                    item.setTextAlignment(Qt.AlignCenter)
                self.users_table.setItem(r, c, item)


    def build_anomalies_tab(self):
        # The experiment page can grow substantially (timeline + progress +
        # recent runs). Keep it usable on small displays instead of forcing the
        # main window beyond the available screen height.
        outer = QVBoxLayout(self.anomalies_tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.experiment_scroll = QScrollArea()
        self.experiment_scroll.setWidgetResizable(True)
        self.experiment_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.experiment_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        experiment_content = QWidget()
        layout = QVBoxLayout(experiment_content)
        layout.setContentsMargins(4, 12, 8, 8)
        layout.setSpacing(10)
        self.experiment_scroll.setWidget(experiment_content)
        outer.addWidget(self.experiment_scroll)

        intro = QLabel(
            "Build one continuous experiment. Normal baseline traffic runs for "
            "the entire PCAP. Each timeline phase either keeps only NORMAL or "
            "adds one controlled anomaly on top of the same baseline."
        )
        intro.setWordWrap(True)
        intro.setObjectName("Hint")
        layout.addWidget(intro)

        run_box = QGroupBox("Experiment")
        form = QFormLayout(run_box)

        self.timeline_target = QComboBox()
        self.timeline_baseline_dir = QLineEdit()
        self.timeline_baseline_dir.setPlaceholderText(
            "/home/user/ml_baseline"
        )
        self.timeline_baseline_dir.setToolTip(
            "Path on the selected CLIENT device."
        )

        form.addRow("Client:", self.timeline_target)
        form.addRow("Client baseline folder:", self.timeline_baseline_dir)
        layout.addWidget(run_box)

        timeline_title = QHBoxLayout()
        timeline_label = QLabel("Timeline phases")
        timeline_label.setStyleSheet("font-weight:700;")
        timeline_title.addWidget(timeline_label)
        timeline_title.addStretch()

        add_phase = QPushButton("Add phase")
        delete_phase = QPushButton("Delete selected")
        load_example = QPushButton("Load example")
        validate_btn = QPushButton("Validate")

        add_phase.clicked.connect(self.add_timeline_phase)
        delete_phase.clicked.connect(self.delete_timeline_phase)
        load_example.clicked.connect(self.load_timeline_example)
        validate_btn.clicked.connect(self.validate_timeline_dialog)

        timeline_title.addWidget(add_phase)
        timeline_title.addWidget(delete_phase)
        timeline_title.addWidget(load_example)
        timeline_title.addWidget(validate_btn)
        layout.addLayout(timeline_title)

        hint = QLabel(
            "Use half-open intervals [start, end). Boundaries use whole "
            "seconds and phases must be continuous. Example: 0-30 NORMAL, "
            "30-50 FREQUENT_RECONNECT."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        self.timeline_table = QTableWidget(0, 4)
        self.timeline_table.setHorizontalHeaderLabels([
            "Start, s", "End, s", "Mode", "Parameters JSON"
        ])
        self.timeline_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.timeline_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.timeline_table.setMinimumHeight(210)

        header = self.timeline_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        layout.addWidget(self.timeline_table, 1)

        action_row = QHBoxLayout()
        run = QPushButton("Run experiment + PCAP")
        stop = QPushButton("Stop selected run")
        delete_run = QPushButton("Force stop & delete")
        delete_run.setObjectName("DangerButton")
        delete_run.setToolTip(
            "Works even for a stuck active run: stops local PCAP, resets the "
            "client experiment slot, removes the run record and its partial "
            "PCAP/metadata files."
        )
        run.clicked.connect(self.run_timeline_experiment)
        stop.clicked.connect(self.stop_selected_run)
        delete_run.clicked.connect(self.delete_selected_run)
        action_row.addStretch()
        action_row.addWidget(run)
        action_row.addWidget(stop)
        action_row.addWidget(delete_run)
        layout.addLayout(action_row)

        progress_box = QGroupBox("Training PCAP preparation")
        progress_layout = QVBoxLayout(progress_box)
        self.training_pcap_progress = QProgressBar()
        self.training_pcap_progress.setRange(0, 100)
        self.training_pcap_progress.setValue(0)
        self.training_pcap_progress.setFormat("0%")
        self.training_pcap_details = QLabel("No active experiment")
        self.training_pcap_details.setObjectName("Hint")
        self.training_pcap_details.setWordWrap(True)
        progress_layout.addWidget(self.training_pcap_progress)
        progress_layout.addWidget(self.training_pcap_details)
        layout.addWidget(progress_box)

        runs_title = QLabel("Recent experiment runs / PCAP files")
        runs_title.setStyleSheet("font-weight:700; margin-top:8px;")
        layout.addWidget(runs_title)

        self.runs_table = QTableWidget(0, 8)
        self.runs_table.setHorizontalHeaderLabels([
            "Run", "Client", "Type", "Status", "Progress", "Started", "PCAP", "Error"
        ])
        self.runs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.runs_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.runs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.runs_table.setMinimumHeight(210)

        runs_header = self.runs_table.horizontalHeader()
        runs_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        runs_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        runs_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        runs_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        runs_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        runs_header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        runs_header.setSectionResizeMode(6, QHeaderView.Stretch)
        runs_header.setSectionResizeMode(7, QHeaderView.Stretch)
        layout.addWidget(self.runs_table, 1)

        self.refresh_timeline_targets()
        self.load_timeline_example()
        self.refresh_runs()

    def _mode_combo(self, selected="NORMAL"):
        combo = QComboBox()
        for code, label in ANOMALY_TYPES:
            combo.addItem(label, code)
        index = combo.findData(selected)
        if index >= 0:
            combo.setCurrentIndex(index)
        return combo

    def add_timeline_phase(self, start_sec=None, end_sec=None,
                           mode="NORMAL", params=None):
        row = self.timeline_table.rowCount()

        if start_sec is None:
            if row == 0:
                start_sec = 0
            else:
                item = self.timeline_table.item(row - 1, 1)
                try:
                    start_sec = int(item.text())
                except Exception:
                    start_sec = row * 30

        if end_sec is None:
            end_sec = int(start_sec) + 30

        self.timeline_table.insertRow(row)
        self.timeline_table.setItem(
            row, 0, QTableWidgetItem(str(int(start_sec)))
        )
        self.timeline_table.setItem(
            row, 1, QTableWidgetItem(str(int(end_sec)))
        )
        self.timeline_table.setCellWidget(
            row, 2, self._mode_combo(mode)
        )
        self.timeline_table.setItem(
            row, 3,
            QTableWidgetItem(
                json.dumps(params or {}, sort_keys=True)
            )
        )

    def delete_timeline_phase(self):
        row = self.timeline_table.currentRow()
        if row >= 0:
            self.timeline_table.removeRow(row)

    def load_timeline_example(self):
        self.timeline_table.setRowCount(0)
        self.add_timeline_phase(0, 30, "NORMAL", {})
        self.add_timeline_phase(
            30, 50, "FREQUENT_RECONNECT",
            {"interval_sec": 0.1}
        )
        self.add_timeline_phase(50, 80, "NORMAL", {})
        self.add_timeline_phase(
            80, 110, "HIGH_REQUEST_RATE",
            {"requests_per_sec": 30}
        )
        self.add_timeline_phase(110, 140, "NORMAL", {})
        self.add_timeline_phase(
            140, 170, "HIGH_FREQUENCY_SMALL_TRANSFERS",
            {"transfers_per_sec": 15, "payload_bytes": 32}
        )

    def collect_timeline(self):
        phases = []
        previous_end = 0

        if self.timeline_table.rowCount() == 0:
            raise RuntimeError("Timeline is empty")

        for row in range(self.timeline_table.rowCount()):
            start_item = self.timeline_table.item(row, 0)
            end_item = self.timeline_table.item(row, 1)
            params_item = self.timeline_table.item(row, 3)
            combo = self.timeline_table.cellWidget(row, 2)

            try:
                start_sec = int(start_item.text().strip())
                end_sec = int(end_item.text().strip())
            except Exception:
                raise RuntimeError(
                    "Row %d start/end must be integer seconds" % (row + 1)
                )

            mode = str(combo.currentData())
            raw_params = (
                params_item.text().strip()
                if params_item is not None else "{}"
            ) or "{}"

            try:
                params = json.loads(raw_params)
            except Exception:
                raise RuntimeError(
                    "Row %d parameters are not valid JSON" % (row + 1)
                )

            if not isinstance(params, dict):
                raise RuntimeError(
                    "Row %d parameters must be a JSON object" % (row + 1)
                )
            if start_sec != previous_end:
                raise RuntimeError(
                    "Row %d must start at %d seconds"
                    % (row + 1, previous_end)
                )
            if end_sec <= start_sec:
                raise RuntimeError(
                    "Row %d end must be greater than start" % (row + 1)
                )
            phases.append({
                "start_sec": start_sec,
                "end_sec": end_sec,
                "label": mode,
                "params": params
            })
            previous_end = end_sec

        if previous_end > 3600:
            raise RuntimeError("Experiment cannot exceed 3600 seconds")

        return phases

    def validate_timeline_dialog(self):
        try:
            phases = self.collect_timeline()
        except Exception as exc:
            self.warn(str(exc))
            return

        QMessageBox.information(
            self,
            APP_NAME,
            "Timeline is valid.\nDuration: %s seconds\nPhases: %s"
            % (phases[-1]["end_sec"], len(phases))
        )

    def refresh_timeline_targets(self):
        current = self.timeline_target.currentData()
        self.timeline_target.clear()

        for row in db.list_all_users():
            if row["role"] != "client" or not row["active"]:
                continue
            self.timeline_target.addItem(
                "%s (%s)" % (row["name"], row["user_id"]),
                row["user_id"]
            )

        if current:
            index = self.timeline_target.findData(current)
            if index >= 0:
                self.timeline_target.setCurrentIndex(index)

    def run_timeline_experiment(self):
        if not self.server_online:
            self.warn("Server is unavailable.")
            return

        target = self.timeline_target.currentData()
        if not target:
            self.warn("Select a target client.")
            return

        baseline_dir = self.timeline_baseline_dir.text().strip()
        if not baseline_dir:
            self.warn("Enter the baseline folder path on the client.")
            return

        try:
            timeline = self.collect_timeline()
        except Exception as exc:
            self.warn(str(exc))
            return

        try:
            response = requests.post(
                self.args.server_url.rstrip("/") + "/admin/experiment/start",
                json={
                    "target_user_id": target,
                    "baseline_dir": baseline_dir,
                    "timeline": timeline
                },
                timeout=8
            )
            data = response.json()
            if response.status_code >= 400:
                raise RuntimeError(
                    data.get("error", "Cannot start experiment")
                )
        except Exception as exc:
            self.warn(str(exc))
            return

        QMessageBox.information(
            self,
            APP_NAME,
            "Experiment run #%s started.\nDuration: %s s\nPCAP: %s"
            % (
                data.get("run_id"),
                data.get("total_duration_sec"),
                data.get("pcap_path")
            )
        )
        self.refresh_runs()

    def selected_run_id(self):
        row = self.runs_table.currentRow()
        if row < 0:
            return None
        return int(self.runs_table.item(row, 0).text())

    def stop_selected_run(self):
        run_id = self.selected_run_id()
        if run_id is None:
            self.warn("Select an experiment run first.")
            return

        try:
            response = requests.post(
                self.args.server_url.rstrip("/") + "/admin/experiment/stop",
                json={"run_id": run_id},
                timeout=5
            )
            data = response.json()
            if response.status_code >= 400:
                raise RuntimeError(
                    data.get("error", "Cannot stop experiment")
                )
        except Exception as exc:
            self.warn(str(exc))
            return

        self.refresh_runs()

    def delete_selected_run(self):
        run_id = self.selected_run_id()
        if run_id is None:
            self.warn("Select an experiment run first.")
            return

        row = db.get_experiment_run(run_id)
        status = str(row["status"]) if row else "unknown"
        active = status in ("starting", "running", "stopping")
        if active:
            text = (
                "Experiment #%s is still %s.\n\n"
                "Force stop it and delete the run together with its partial "
                "PCAP/metadata files?\n\n"
                "This releases the client immediately so a new test can be "
                "started even if the old worker is stuck."
            ) % (run_id, status)
        else:
            text = (
                "Delete experiment #%s and its PCAP/metadata files?\n\n"
                "This cannot be undone."
            ) % run_id

        answer = QMessageBox.question(
            self,
            APP_NAME,
            text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        try:
            response = requests.post(
                self.args.server_url.rstrip("/") + "/admin/experiment/delete",
                json={"run_id": run_id, "delete_files": True},
                timeout=12
            )
            data = response.json()
            if response.status_code >= 400:
                raise RuntimeError(
                    data.get("error", "Cannot delete experiment")
                )
        except Exception as exc:
            self.warn(str(exc))
            return

        self.refresh_runs()

    @staticmethod
    def _run_progress_info(row):
        status = str(row["status"] or "")
        try:
            params = json.loads(row["params_json"] or "{}")
        except Exception:
            params = {}
        timeline = params.get("timeline") or []
        total = 0
        if timeline:
            try:
                total = int(timeline[-1]["end_sec"])
            except Exception:
                total = 0

        started = row["experiment_start_epoch"]
        finished = row["experiment_end_epoch"]
        now = time.time()
        elapsed = 0.0
        if started is not None:
            try:
                end_value = float(finished) if finished is not None else now
                elapsed = max(0.0, end_value - float(started))
            except Exception:
                elapsed = 0.0

        active = status in ("starting", "running", "stopping")
        if status == "completed":
            percent = 100
        elif total > 0:
            percent = int((min(float(total), elapsed) / float(total)) * 100.0)
            if active:
                percent = min(99, percent)
        else:
            percent = 0

        phase = None
        if timeline and started is not None:
            relative = min(max(0.0, elapsed), float(total or 0))
            for item in timeline:
                try:
                    if (relative >= float(item["start_sec"]) and
                            relative < float(item["end_sec"])):
                        phase = str(item.get("label") or "")
                        break
                except Exception:
                    pass

        if active and total > 0 and elapsed >= float(total):
            detail = "Finalizing PCAP capture..."
        elif active:
            remaining = max(0, int(round(float(total) - elapsed))) if total else 0
            detail = "Elapsed: %d s • Remaining: %d s" % (int(elapsed), remaining)
            if phase:
                detail += " • Current phase: %s" % phase
        elif status == "completed":
            detail = "PCAP ready • %d s planned" % total
        elif status in ("stopped", "error", "timeout"):
            detail = "%s at %d%%" % (status.capitalize(), percent)
            if row["error"]:
                detail += " • %s" % row["error"]
        else:
            detail = status or "Idle"

        return {
            "percent": max(0, min(100, percent)),
            "detail": detail,
            "phase": phase,
            "elapsed": elapsed,
            "total": total,
            "active": active,
        }

    def _progress_row_for_panel(self, rows):
        selected_id = self.selected_run_id() if hasattr(self, "runs_table") else None
        if selected_id is not None:
            for row in rows:
                if int(row["id"]) == int(selected_id):
                    return row
        for row in rows:
            if str(row["status"]) in ("starting", "running", "stopping"):
                return row
        return rows[0] if rows else None

    def refresh_training_progress(self):
        if not hasattr(self, "training_pcap_progress"):
            return
        try:
            rows = db.list_experiment_runs(100)
        except Exception:
            return
        row = self._progress_row_for_panel(rows)
        if row is None:
            self.training_pcap_progress.setValue(0)
            self.training_pcap_progress.setFormat("0%")
            self.training_pcap_details.setText("No experiment selected")
            return
        info = self._run_progress_info(row)
        value = int(info["percent"])
        self.training_pcap_progress.setValue(value)
        self.training_pcap_progress.setFormat("%d%%" % value)
        self.training_pcap_details.setText(
            "Run #%s • %s • %s" % (row["id"], row["status"], info["detail"])
        )

        # Update only progress widgets in the table. The full table is rebuilt
        # by the normal server-status refresh every 2.5 seconds.
        for table_row in range(self.runs_table.rowCount()):
            item = self.runs_table.item(table_row, 0)
            if item is None:
                continue
            try:
                table_id = int(item.text())
            except Exception:
                continue
            source = next((r for r in rows if int(r["id"]) == table_id), None)
            if source is None:
                continue
            source_info = self._run_progress_info(source)
            bar = self.runs_table.cellWidget(table_row, 4)
            if bar is None:
                bar = QProgressBar()
                bar.setRange(0, 100)
                self.runs_table.setCellWidget(table_row, 4, bar)
            bar.setValue(int(source_info["percent"]))
            bar.setFormat("%d%%" % int(source_info["percent"]))
            bar.setToolTip(source_info["detail"])

    def refresh_runs(self):
        rows = db.list_experiment_runs(100)
        self.runs_table.setRowCount(len(rows))

        for r, row in enumerate(rows):
            values = [
                row["id"],
                row["target_user_id"],
                row["anomaly_type"],
                row["status"],
                None,
                row["started_at"] or "",
                row["pcap_path"] or "",
                row["error"] or "",
            ]
            for c, value in enumerate(values):
                if c == 4:
                    continue
                self.runs_table.setItem(
                    r, c, QTableWidgetItem(str(value))
                )
            info = self._run_progress_info(row)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(info["percent"]))
            bar.setFormat("%d%%" % int(info["percent"]))
            bar.setToolTip(info["detail"])
            self.runs_table.setCellWidget(r, 4, bar)
        self.refresh_training_progress()


    def build_model_tab(self):
        layout = QVBoxLayout(self.model_tab)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(10)

        intro = QLabel(
            "Live mode bypasses CSV: packets are aggregated in RAM into the "
            "same fixed 1-second feature vector used by the dataset parser, "
            "then sent directly to the loaded classifier. Automatic blocking "
            "is disabled in this version."
        )
        intro.setWordWrap(True)
        intro.setObjectName("Hint")
        layout.addWidget(intro)

        model_box = QGroupBox("Model")
        model_layout = QVBoxLayout(model_box)
        path_row = QHBoxLayout()
        self.model_path = QLineEdit()
        self.model_path.setPlaceholderText("Select a trusted .joblib / .pkl model file")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self.browse_model_file)
        path_row.addWidget(self.model_path, 1)
        path_row.addWidget(browse)
        model_layout.addLayout(path_row)

        button_row = QHBoxLayout()
        self.model_load_btn = QPushButton("Load model")
        self.model_unload_btn = QPushButton("Unload")
        self.model_load_btn.clicked.connect(self.load_model_file)
        self.model_unload_btn.clicked.connect(self.unload_model_file)
        button_row.addWidget(self.model_load_btn)
        button_row.addWidget(self.model_unload_btn)
        button_row.addStretch()
        model_layout.addLayout(button_row)

        model_info = QFormLayout()
        self.model_status_value = QLabel("Not loaded")
        self.model_schema_value = QLabel("Fixed window: 1 second")
        self.model_classes_value = QLabel("-")
        self.model_capture_value = QLabel("Idle")
        self.model_mode_value = QLabel("Observation only — automatic blocking disabled")
        self.model_status_value.setWordWrap(True)
        self.model_schema_value.setWordWrap(True)
        self.model_classes_value.setWordWrap(True)
        self.model_capture_value.setWordWrap(True)
        self.model_mode_value.setWordWrap(True)
        model_info.addRow("Status:", self.model_status_value)
        model_info.addRow("Feature schema:", self.model_schema_value)
        model_info.addRow("Classes:", self.model_classes_value)
        model_info.addRow("Capture:", self.model_capture_value)
        model_info.addRow("Mode:", self.model_mode_value)
        model_layout.addLayout(model_info)

        trust = QLabel(
            "Security: joblib/pickle models can execute Python code while loading. "
            "Load only model files you trust."
        )
        trust.setWordWrap(True)
        trust.setObjectName("Hint")
        model_layout.addWidget(trust)
        layout.addWidget(model_box)

        self.model_views = QTabWidget()
        self.model_live_page = QWidget()
        self.model_test_page = QWidget()
        self.model_views.addTab(self.model_live_page, "Live monitoring")
        self.model_views.addTab(self.model_test_page, "Model test")
        layout.addWidget(self.model_views, 1)

        live_layout = QVBoxLayout(self.model_live_page)
        live_layout.setContentsMargins(4, 8, 4, 4)
        live_layout.setSpacing(8)

        traffic_box = QGroupBox("Active clients — latest completed 1-second window")
        traffic_layout = QVBoxLayout(traffic_box)
        self.model_monitor_summary = QLabel("Waiting for server...")
        self.model_monitor_summary.setObjectName("Hint")
        traffic_layout.addWidget(self.model_monitor_summary)

        self.model_clients_table = QTableWidget(0, 9)
        self.model_clients_table.setHorizontalHeaderLabels([
            "Client", "IP", "Connection", "State", "Type / class",
            "Confidence", "Last window", "Packets/s", "Bytes/s"
        ])
        self.model_clients_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.model_clients_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.model_clients_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.model_clients_table.cellDoubleClicked.connect(
            self.show_model_client_details
        )
        header = self.model_clients_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 9):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        traffic_layout.addWidget(self.model_clients_table, 1)
        live_layout.addWidget(traffic_box, 1)

        events_box = QGroupBox("Model events")
        events_layout = QVBoxLayout(events_box)
        self.model_events = QPlainTextEdit()
        self.model_events.setReadOnly(True)
        self.model_events.setMaximumHeight(110)
        self.model_events.setPlaceholderText("Model load and anomaly transitions will appear here.")
        events_layout.addWidget(self.model_events)
        live_layout.addWidget(events_box)

        test_outer = QVBoxLayout(self.model_test_page)
        test_outer.setContentsMargins(0, 0, 0, 0)
        test_outer.setSpacing(0)
        self.model_test_scroll = QScrollArea()
        self.model_test_scroll.setWidgetResizable(True)
        self.model_test_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.model_test_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        model_test_content = QWidget()
        test_layout = QVBoxLayout(model_test_content)
        test_layout.setContentsMargins(4, 8, 8, 8)
        test_layout.setSpacing(8)
        self.model_test_scroll.setWidget(model_test_content)
        test_outer.addWidget(self.model_test_scroll)

        test_intro = QLabel(
            "Run the same traffic scenarios used for training, but without "
            "creating PCAP or CSV files. Every complete 1-second live window "
            "is compared with the expected phase class."
        )
        test_intro.setWordWrap(True)
        test_intro.setObjectName("Hint")
        test_layout.addWidget(test_intro)

        setup_box = QGroupBox("Validation scenario")
        setup_layout = QVBoxLayout(setup_box)
        setup_form = QFormLayout()
        self.model_test_target = QComboBox()
        self.model_test_baseline_dir = QLineEdit()
        self.model_test_baseline_dir.setPlaceholderText("/home/user/ml_baseline")
        self.model_test_baseline_dir.setToolTip("Path on the selected CLIENT device.")
        setup_form.addRow("Client:", self.model_test_target)
        setup_form.addRow("Client baseline folder:", self.model_test_baseline_dir)
        setup_layout.addLayout(setup_form)

        test_buttons = QHBoxLayout()
        add_phase = QPushButton("Add phase")
        delete_phase = QPushButton("Delete selected")
        example = QPushButton("Load example")
        copy_training = QPushButton("Use training scenario")
        validate = QPushButton("Validate")
        add_phase.clicked.connect(self.add_model_test_phase)
        delete_phase.clicked.connect(self.delete_model_test_phase)
        example.clicked.connect(self.load_model_test_example)
        copy_training.clicked.connect(self.copy_training_scenario_to_model_test)
        validate.clicked.connect(self.validate_model_test_timeline)
        test_buttons.addWidget(add_phase)
        test_buttons.addWidget(delete_phase)
        test_buttons.addWidget(example)
        test_buttons.addWidget(copy_training)
        test_buttons.addWidget(validate)
        test_buttons.addStretch()
        setup_layout.addLayout(test_buttons)

        self.model_test_timeline = QTableWidget(0, 4)
        self.model_test_timeline.setHorizontalHeaderLabels([
            "Start, s", "End, s", "Mode", "Parameters JSON"
        ])
        self.model_test_timeline.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.model_test_timeline.setSelectionMode(QAbstractItemView.SingleSelection)
        self.model_test_timeline.setMinimumHeight(210)
        test_header = self.model_test_timeline.horizontalHeader()
        test_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        test_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        test_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        test_header.setSectionResizeMode(3, QHeaderView.Stretch)
        setup_layout.addWidget(self.model_test_timeline)

        run_row = QHBoxLayout()
        self.model_test_start_btn = QPushButton("Run live model test")
        self.model_test_stop_btn = QPushButton("Stop test")
        self.model_test_start_btn.clicked.connect(self.start_model_test)
        self.model_test_stop_btn.clicked.connect(self.stop_model_test)
        run_row.addStretch()
        run_row.addWidget(self.model_test_start_btn)
        run_row.addWidget(self.model_test_stop_btn)
        setup_layout.addLayout(run_row)
        test_layout.addWidget(setup_box)

        progress_box = QGroupBox("Test progress")
        progress_layout = QVBoxLayout(progress_box)
        self.model_test_progress = QProgressBar()
        self.model_test_progress.setRange(0, 100)
        self.model_test_progress.setValue(0)
        self.model_test_progress.setFormat("0%")
        self.model_test_status_summary = QLabel("No model test has been started")
        self.model_test_status_summary.setObjectName("Hint")
        self.model_test_status_summary.setWordWrap(True)
        self.model_test_live_result = QLabel("Expected: —    Model: —")
        self.model_test_live_result.setWordWrap(True)
        progress_layout.addWidget(self.model_test_progress)
        progress_layout.addWidget(self.model_test_status_summary)
        progress_layout.addWidget(self.model_test_live_result)
        test_layout.addWidget(progress_box)

        results_box = QGroupBox("Per-second validation results")
        results_layout = QVBoxLayout(results_box)
        self.model_test_results = QTableWidget(0, 5)
        self.model_test_results.setHorizontalHeaderLabels([
            "Time", "Expected", "Model", "Confidence", "Match"
        ])
        self.model_test_results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.model_test_results.setMinimumHeight(230)
        result_header = self.model_test_results.horizontalHeader()
        result_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        result_header.setSectionResizeMode(1, QHeaderView.Stretch)
        result_header.setSectionResizeMode(2, QHeaderView.Stretch)
        result_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        result_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        results_layout.addWidget(self.model_test_results, 1)
        self.model_test_summary = QLabel("Scored windows: 0")
        self.model_test_summary.setObjectName("Hint")
        self.model_test_summary.setWordWrap(True)
        results_layout.addWidget(self.model_test_summary)
        test_layout.addWidget(results_box, 1)

        self._model_monitor_data = {}
        self._model_test_data = {}
        self.refresh_model_test_targets()
        self.load_model_test_example()


    def refresh_model_test_targets(self):
        if not hasattr(self, "model_test_target"):
            return
        current = self.model_test_target.currentData()
        self.model_test_target.clear()
        for row in db.list_all_users():
            if row["role"] != "client" or not row["active"]:
                continue
            self.model_test_target.addItem(
                "%s (%s)" % (row["name"], row["user_id"]),
                row["user_id"]
            )
        if current:
            index = self.model_test_target.findData(current)
            if index >= 0:
                self.model_test_target.setCurrentIndex(index)

    def add_model_test_phase(self, start_sec=None, end_sec=None,
                             mode="NORMAL", params=None):
        table = self.model_test_timeline
        row = table.rowCount()
        if start_sec is None:
            if row == 0:
                start_sec = 0
            else:
                item = table.item(row - 1, 1)
                try:
                    start_sec = int(item.text())
                except Exception:
                    start_sec = row * 15
        if end_sec is None:
            end_sec = int(start_sec) + 15
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(str(int(start_sec))))
        table.setItem(row, 1, QTableWidgetItem(str(int(end_sec))))
        table.setCellWidget(row, 2, self._mode_combo(mode))
        table.setItem(
            row, 3,
            QTableWidgetItem(json.dumps(params or {}, sort_keys=True))
        )

    def delete_model_test_phase(self):
        row = self.model_test_timeline.currentRow()
        if row >= 0:
            self.model_test_timeline.removeRow(row)

    def load_model_test_example(self):
        if not hasattr(self, "model_test_timeline"):
            return
        self.model_test_timeline.setRowCount(0)
        self.add_model_test_phase(0, 10, "NORMAL", {})
        self.add_model_test_phase(
            10, 20, "FREQUENT_RECONNECT", {"interval_sec": 0.1}
        )
        self.add_model_test_phase(20, 30, "NORMAL", {})
        self.add_model_test_phase(
            30, 40, "HIGH_REQUEST_RATE", {"requests_per_sec": 30}
        )
        self.add_model_test_phase(40, 50, "NORMAL", {})
        self.add_model_test_phase(
            50, 60, "HIGH_FREQUENCY_SMALL_TRANSFERS",
            {"transfers_per_sec": 15, "payload_bytes": 32}
        )

    def collect_model_test_timeline(self):
        table = self.model_test_timeline
        if table.rowCount() == 0:
            raise RuntimeError("Model test timeline is empty")
        phases = []
        previous_end = 0
        for row in range(table.rowCount()):
            start_item = table.item(row, 0)
            end_item = table.item(row, 1)
            params_item = table.item(row, 3)
            combo = table.cellWidget(row, 2)
            try:
                start_sec = int(start_item.text().strip())
                end_sec = int(end_item.text().strip())
            except Exception:
                raise RuntimeError(
                    "Row %d start/end must be integer seconds" % (row + 1)
                )
            if start_sec != previous_end:
                raise RuntimeError(
                    "Row %d must start at %d seconds" % (row + 1, previous_end)
                )
            if end_sec <= start_sec:
                raise RuntimeError(
                    "Row %d end must be greater than start" % (row + 1)
                )
            raw_params = (
                params_item.text().strip() if params_item is not None else "{}"
            ) or "{}"
            try:
                params = json.loads(raw_params)
            except Exception:
                raise RuntimeError(
                    "Row %d parameters are not valid JSON" % (row + 1)
                )
            if not isinstance(params, dict):
                raise RuntimeError(
                    "Row %d parameters must be a JSON object" % (row + 1)
                )
            phases.append({
                "start_sec": start_sec,
                "end_sec": end_sec,
                "label": str(combo.currentData()),
                "params": params,
            })
            previous_end = end_sec
        if previous_end > 3600:
            raise RuntimeError("Model test cannot exceed 3600 seconds")
        return phases

    def validate_model_test_timeline(self):
        try:
            timeline = self.collect_model_test_timeline()
        except Exception as exc:
            self.warn(str(exc))
            return
        QMessageBox.information(
            self,
            APP_NAME,
            "Model test scenario is valid.\nDuration: %d seconds\nPhases: %d\n"
            "PCAP/CSV recording: disabled"
            % (timeline[-1]["end_sec"], len(timeline))
        )

    def copy_training_scenario_to_model_test(self):
        try:
            timeline = self.collect_timeline()
        except Exception as exc:
            self.warn("Training scenario is not valid: %s" % exc)
            return
        target = self.timeline_target.currentData()
        if target:
            index = self.model_test_target.findData(target)
            if index >= 0:
                self.model_test_target.setCurrentIndex(index)
        self.model_test_baseline_dir.setText(
            self.timeline_baseline_dir.text().strip()
        )
        self.model_test_timeline.setRowCount(0)
        for phase in timeline:
            self.add_model_test_phase(
                phase["start_sec"], phase["end_sec"], phase["label"],
                dict(phase.get("params") or {})
            )

    def start_model_test(self):
        if not self.server_online:
            self.warn("Server is unavailable.")
            return
        target = self.model_test_target.currentData()
        if not target:
            self.warn("Select a target client.")
            return
        baseline_dir = self.model_test_baseline_dir.text().strip()
        if not baseline_dir:
            self.warn("Enter the baseline folder path on the client.")
            return
        try:
            timeline = self.collect_model_test_timeline()
            response = requests.post(
                self.args.server_url.rstrip("/") + "/admin/model/test/start",
                json={
                    "target_user_id": target,
                    "baseline_dir": baseline_dir,
                    "timeline": timeline,
                },
                timeout=8
            )
            data = response.json()
            if response.status_code >= 400:
                raise RuntimeError(data.get("error", "Cannot start model test"))
        except Exception as exc:
            self.warn(str(exc))
            return
        self._model_test_data = data
        self.refresh_model_test()

    def stop_model_test(self):
        try:
            response = requests.post(
                self.args.server_url.rstrip("/") + "/admin/model/test/stop",
                json={},
                timeout=5
            )
            data = response.json()
            if response.status_code >= 400:
                raise RuntimeError(data.get("error", "Cannot stop model test"))
        except Exception as exc:
            self.warn(str(exc))
            return
        self._model_test_data = data
        self.refresh_model_test()

    def refresh_model_test(self):
        if not hasattr(self, "model_test_progress"):
            return
        try:
            response = requests.get(
                self.args.server_url.rstrip("/") + "/admin/model/test/status",
                timeout=1.5
            )
            data = response.json()
            if response.status_code >= 400:
                raise RuntimeError(data.get("error", "Model test status unavailable"))
        except Exception as exc:
            self.model_test_status_summary.setText(
                "Cannot read model test status: %s" % exc
            )
            return

        self._model_test_data = data
        status = str(data.get("status") or "idle")
        progress = int(data.get("progress_percent") or 0)
        self.model_test_progress.setValue(progress)
        self.model_test_progress.setFormat("%d%%" % progress)

        elapsed = float(data.get("elapsed_sec") or 0.0)
        total = int(data.get("total_duration_sec") or 0)
        remaining = float(data.get("remaining_sec") or 0.0)
        phase = data.get("current_phase") or "—"
        if status == "idle":
            status_text = "No model test has been started"
        else:
            status_text = (
                "Test #%s • %s • %.0f / %d s • remaining %.0f s • phase: %s"
                % (
                    data.get("test_id"), status, elapsed, total, remaining, phase
                )
            )
            if data.get("error"):
                status_text += " • %s" % data.get("error")
        self.model_test_status_summary.setText(status_text)

        latest = data.get("latest") or {}
        if latest:
            conf = latest.get("confidence")
            conf_text = "—" if conf is None else "%.1f%%" % (float(conf) * 100.0)
            match_text = "MATCH" if latest.get("match") else "MISMATCH"
            self.model_test_live_result.setText(
                "Expected: %s    Model: %s    Confidence: %s    %s"
                % (
                    latest.get("expected") or "—",
                    latest.get("prediction") or "—",
                    conf_text,
                    match_text,
                )
            )
        else:
            self.model_test_live_result.setText(
                "Expected: %s    Model: waiting for a complete 1-second window"
                % phase
            )

        results = data.get("results") or []
        self.model_test_results.setRowCount(len(results))
        for r, item in enumerate(results):
            conf = item.get("confidence")
            conf_text = "—" if conf is None else "%.1f%%" % (float(conf) * 100.0)
            values = [
                "%.1f s" % float(item.get("relative_sec") or 0.0),
                item.get("expected") or "—",
                item.get("prediction") or "—",
                conf_text,
                "✓" if item.get("match") else "✕",
            ]
            for c, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if c in (0, 3, 4):
                    cell.setTextAlignment(Qt.AlignCenter)
                self.model_test_results.setItem(r, c, cell)

        summary = data.get("summary") or {}
        accuracy = summary.get("accuracy")
        avg_conf = summary.get("average_confidence")
        accuracy_text = "—" if accuracy is None else "%.1f%%" % (float(accuracy) * 100.0)
        avg_conf_text = "—" if avg_conf is None else "%.1f%%" % (float(avg_conf) * 100.0)
        pieces = [
            "Scored: %d" % int(summary.get("scored_windows") or 0),
            "Correct: %d" % int(summary.get("correct_windows") or 0),
            "Accuracy: %s" % accuracy_text,
            "Avg confidence: %s" % avg_conf_text,
        ]
        ignored = int(data.get("ignored_boundary_windows") or 0)
        if ignored:
            pieces.append("Boundary windows ignored: %d" % ignored)
        by_class = summary.get("by_class") or {}
        class_parts = []
        for name in sorted(by_class.keys()):
            item = by_class[name]
            total_count = int(item.get("total") or 0)
            correct_count = int(item.get("correct") or 0)
            class_parts.append("%s %d/%d" % (name, correct_count, total_count))
        text = " • ".join(pieces)
        if class_parts:
            text += "\n" + " • ".join(class_parts)
        self.model_test_summary.setText(text)

    def browse_model_file(self):
        path, selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select trained model",
            self.model_path.text().strip() or str(Path.home()),
            "Model files (*.joblib *.pkl *.pickle);;All files (*)"
        )
        if path:
            self.model_path.setText(path)

    def load_model_file(self):
        path = self.model_path.text().strip()
        if not path:
            self.warn("Select a model file first.")
            return
        try:
            response = requests.post(
                self.args.server_url.rstrip("/") + "/admin/model/load",
                json={"path": path},
                timeout=15
            )
            data = response.json()
            if response.status_code >= 400:
                raise RuntimeError(data.get("error", "Cannot load model"))
        except Exception as exc:
            self.warn(str(exc))
            return
        self.refresh_model_monitor()

    def unload_model_file(self):
        try:
            response = requests.post(
                self.args.server_url.rstrip("/") + "/admin/model/unload",
                json={},
                timeout=5
            )
            data = response.json()
            if response.status_code >= 400:
                raise RuntimeError(data.get("error", "Cannot unload model"))
        except Exception as exc:
            self.warn(str(exc))
            return
        self.refresh_model_monitor()

    @staticmethod
    def _monitor_state_text(value):
        mapping = {
            "NORMAL": "Normal",
            "ANOMALY": "Anomaly",
            "NO_DATA": "No data yet",
            "MODEL_NOT_LOADED": "Model not loaded",
            "CAPTURE_ERROR": "Capture error",
        }
        return mapping.get(str(value or ""), str(value or "-"))

    @staticmethod
    def _format_monitor_window(epoch):
        if epoch is None:
            return "-"
        try:
            return time.strftime("%H:%M:%S", time.localtime(float(epoch)))
        except Exception:
            return "-"

    def refresh_model_monitor(self):
        if not hasattr(self, "model_clients_table"):
            return
        try:
            response = requests.get(
                self.args.server_url.rstrip("/") + "/admin/model/monitor",
                timeout=1.5
            )
            data = response.json()
            if response.status_code >= 400:
                raise RuntimeError(data.get("error", "Model monitor unavailable"))
        except Exception as exc:
            self.model_status_value.setText("Server unavailable")
            self.model_capture_value.setText(str(exc))
            self.model_monitor_summary.setText("Cannot read live model status.")
            return

        self._model_monitor_data = data
        model = data.get("model") or {}
        capture = data.get("capture") or {}
        clients = data.get("clients") or []

        if model.get("loaded"):
            self.model_status_value.setText(
                "Loaded: %s" % (model.get("file_name") or "model")
            )
            if model.get("path") and not self.model_path.hasFocus():
                self.model_path.setText(str(model.get("path")))
        else:
            self.model_status_value.setText("Not loaded")

        feature_count = int(model.get("feature_count") or 0)
        self.model_schema_value.setText(
            "1 second fixed window • %d model features" % feature_count
        )
        classes = model.get("classes") or []
        self.model_classes_value.setText(
            ", ".join(str(item) for item in classes) if classes else "-"
        )

        capture_text = str(capture.get("state") or "idle")
        if capture.get("backend"):
            capture_text += " • %s" % capture.get("backend")
        if capture.get("interface"):
            capture_text += " • interface %s" % capture.get("interface")
        if capture.get("error"):
            capture_text += " • %s" % capture.get("error")
        if model.get("runtime_error") and model.get("runtime_error") not in capture_text:
            capture_text += " • %s" % model.get("runtime_error")
        self.model_capture_value.setText(capture_text)

        self.model_monitor_summary.setText(
            "Active clients: %d • results update once per completed second" % len(clients)
        )
        self.model_clients_table.setRowCount(len(clients))
        for row_index, client in enumerate(clients):
            metrics = client.get("metrics") or {}
            confidence = client.get("confidence")
            confidence_text = "-"
            if confidence is not None:
                try:
                    confidence_text = "%.1f%%" % (float(confidence) * 100.0)
                except Exception:
                    confidence_text = str(confidence)
            prediction = client.get("prediction") or "-"
            values = [
                "%s (%s)" % (client.get("name") or client.get("user_id"), client.get("user_id")),
                client.get("ip") or "-",
                "Online" if client.get("online") else "Offline",
                self._monitor_state_text(client.get("status")),
                prediction,
                confidence_text,
                self._format_monitor_window(client.get("window_start_epoch")),
                metrics.get("packets_per_sec", "-"),
                metrics.get("bytes_per_sec", "-"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in (2, 3, 5, 6, 7, 8):
                    item.setTextAlignment(Qt.AlignCenter)
                if column == 0:
                    item.setData(Qt.UserRole, str(client.get("user_id") or ""))
                self.model_clients_table.setItem(row_index, column, item)

        events = data.get("events") or []
        lines = []
        for event in reversed(events[-40:]):
            lines.append("[%s] %s" % (
                event.get("time") or "--:--:--",
                event.get("message") or ""
            ))
        self.model_events.setPlainText("\n".join(lines))

    def show_model_client_details(self, row, column):
        item = self.model_clients_table.item(row, 0)
        if item is None:
            return
        user_id = item.data(Qt.UserRole)
        if not user_id:
            return
        try:
            response = requests.get(
                self.args.server_url.rstrip("/") + "/admin/model/client",
                params={"user_id": str(user_id)},
                timeout=2
            )
            data = response.json()
            if response.status_code >= 400:
                raise RuntimeError(data.get("error", "Cannot read client details"))
        except Exception as exc:
            self.warn(str(exc))
            return

        latest = data.get("latest") or {}
        history = data.get("history") or []
        if not latest:
            QMessageBox.information(
                self, APP_NAME, "No completed live window for this client yet."
            )
            return

        confidence = latest.get("confidence")
        confidence_text = "-"
        if confidence is not None:
            confidence_text = "%.1f%%" % (float(confidence) * 100.0)

        summary = (
            "Client: %s\nState: %s\nClass / anomaly type: %s\nConfidence: %s\n"
            "Window: %s–%s"
        ) % (
            user_id,
            self._monitor_state_text(latest.get("status")),
            latest.get("prediction") or "-",
            confidence_text,
            self._format_monitor_window(latest.get("window_start_epoch")),
            self._format_monitor_window(latest.get("window_end_epoch")),
        )

        details = ["Class probabilities:"]
        probabilities = latest.get("class_probabilities") or {}
        for name, value in sorted(
                probabilities.items(), key=lambda pair: pair[1], reverse=True):
            details.append("  %s: %.2f%%" % (name, float(value) * 100.0))
        details.append("")
        details.append("1-second feature values:")
        for name, value in sorted((latest.get("features") or {}).items()):
            details.append("  %s: %s" % (name, value))
        details.append("")
        details.append("Recent history:")
        for entry in history[-15:]:
            conf = entry.get("confidence")
            conf_text = "-" if conf is None else "%.1f%%" % (float(conf) * 100.0)
            details.append("  %s  %s  %s" % (
                self._format_monitor_window(entry.get("window_start_epoch")),
                entry.get("prediction") or "-",
                conf_text,
            ))

        box = QMessageBox(self)
        box.setWindowTitle("Traffic details — %s" % user_id)
        box.setText(summary)
        box.setDetailedText("\n".join(details))
        if hasattr(box, "exec"):
            box.exec()
        else:
            box.exec_()

    def refresh_server_status(self):
        url = self.args.server_url.rstrip("/") + "/users"
        try:
            response = requests.get(url, timeout=1.0)
            response.raise_for_status()
            users = response.json().get("users", [])
            self.online_map = {
                u["user_id"]: bool(u.get("online"))
                for u in users
            }
            self.server_online = True
            self.set_server_indicator(True)
        except Exception:
            self.online_map = {}
            self.server_online = False
            self.set_server_indicator(False)

        self.refresh_users()
        if hasattr(self, "timeline_target"):
            self.refresh_timeline_targets()
        if hasattr(self, "model_test_target"):
            self.refresh_model_test_targets()
        if hasattr(self, "runs_table"):
            self.refresh_runs()

    def set_server_indicator(self, online):
        if online:
            self.server_dot.setStyleSheet(
                "background:#22C55E; border-radius:5px;"
            )
            self.server_status.setText("Server running")
        else:
            self.server_dot.setStyleSheet(
                "background:#94A3B8; border-radius:5px;"
            )
            self.server_status.setText("Server unavailable")

    @staticmethod
    def online_text(value):
        if value is True:
            return "Online"
        if value is False:
            return "Offline"
        return "Unknown"

    def warn(self, text):
        QMessageBox.warning(self, APP_NAME, text)

    def apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #F7F9FC;
                color: #172033;
                font-family: Arial, "DejaVu Sans", sans-serif;
                font-size: 13px;
            }
            QLabel#Title {
                font-size: 22px;
                font-weight: 700;
                color: #111827;
            }
            QLabel#ServerStatus {
                font-weight: 600;
                color: #475467;
            }
            QLabel#Hint {
                color: #5E6B7C;
                padding: 4px;
            }
            QGroupBox {
                background: #FFFFFF;
                border: 1px solid #DDE3EA;
                border-radius: 10px;
                margin-top: 10px;
                padding: 12px;
                font-weight: 700;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
            }
            QLineEdit, QComboBox {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 7px;
                padding: 7px;
                color: #172033;
            }
            QPushButton {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 7px;
                padding: 7px 12px;
                color: #172033;
            }
            QPushButton:hover {
                background: #EEF4FF;
                border-color: #9DB9F3;
            }
            QPushButton#DangerButton {
                background: #FFF7F7;
                border-color: #F1A7A7;
                color: #B42318;
                font-weight: 700;
            }
            QPushButton#DangerButton:hover {
                background: #FEECEC;
                border-color: #E57373;
            }
            QPushButton:disabled {
                color: #98A2B3;
                background: #F2F4F7;
            }
            QScrollArea {
                border: 0;
                background: transparent;
            }
            QTableWidget {
                background: #FFFFFF;
                alternate-background-color: #F8FAFC;
                border: 1px solid #DDE3EA;
                border-radius: 8px;
                gridline-color: #EDF0F4;
            }
            QHeaderView::section {
                background: #F1F5F9;
                color: #334155;
                padding: 7px;
                border: 0;
                border-right: 1px solid #E2E8F0;
                font-weight: 700;
            }
            QTabWidget::pane {
                border: 1px solid #DDE3EA;
                background: #FFFFFF;
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #E9EEF5;
                padding: 9px 16px;
                margin-right: 3px;
                border-top-left-radius: 7px;
                border-top-right-radius: 7px;
            }
            QTabBar::tab:selected {
                background: #FFFFFF;
                color: #1D4ED8;
                font-weight: 700;
            }
        """)


def parse_args():
    p = argparse.ArgumentParser(description="Interchange Admin Panel")
    p.add_argument("--server-config", default=None)
    p.add_argument("--db", default=None)
    p.add_argument("--server-url", default=None)
    return p.parse_args()


def main():
    args = parse_args()
    config_path = Path(args.server_config or default_config_path()).expanduser()
    server_values = load_server_config(config_path)

    if args.db is None:
        args.db = server_values["db_file"]
    if args.server_url is None:
        args.server_url = "http://127.0.0.1:%s" % server_values["http_port"]

    app = QApplication([])
    app.setApplicationName(APP_NAME)
    window = AdminWindow(args)
    window.show()
    app_exec(app)


if __name__ == "__main__":
    main()
