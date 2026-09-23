import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from client_cache import ClientCache
from client_config import (
    default_config_path, is_client_config_complete, load_client_config
)
from client_setup import ClientSetupDialog, dialog_exec
from client_network import ClientNetwork
from py_compat import parse_sqlite_datetime
from qt_compat import (
    QApplication, QFileDialog, QAbstractItemView, QFrame, QHBoxLayout,
    QIcon, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPixmap, QDialog, QSize, QToolButton, QTimer,
    QVBoxLayout, QWidget, Qt, QT_API, app_exec
)

APP_NAME = "Interchange"


def resource_path(*parts):
    """Return a resource path in source, native packages, or PyInstaller."""
    roots = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.append(Path(bundle_root))
    roots.append(Path(__file__).resolve().parent)
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)

    for root in roots:
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate

    # Return a deterministic path for diagnostics even if it is missing.
    return roots[0].joinpath(*parts)


def set_button_icon(button, filename, fallback_text):
    path = resource_path("icons", filename)
    icon = QIcon(str(path))
    if not icon.isNull():
        button.setIcon(icon)
        return True
    logging.getLogger(__name__).warning("Missing/invalid UI icon: %s", path)
    button.setText(fallback_text)
    return False


def required_ui_resources():
    return [
        resource_path("assets", "interchange_logo.png"),
        resource_path("icons", "file.png"),
        resource_path("icons", "folder.png"),
        resource_path("icons", "send_white.png"),
    ]


