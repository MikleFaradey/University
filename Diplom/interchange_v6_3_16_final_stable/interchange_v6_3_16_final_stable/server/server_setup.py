from pathlib import Path

from qt_compat import (
    QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPixmap, QPushButton, QSpinBox, Qt,
    QVBoxLayout, QWidget
)
from server_config import save_server_config


class ServerSetupDialog(QDialog):
    def __init__(self, config_path, values, first_run=False, parent=None):
        QDialog.__init__(self, parent)
        self.config_path = Path(config_path).expanduser()
        self.saved_values = None
        self.first_run = first_run

        self.setWindowTitle(
            "Interchange Server Setup" if first_run
            else "Interchange Server Settings"
        )
        self.setMinimumWidth(620)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        logo = QLabel()
        logo_path = Path(__file__).parent / "assets" / "interchange_logo.png"
        pixmap = QPixmap(str(logo_path))
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaledToHeight(46, Qt.SmoothTransformation))
        root.addWidget(logo)

        title = QLabel(
            "Configure this server" if first_run
            else "Server settings"
        )
        title.setStyleSheet("font-size:20px; font-weight:700;")
        root.addWidget(title)

        hint = QLabel(
            "These settings control the Interchange server, database, "
            "relay storage, and network ports."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#596579;")
        root.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)

        self.destination_dir = QLineEdit(str(values.get("destination_dir", "")))
        self.db_file = QLineEdit(str(values.get("db_file", "")))
        self.spool_dir = QLineEdit(str(values.get("spool_dir", "")))
        self.pcap_dir = QLineEdit(str(values.get("pcap_dir", "")))
        self.capture_interface = QLineEdit(
            str(values.get("capture_interface", "auto"))
        )

        form.addRow(
            "Server receive folder:",
            self.path_row(self.destination_dir, self.browse_destination)
        )
        form.addRow("Database file:", self.db_file)
        form.addRow(
            "Relay spool folder:",
            self.path_row(self.spool_dir, self.browse_spool)
        )
        form.addRow(
            "PCAP folder:",
            self.path_row(self.pcap_dir, self.browse_pcap)
        )
        form.addRow("Capture interface:", self.capture_interface)

        self.http_port = QSpinBox()
        self.http_port.setRange(1, 65535)
        self.http_port.setValue(int(values.get("http_port", 8080)))
        self.socket_port = QSpinBox()
        self.socket_port.setRange(1, 65535)
        self.socket_port.setValue(int(values.get("socket_port", 8081)))
        self.show_gui = QCheckBox("Open the server monitor window")
        self.show_gui.setChecked(bool(values.get("show_gui", True)))

        form.addRow("HTTP port:", self.http_port)
        form.addRow("Socket port:", self.socket_port)
        form.addRow("", self.show_gui)
        root.addLayout(form)

        info = QLabel(
            "The Administration Panel uses the same database configuration automatically."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#596579;")
        root.addWidget(info)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("Save and start" if first_run else "Save")
        save.clicked.connect(self.save)
        save.setDefault(True)
        buttons.addWidget(save)
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

    def path_row(self, edit, callback):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.addWidget(edit, 1)
        button = QPushButton("Browse...")
        button.clicked.connect(callback)
        layout.addWidget(button)
        return widget

    def browse_destination(self):
        current = self.destination_dir.text().strip() or str(Path.home())
        value = QFileDialog.getExistingDirectory(
            self, "Select server receive folder", current
        )
        if value:
            self.destination_dir.setText(value)

    def browse_spool(self):
        current = self.spool_dir.text().strip() or str(Path.home())
        value = QFileDialog.getExistingDirectory(
            self, "Select relay spool folder", current
        )
        if value:
            self.spool_dir.setText(value)

    def browse_pcap(self):
        current = self.pcap_dir.text().strip() or str(Path.home())
        value = QFileDialog.getExistingDirectory(
            self, "Select PCAP folder", current
        )
        if value:
            self.pcap_dir.setText(value)

    def values(self):
        return {
            "destination_dir": self.destination_dir.text().strip(),
            "db_file": self.db_file.text().strip(),
            "spool_dir": self.spool_dir.text().strip(),
            "pcap_dir": self.pcap_dir.text().strip(),
            "capture_interface": (
                self.capture_interface.text().strip() or "auto"
            ),
            "http_port": int(self.http_port.value()),
            "socket_port": int(self.socket_port.value()),
            "show_gui": self.show_gui.isChecked(),
        }

    def validate(self):
        values = self.values()
        if not values["destination_dir"]:
            QMessageBox.warning(self, "Interchange", "Select the server receive folder.")
            return None
        if not values["db_file"]:
            QMessageBox.warning(self, "Interchange", "Enter the database file path.")
            return None
        if not values["spool_dir"]:
            QMessageBox.warning(self, "Interchange", "Select the relay spool folder.")
            return None
        if not values["pcap_dir"]:
            QMessageBox.warning(self, "Interchange", "Select the PCAP folder.")
            return None
        if values["http_port"] == values["socket_port"]:
            QMessageBox.warning(self, "Interchange", "HTTP and Socket ports must be different.")
            return None
        return values

    def save(self):
        values = self.validate()
        if not values:
            return
        try:
            Path(values["destination_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
            Path(values["spool_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
            Path(values["pcap_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
            Path(values["db_file"]).expanduser().parent.mkdir(parents=True, exist_ok=True)
            save_server_config(values, self.config_path)
        except Exception as exc:
            QMessageBox.warning(self, "Interchange", "Cannot save settings: %s" % exc)
            return
        self.saved_values = values
        self.accept()


def dialog_exec(dialog):
    if hasattr(dialog, "exec"):
        return dialog.exec()
    return dialog.exec_()