def configure_logging():
    logging.basicConfig(
        filename="client_debug.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )


class ContactWidget(QWidget):
    def __init__(self, name, user_id, status_text, status_kind,
                 preview="", time_text="", parent=None):
        QWidget.__init__(self, parent)
        self.setObjectName("ContactCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(8)

        dot = QLabel()
        dot.setFixedSize(10, 10)
        color = {
            "online": "#22C55E",
            "offline": "#94A3B8",
            "unknown": "#F59E0B",
        }.get(status_kind, "#94A3B8")
        dot.setStyleSheet("background:%s; border-radius:5px;" % color)

        title = QLabel(name)
        title.setObjectName("ContactName")

        state = QLabel(status_text)
        state.setObjectName("ContactStatus")

        top.addWidget(dot)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(state)
        outer.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        preview_label = QLabel(preview or "")
        preview_label.setObjectName("ContactPreview")
        preview_label.setToolTip(preview or "")
        preview_label.setWordWrap(False)
        time_label = QLabel(time_text or "")
        time_label.setObjectName("ContactTime")
        bottom.addWidget(preview_label, 1)
        bottom.addWidget(time_label)
        outer.addLayout(bottom)


class MessageBubble(QWidget):
    """
    Layout rule:
    - own messages are on the left;
    - peer messages are on the right.
    """
    def __init__(self, text, time_text, own=False, file_status=False, parent=None):
        QWidget.__init__(self, parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 4, 10, 4)
        row.setSpacing(0)

        bubble = QFrame()
        bubble.setObjectName("OwnBubble" if own else "PeerBubble")
        bubble.setMaximumWidth(520)

        inner = QVBoxLayout(bubble)
        inner.setContentsMargins(14, 10, 14, 9)
        inner.setSpacing(6)

        label = QLabel(text)
        label.setObjectName("FileText" if file_status else "MessageText")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        inner.addWidget(label)

        stamp = QLabel(time_text)
        stamp.setObjectName("MessageTime")
        if own:
            stamp.setAlignment(Qt.AlignLeft)
        else:
            stamp.setAlignment(Qt.AlignRight)
        inner.addWidget(stamp)

        if own:
            row.addWidget(bubble, 0, Qt.AlignLeft)
            row.addStretch(1)
        else:
            row.addStretch(1)
            row.addWidget(bubble, 0, Qt.AlignRight)


class MainWindow(QMainWindow):
    def __init__(self, args, config_path):
        QMainWindow.__init__(self)
        self.args = args
        self.config_path = config_path
        self.cache = ClientCache(args.cache)
        self.online_map = {}
        self.connected = False
        self.current_peer = None
        self.current_progress_name = None
        self._reauth_in_progress = False
        self._experiment_active = False
        self._experiment_label = ""

        # Coalesce network bursts into a small number of GUI updates.  This is
        # essential during FREQUENT_RECONNECT and history synchronization.
        self._contacts_timer = QTimer(self)
        self._contacts_timer.setSingleShot(True)
        self._contacts_timer.setInterval(120)
        self._contacts_timer.timeout.connect(self.rebuild_contacts)

        self._chat_timer = QTimer(self)
        self._chat_timer.setSingleShot(True)
        self._chat_timer.setInterval(60)
        self._chat_timer.timeout.connect(self.render_cached_chat)

        self.cache.upsert_contact("server", u"Server", "server")

        self.setWindowTitle(APP_NAME)
        self.resize(1040, 700)
        self.setMinimumSize(900, 600)

        account_menu = self.menuBar().addMenu("Account")
        switch_action = account_menu.addAction("Switch account...")
        switch_action.triggered.connect(self.switch_account)

        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        topbar = QFrame()
        topbar.setObjectName("TopBar")
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(20, 10, 24, 10)

        self.logo = QLabel()
        self.logo.setObjectName("BrandLogo")
        logo_path = resource_path("assets", "interchange_logo.png")
        pixmap = QPixmap(str(logo_path))
        if not pixmap.isNull():
            self.logo.setPixmap(pixmap.scaledToHeight(42, Qt.SmoothTransformation))
        self.logo.setMinimumHeight(42)
        top_layout.addWidget(self.logo)
        top_layout.addStretch()

        self.experiment_text = QLabel("")
        self.experiment_text.setObjectName("ExperimentState")
        self.experiment_text.setVisible(False)
        top_layout.addWidget(self.experiment_text)
        top_layout.addSpacing(12)

        self.connection_dot = QLabel()
        self.connection_dot.setFixedSize(10, 10)
        self.connection_text = QLabel(u"Disconnected")
        self.connection_text.setObjectName("ConnectionText")
        top_layout.addWidget(self.connection_dot)
        top_layout.addSpacing(6)
        top_layout.addWidget(self.connection_text)
        root.addWidget(topbar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(340)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 18, 14, 14)
        side_layout.setSpacing(12)

        dialogs_label = QLabel(u"Chats")
        dialogs_label.setObjectName("SectionTitle")
        side_layout.addWidget(dialogs_label)

        self.users = QListWidget()
        self.users.setObjectName("ContactList")
        self.users.setSpacing(4)
        self.users.setFrameShape(QFrame.NoFrame)
        self.users.setSelectionMode(QAbstractItemView.SingleSelection)
        self.users.itemSelectionChanged.connect(self.select_peer)
        side_layout.addWidget(self.users, 1)


        body.addWidget(sidebar)

        conversation = QFrame()
        conversation.setObjectName("Conversation")
        conv_layout = QVBoxLayout(conversation)
        conv_layout.setContentsMargins(0, 0, 0, 0)
        conv_layout.setSpacing(0)

        chat_header = QFrame()
        chat_header.setObjectName("ChatHeader")
        chat_header_layout = QVBoxLayout(chat_header)
        chat_header_layout.setContentsMargins(24, 15, 24, 13)
        chat_header_layout.setSpacing(3)

        self.peer_name = QLabel(u"Select a chat")
        self.peer_name.setObjectName("PeerName")
        chat_header_layout.addWidget(self.peer_name)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.peer_dot = QLabel()
        self.peer_dot.setFixedSize(9, 9)
        self.peer_status = QLabel("")
        self.peer_status.setObjectName("PeerStatus")
        status_row.addWidget(self.peer_dot)
        status_row.addWidget(self.peer_status)
        status_row.addStretch()
        chat_header_layout.addLayout(status_row)
        conv_layout.addWidget(chat_header)

        self.chat = QListWidget()
        self.chat.setObjectName("MessageList")
        self.chat.setFrameShape(QFrame.NoFrame)
        self.chat.setSelectionMode(QAbstractItemView.NoSelection)
        self.chat.setFocusPolicy(Qt.NoFocus)
        self.chat.setSpacing(2)
        conv_layout.addWidget(self.chat, 1)

        composer_wrap = QFrame()
        composer_wrap.setObjectName("ComposerWrap")
        composer_outer = QVBoxLayout(composer_wrap)
        composer_outer.setContentsMargins(22, 12, 22, 18)
        composer_outer.setSpacing(6)


        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("TransferProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat(u"%p%")
        self.progress_bar.setVisible(False)
        composer_outer.addWidget(self.progress_bar)

        composer = QFrame()
        composer.setObjectName("Composer")
        composer_row = QHBoxLayout(composer)
        composer_row.setContentsMargins(10, 8, 10, 8)
        composer_row.setSpacing(7)

        self.file_button = QToolButton()
        self.file_button.setObjectName("IconButton")
        set_button_icon(self.file_button, "file.png", u"File")
        self.file_button.setIconSize(QSize(21, 21))
        self.file_button.setToolTip(u"Send file")
        self.file_button.clicked.connect(self.send_file)

        self.folder_button = QToolButton()
        self.folder_button.setObjectName("IconButton")
        set_button_icon(self.folder_button, "folder.png", u"Folder")
        self.folder_button.setIconSize(QSize(21, 21))
        self.folder_button.setToolTip(u"Send folder")
        self.folder_button.clicked.connect(self.send_folder)

        self.input = QPlainTextEdit()
        self.input.setObjectName("MessageInput")
        self.input.setPlaceholderText(u"Type a message...")
        self.input.setMaximumHeight(72)
        self.input.setMinimumHeight(48)

        self.send_button = QToolButton()
        self.send_button.setObjectName("SendButton")
        set_button_icon(self.send_button, "send_white.png", u">")
        self.send_button.setIconSize(QSize(22, 22))
        self.send_button.setToolTip(u"Send")
        self.send_button.setFixedSize(42, 42)
        self.send_button.clicked.connect(self.send_message)

        composer_row.addWidget(self.file_button)
        composer_row.addWidget(self.folder_button)
        composer_row.addWidget(self.input, 1)
        composer_row.addWidget(self.send_button)
        composer_outer.addWidget(composer)
        conv_layout.addWidget(composer_wrap)

        body.addWidget(conversation, 1)

        self.apply_style()

        self.net = ClientNetwork(
            args.server,
            args.port,
            args.socket_port,
            args.user_id,
            args.client_token,
            args.password_secret,
            args.dest
        )
        self.net.connection_changed.connect(self.on_connection)
        self.net.presence_changed.connect(self.on_presence)
        self.net.message_received.connect(self.on_message_received)
        self.net.message_sent.connect(self.on_message_sent)
        self.net.history_synced.connect(self.on_history_synced)
        self.net.transfer_progress.connect(self.on_transfer_progress)
        self.net.transfer_status.connect(self.on_transfer_status)
        self.net.user_error.connect(self.on_error)
        self.net.fatal_error.connect(self.on_fatal_error)
        self.net.experiment_changed.connect(self.on_experiment_changed)

        self.rebuild_contacts()
        self.select_first_contact()
        self.update_connection_visual(False)
        self.net.start()

    def apply_style(self):
        self.setStyleSheet("""
            QWidget#Root {
                background: #F5F7FA;
                color: #172033;
                font-family: Arial, \"DejaVu Sans\", sans-serif;
                font-size: 14px;
            }
            QFrame#TopBar {
                background: #FFFFFF;
                border-bottom: 1px solid #E5EAF0;
            }
            QLabel#BrandLogo {
                background: transparent;
            }
            QLabel#ConnectionText {
                color: #4B5563;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#ExperimentState {
                color: #1D4ED8;
                background: #EEF4FF;
                border: 1px solid #D8E5FF;
                border-radius: 9px;
                padding: 4px 9px;
                font-size: 12px;
                font-weight: 700;
            }
            QFrame#Sidebar {
                background: #FFFFFF;
                border-right: 1px solid #E5EAF0;
            }
            QLabel#SectionTitle {
                color: #111827;
                font-size: 17px;
                font-weight: 700;
                padding-left: 4px;
            }
            QListWidget#ContactList {
                background: transparent;
                outline: 0;
                border: 0;
            }
            QListWidget#ContactList::item {
                background: transparent;
                border: 0;
                border-radius: 10px;
            }
            QListWidget#ContactList::item:selected {
                background: #EEF4FF;
            }
            QListWidget#ContactList::item:hover {
                background: #F5F7FB;
            }
            QLabel#ContactName {
                color: #172033;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#ContactId {
                color: #94A3B8;
                font-size: 11px;
            }
            QLabel#ContactStatus {
                color: #64748B;
                font-size: 11px;
            }
            QLabel#ContactPreview {
                color: #667085;
                font-size: 12px;
            }
            QLabel#ContactTime {
                color: #98A2B3;
                font-size: 11px;
            }
            QFrame#Conversation {
                background: #F8FAFC;
            }
            QFrame#ChatHeader {
                background: #FFFFFF;
                border-bottom: 1px solid #E5EAF0;
            }
            QLabel#PeerName {
                color: #111827;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#PeerStatus {
                color: #667085;
                font-size: 12px;
            }
            QListWidget#MessageList {
                background: #F8FAFC;
                border: 0;
                padding: 14px 12px 8px 12px;
                outline: 0;
            }
            QFrame#OwnBubble {
                background: #E8F0FF;
                border: 1px solid #D8E5FF;
                border-radius: 12px;
            }
            QFrame#PeerBubble {
                background: #FFFFFF;
                border: 1px solid #E5EAF0;
                border-radius: 12px;
            }
            QLabel#MessageText, QLabel#FileText {
                color: #172033;
                font-size: 14px;
                font-weight: 500;
            }
            QLabel#FileText {
                font-weight: 600;
            }
            QLabel#MessageTime {
                color: #7C8798;
                font-size: 11px;
            }
            QFrame#ComposerWrap {
                background: #FFFFFF;
                border-top: 1px solid #E5EAF0;
            }
            QProgressBar#TransferProgress {
                background: #E9EEF5;
                border: 1px solid #D6DEE8;
                border-radius: 7px;
                height: 16px;
                text-align: center;
                color: #172033;
                font-size: 11px;
                font-weight: 700;
            }
            QProgressBar#TransferProgress::chunk {
                background: #2563EB;
                border-radius: 6px;
            }
            QFrame#Composer {
                background: #F7F9FC;
                border: 1px solid #DDE3EA;
                border-radius: 13px;
            }
            QPlainTextEdit#MessageInput {
                background: transparent;
                color: #172033;
                border: 0;
                font-size: 14px;
                selection-background-color: #C7D7FE;
            }
            QToolButton#IconButton {
                background: transparent;
                border: 0;
                border-radius: 8px;
                padding: 7px;
            }
            QToolButton#IconButton:hover {
                background: #E9EEF5;
            }
            QToolButton#SendButton {
                background: #2563EB;
                border: 0;
                border-radius: 21px;
            }
            QToolButton#SendButton:hover {
                background: #1D4ED8;
            }
            QToolButton#SendButton:disabled {
                background: #AFC4F5;
            }
        """)

    def closeEvent(self, event):
        self.net.stop()
        QMainWindow.closeEvent(self, event)

    def update_connection_visual(self, connected):
        self.connected = connected
        if connected:
            self.connection_dot.setStyleSheet("background:#22C55E; border-radius:5px;")
            self.connection_text.setText(u"Connected")
        else:
            self.connection_dot.setStyleSheet("background:#94A3B8; border-radius:5px;")
            self.connection_text.setText(u"Disconnected")

        allow_send = connected and self.current_peer is not None
        self.send_button.setEnabled(allow_send)
        self.file_button.setEnabled(allow_send)
        self.folder_button.setEnabled(allow_send)
        self.update_peer_header()

    def on_connection(self, connected):
        self.update_connection_visual(connected)
        if not connected and not self._experiment_active:
            self.online_map = {}
            self.schedule_contacts_rebuild()

    def on_experiment_changed(self, info):
        status = str(info.get("status", ""))
        if status in ("running", "phase", "starting"):
            self._experiment_active = True
            label = str(info.get("label") or self._experiment_label or "traffic test")
            self._experiment_label = label
            self.experiment_text.setText(u"Test: %s" % label)
            self.experiment_text.setVisible(True)
            return

        if status in ("completed", "stopped", "error"):
            self._experiment_active = False
            self._experiment_label = ""
            self.experiment_text.setVisible(False)
            self.schedule_contacts_rebuild()

    def on_presence(self, users):
        self.online_map = {}
        peers = []
        for u in users:
            uid = u['user_id']
            if uid == self.args.user_id:
                continue
            self.cache.upsert_contact(
                uid,
                u.get('name', uid),
                u.get('role', 'client')
            )




            if uid == 'server':
                self.online_map[uid] = bool(self.connected)
            else:
                self.online_map[uid] = bool(u.get('online'))

            peers.append(uid)

        self.schedule_contacts_rebuild()
        self.net.sync_histories(peers)
        self.update_peer_header()

    def contact_state(self, user_id):
        if not self.connected:
            return 'unknown', u'Status unknown'




        if user_id == 'server':
            return 'online', u'Online'

        online = self.online_map.get(user_id, False)
        if online:
            return 'online', u'Online'
        return 'offline', u'Offline'

    def schedule_contacts_rebuild(self):
        # Restarting a single-shot timer collapses a burst of presence/message
        # events into one contact-list rebuild.
        self._contacts_timer.start()

    def schedule_chat_render(self):
        # Chat rendering creates QWidget bubbles, so never rebuild it once per
        # network event when several events arrive together.
        self._chat_timer.start()

    def rebuild_contacts(self):
        selected = self.current_peer
        self.users.blockSignals(True)
        self.users.clear()

        for row in self.cache.list_contacts():
            uid = row['user_id']
            status_kind, status_text = self.contact_state(uid)
            time_text = self.format_contact_time(row['last_activity_at'])
            item = QListWidgetItem()
            item.setData(Qt.UserRole, uid)
            widget = ContactWidget(
                row['name'], uid, status_text, status_kind,
                row['last_preview'] or '', time_text
            )
            item.setSizeHint(widget.sizeHint())
            self.users.addItem(item)
            self.users.setItemWidget(item, widget)
            if uid == selected:
                item.setSelected(True)

        self.users.blockSignals(False)

    def select_first_contact(self):
        if self.users.count() > 0:
            self.users.setCurrentRow(0)
            self.select_peer()

    def select_peer(self):
        items = self.users.selectedItems()
        if not items:
            return
        self.current_peer = items[0].data(Qt.UserRole)
        self.update_peer_header()
        self.render_cached_chat()
        allow_send = self.connected and self.current_peer is not None
        self.send_button.setEnabled(allow_send)
        self.file_button.setEnabled(allow_send)
        self.folder_button.setEnabled(allow_send)
        if self.connected:
            self.net.sync_history(self.current_peer)

    def update_peer_header(self):
        if not self.current_peer:
            self.peer_name.setText(u"Select a chat")
            self.peer_status.setText("")
            self.peer_dot.setStyleSheet("background:transparent;")
            return

        name = self.contact_name(self.current_peer)
        self.peer_name.setText(name)
        kind, text = self.contact_state(self.current_peer)
        color = {
            'online': '#22C55E',
            'offline': '#94A3B8',
            'unknown': '#F59E0B'
        }.get(kind, '#94A3B8')
        self.peer_dot.setStyleSheet('background:%s; border-radius:4px;' % color)
        self.peer_status.setText(text)

    def render_cached_chat(self):
        self.chat.clear()
        if not self.current_peer:
            return
        rows = self.cache.get_messages(self.current_peer)
        for row in rows:
            own = (row['sender_id'] == self.args.user_id)
            file_status = (row['message_type'] == 'file_status')
            widget = MessageBubble(
                row['text'],
                self.format_chat_time(row['created_at']),
                own=own,
                file_status=file_status
            )
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.chat.addItem(item)
            self.chat.setItemWidget(item, widget)
        if self.chat.count() > 0:
            self.chat.scrollToBottom()

    def send_message(self):
        if not self.connected:
            self.on_error(u"No connection to server")
            return
        if not self.current_peer:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.net.send_message(self.current_peer, text)
        self.input.clear()

    def on_message_sent(self, msg):
        peer = msg.get('to')
        self._cache_message(msg, peer)
        self.schedule_contacts_rebuild()
        if peer == self.current_peer:
            self.schedule_chat_render()

    def on_message_received(self, msg):
        peer = msg.get('from')
        self._cache_message(msg, peer)
        self.schedule_contacts_rebuild()
        if peer == self.current_peer:
            self.schedule_chat_render()

    def on_history_synced(self, peer, messages):
        if not messages:
            return

        role = 'server' if peer == 'server' else 'client'
        self.cache.upsert_contact(peer, self.contact_name(peer), role)
        batch = []
        for msg in messages:
            values = self._cache_values(msg, peer)
            batch.append({
                'server_message_id': values[0],
                'peer_id': peer,
                'sender_id': values[1],
                'recipient_id': values[2],
                'message_type': values[3],
                'text': values[4],
                'created_at': values[5],
            })
        self.cache.add_messages_batch(batch)

        if peer == self.current_peer:
            self.schedule_chat_render()
        self.schedule_contacts_rebuild()

    def _cache_values(self, msg, peer):
        mid = msg.get('id') or msg.get('message_id')
        created_at = msg.get('created_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sender = msg.get('from', self.args.user_id)
        recipient = msg.get('to', peer)
        msg_type = msg.get('type', 'text')
        if msg_type in ('message', 'message_ack'):
            msg_type = msg.get('message_type', 'text')
        return mid, sender, recipient, msg_type, msg.get('text', ''), created_at

    def _cache_message(self, msg, peer):
        mid, sender, recipient, msg_type, text, created_at = (
            self._cache_values(msg, peer)
        )
        role = 'server' if peer == 'server' else 'client'
        self.cache.upsert_contact(peer, self.contact_name(peer), role)
        self.cache.add_message(
            mid, peer, sender, recipient, msg_type, text, created_at
        )

    def send_file(self):
        if not self.connected:
            self.on_error(u"No connection to server")
            return
        if not self.current_peer:
            return
        path = QFileDialog.getOpenFileName(self, u"Select file")[0]
        if path:
            self.prepare_progress(Path(path).name, u"Sending file...")
            self.net.send_path(self.current_peer, path)

    def send_folder(self):
        if not self.connected:
            self.on_error(u"No connection to server")
            return
        if not self.current_peer:
            return
        path = QFileDialog.getExistingDirectory(self, u"Select folder")
        if path:
            self.prepare_progress(Path(path).name, u"Sending folder...")
            self.net.send_path(self.current_peer, path)

    def prepare_progress(self, name, prefix):
        self.current_progress_name = name
        self.progress_bar.setToolTip(prefix + u" " + name)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(name + u" - %p%")
        self.progress_bar.setVisible(True)

    def on_transfer_progress(self, name, percent):
        self.current_progress_name = name
        if not self.progress_bar.isVisible():
            self.progress_bar.setVisible(True)
        self.progress_bar.setToolTip(name)
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(name + u" - %p%")

    def on_transfer_status(self, info):
        text = info.get('text', '')
        peer = info.get('peer') or self.current_peer
        status = info.get('status')
        self.progress_bar.setToolTip(text)

        if status == 'error':
            if self.current_progress_name:
                self.progress_bar.setVisible(True)
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat(u"Error")
            QTimer.singleShot(4000, self.hide_progress)
            return


        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat(u"Done")
        QTimer.singleShot(2200, self.hide_progress)

        if not peer:
            return
        created = info.get('created_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        mid = info.get('message_id')
        sender = info.get('sender_id')
        recipient = info.get('recipient_id')
        direction = info.get('direction')
        if not sender:
            if direction == 'incoming':
                sender = peer
                recipient = self.args.user_id
            else:
                sender = self.args.user_id
                recipient = peer
        role = 'server' if peer == 'server' else 'client'
        self.cache.upsert_contact(peer, self.contact_name(peer), role)
        self.cache.add_message(mid, peer, sender, recipient or peer, 'file_status', text, created)




        if peer == self.current_peer:
            self.schedule_chat_render()

        self.schedule_contacts_rebuild()

    def hide_progress(self):
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(u"%p%")
        self.progress_bar.setToolTip("")
        self.current_progress_name = None

    def switch_account(self):
        # Confirmation must be the very first operation. Choosing No must be
        # a true no-op: keep the network session, current identity, config,
        # cache, contacts and chat history untouched.
        answer = QMessageBox.question(
            self,
            APP_NAME,
            "Switch to a new account?\n\n"
            "The local chat history of the current account will be "
            "permanently deleted. A new device identity will be created "
            "and the administrator will need to approve it again.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        values = {
            "server_ip": self.args.server,
            "display_name": self.args.display_name,
            "client_token": self.args.client_token,
            "user_id": self.args.user_id,
            "download_dir": self.args.dest,
            "http_port": self.args.port,
            "socket_port": self.args.socket_port,
        }

        # Destructive work starts only after an explicit Yes.
        self.net.stop()

        dialog = ClientSetupDialog(
            self.config_path,
            values,
            first_run=False,
            parent=self,
            cache_path=self.args.cache
        )

        if not dialog.prepare_new_account():
            self.net.start()
            return

        if dialog_exec(dialog) == QDialog.Accepted:
            new_args = build_runtime_args(
                dialog.saved_values,
                self.args.cache_override
            )
            new_window = MainWindow(
                new_args,
                self.config_path
            )
            app = QApplication.instance()
            app._interchange_main_window = new_window
            new_window.show()
            self.close()
            return

        self.net.start()

    def contact_name(self, user_id):
        for row in self.cache.list_contacts():
            if row['user_id'] == user_id:
                return row['name']
        return user_id

    def on_error(self, text):
        QMessageBox.warning(self, APP_NAME, text)

    def on_fatal_error(self, text):




        if self._reauth_in_progress:
            return

        self._reauth_in_progress = True
        self.net.stop()
        self.update_connection_visual(False)

        values = {
            "server_ip": self.args.server,
            "display_name": self.args.display_name,
            "client_token": self.args.client_token,
            "user_id": self.args.user_id,
            "download_dir": self.args.dest,
            "http_port": self.args.port,
            "socket_port": self.args.socket_port,
        }

        self.hide()

        dialog = ClientSetupDialog(
            self.config_path,
            values,
            first_run=False,
            parent=None,
            reauth=True,
            error_message=text,
            cache_path=self.args.cache
        )

        if dialog_exec(dialog) == QDialog.Accepted:
            new_args = build_runtime_args(
                dialog.saved_values,
                self.args.cache_override
            )

            new_window = MainWindow(new_args, self.config_path)
            app = QApplication.instance()


            app._interchange_main_window = new_window
            new_window.show()
            self.close()
            return

        self.close()
        QApplication.instance().quit()

    @staticmethod
    def format_contact_time(value):
        if not value:
            return ''
        dt = parse_sqlite_datetime(value)
        return dt.strftime('%H:%M') if dt else ''

    @staticmethod
    def format_chat_time(value):
        if not value:
            return ''
        dt = parse_sqlite_datetime(value)
        return dt.strftime('%H:%M') if dt else value


def parse_args():
    p = argparse.ArgumentParser(description='Interchange GUI client')
    p.add_argument('--config', default=None)
    p.add_argument('--server', default=None)
    p.add_argument('--name', default=None)
    p.add_argument('--user-id', default=None)
    p.add_argument('--dest', default=None)
    p.add_argument('--port', type=int, default=None)
    p.add_argument('--socket-port', type=int, default=None)
    p.add_argument('--cache', default=None,
                   help=u'Local SQLite cache for recent conversations')
    p.add_argument('--self-test', action='store_true',
                   help=argparse.SUPPRESS)
    return p.parse_args()


def resolve_settings(cli_args, config_values):
    values = dict(config_values)
    if cli_args.server:
        values['server_ip'] = cli_args.server
    if cli_args.name:
        values['display_name'] = cli_args.name
    if cli_args.user_id:
        values['user_id'] = cli_args.user_id
    if cli_args.dest:
        values['download_dir'] = cli_args.dest
    if cli_args.port is not None:
        values['http_port'] = cli_args.port
    if cli_args.socket_port is not None:
        values['socket_port'] = cli_args.socket_port
    return values


def account_cache_path(values, cache_override=None):
    if cache_override is not None:
        return str(Path(cache_override).expanduser())

    user_id = str(values.get("user_id", "")).strip()
    if not user_id:
        return None

    return str(
        Path.home()
        / ".interchange"
        / ("%s_cache.db" % user_id)
    )


def build_runtime_args(values, cache_override=None):
    dest = str(Path(values['download_dir']).expanduser())
    Path(dest).mkdir(parents=True, exist_ok=True)

    args = argparse.Namespace()
    args.server = values['server_ip']
    args.display_name = values['display_name']
    args.client_token = values['client_token']
    args.user_id = values['user_id']
    args.password_secret = int(values['password_secret'])
    args.dest = dest
    args.port = int(values['http_port'])
    args.socket_port = int(values['socket_port'])
    args.cache_override = cache_override

    if cache_override is None:
        args.cache = account_cache_path(values, None)
    else:
        args.cache = str(Path(cache_override).expanduser())

    return args


def main():
    configure_logging()
    cli_args = parse_args()
    config_path = Path(cli_args.config or default_config_path()).expanduser()

    app = QApplication([])
    app.setApplicationName(APP_NAME)

    if cli_args.self_test:
        missing = [str(path) for path in required_ui_resources() if not path.is_file()]
        if missing:
            logging.error("Client self-test failed; missing UI resources: %s", missing)
            return 2
        print("Interchange self-test OK: Qt API=%s platform=%s resources=OK" % (
            QT_API, app.platformName() if hasattr(app, "platformName") else "unknown"
        ))
        return 0

    values = resolve_settings(cli_args, load_client_config(config_path))


    first_run = (
        not config_path.exists()
        or not is_client_config_complete(values)
    )
    dialog = ClientSetupDialog(
        config_path,
        values,
        first_run=first_run,
        parent=None,
        cache_path=account_cache_path(values, cli_args.cache)
    )
    if dialog_exec(dialog) != QDialog.Accepted:
        return
    values = dialog.saved_values

    args = build_runtime_args(values, cli_args.cache)

    window = MainWindow(args, config_path)
    app._interchange_main_window = window
    window.show()
    app_exec(app)


if __name__ == '__main__':
    sys.exit(main() or 0)
