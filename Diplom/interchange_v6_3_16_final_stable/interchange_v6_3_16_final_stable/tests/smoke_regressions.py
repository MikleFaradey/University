import ast
import importlib.util
import json
import pathlib
import tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pcap_dumpcap_interface_parsing():
    mod = load('pcap_manager_test', ROOT / 'server' / 'pcap_manager.py')
    with tempfile.TemporaryDirectory() as td:
        manager = mod.PcapManager(td)
        manager._find_program = lambda name: 'dumpcap' if name == 'dumpcap' else None
        completed = mock.Mock(returncode=0, stdout='1. Ethernet\n2. Wi-Fi\n', stderr='')
        with mock.patch.object(mod.subprocess, 'run', return_value=completed):
            assert manager._dumpcap_interfaces() == [('1', 'Ethernet'), ('2', 'Wi-Fi')]


def test_one_second_metric_math():
    mod = load('parser_metric_test', ROOT / 'parser' / 'pcap_to_csv.py')
    bucket = mod.make_empty_window()
    bucket.update({
        'packet_count': 4,
        'total_bytes': 1000,
        'client_to_server_packets': 3,
        'server_to_client_packets': 1,
        'client_to_server_bytes': 700,
        'server_to_client_bytes': 300,
        'tcp_packets': 3,
        'udp_packets': 1,
        'syn_count': 2,
        'syn_ack_count': 1,
        'fin_count': 1,
        'rst_count': 1,
        'psh_count': 2,
        'http_packets': 2,
        'socket_packets': 2,
        'http_client_payload_packets': 1,
        'small_packet_count': 2,
        'packet_sizes': [100, 200, 300, 400],
        'interarrivals': [0.1, 0.2, 0.3],
        'flows': {('a', 1), ('b', 2), ('c', 3)},
        'new_tcp_flows': {('a', 1), ('b', 2)},
    })
    features = mod.finalize_window(bucket)
    assert features['packet_count'] == 4
    assert features['total_bytes'] == 1000
    assert features['packets_per_sec'] == 4.0
    assert features['bytes_per_sec'] == 1000.0
    assert features['new_tcp_connections'] == 2
    assert features['unique_flows'] == 3
    assert abs(features['small_packet_ratio'] - 0.5) < 1e-12
    assert abs(features['client_to_server_packet_ratio'] - 0.75) < 1e-12
    assert abs(features['client_to_server_byte_ratio'] - 0.7) < 1e-12
    assert abs(features['avg_packet_size'] - 250.0) < 1e-12
    assert abs(features['avg_interarrival'] - 0.2) < 1e-12

    try:
        mod.finalize_window(bucket, 5.0)
    except ValueError:
        pass
    else:
        raise AssertionError('non-1-second metric window was accepted')


def test_one_second_window_policy():
    mod = load('parser_window_policy_test', ROOT / 'parser' / 'pcap_to_csv.py')
    assert mod.FIXED_WINDOW_SEC == 1.0
    assert mod.DEFAULT_WINDOW_SEC == 1.0
    assert mod.resolve_fixed_window({}, None) == 1.0
    assert mod.resolve_fixed_window({'window_sec': 1}, 1) == 1.0

    try:
        mod.resolve_fixed_window({}, 0.5)
    except ValueError:
        pass
    else:
        raise AssertionError('parser accepted a non-1-second override')

    assert mod.validate_fixed_timeline([
        {'start_sec': 0, 'end_sec': 1, 'label': 'NORMAL'},
        {'start_sec': 1, 'end_sec': 3, 'label': 'HIGH_REQUEST_RATE'},
    ]) == 3

    try:
        mod.validate_fixed_timeline([
            {'start_sec': 0, 'end_sec': 1.5, 'label': 'NORMAL'},
        ])
    except ValueError:
        pass
    else:
        raise AssertionError('fractional timeline boundary was accepted')

    server_source = (ROOT / 'server' / 'server.py').read_text(encoding='utf-8')
    assert 'DATASET_WINDOW_SEC = 1' in server_source
    assert '"window_sec": DATASET_WINDOW_SEC' in server_source
    assert '"dataset_duration_sec": _dataset_duration_for_run(' in server_source
    assert 'multiples of 5 seconds' not in server_source


def test_cross_window_interarrival_and_syn_deduplication():
    mod = load('parser_cross_window_test', ROOT / 'parser' / 'pcap_to_csv.py')

    class IP(object):
        pass

    class IPv6(object):
        pass

    class TCP(object):
        pass

    class UDP(object):
        pass

    class Raw(object):
        pass

    class Layer(object):
        def __init__(self, **values):
            for key, value in values.items():
                setattr(self, key, value)

        def __bytes__(self):
            return getattr(self, '_payload', b'')

    class Packet(object):
        def __init__(self, timestamp, size, layers):
            self.time = timestamp
            self._size = size
            self._layers = layers

        def __contains__(self, key):
            return key in self._layers

        def __getitem__(self, key):
            return self._layers[key]

        def __bytes__(self):
            return b'x' * self._size

    packets = [
        Packet(100.2, 100, {
            IP: Layer(src='10.0.0.2', dst='10.0.0.1'),
            TCP: Layer(flags=0x02, sport=50000, dport=8080, seq=1000),
        }),
        Packet(101.2, 120, {
            IP: Layer(src='10.0.0.2', dst='10.0.0.1'),
            TCP: Layer(flags=0x02, sport=50001, dport=8080, seq=2000),
        }),
        Packet(101.4, 120, {
            IP: Layer(src='10.0.0.2', dst='10.0.0.1'),
            TCP: Layer(flags=0x02, sport=50001, dport=8080, seq=2000),
        }),
    ]

    class Reader(object):
        def __init__(self, path):
            self._packets = packets

        def __iter__(self):
            return iter(self._packets)

        def close(self):
            pass

    mod.load_scapy = lambda: (Reader, IP, IPv6, TCP, UDP, Raw)

    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        pcap = td / 'run.pcap'
        pcap.write_bytes(b'fake')
        metadata = td / 'run.json'
        metadata.write_text(json.dumps({
            'experiment_id': 1,
            'target_client_ip': '10.0.0.2',
            'experiment_start_epoch': 100.0,
            'clock_source': 'server',
            'window_sec': 1,
            'dataset_duration_sec': 2,
            'timeline': [
                {'start_sec': 0, 'end_sec': 2, 'label': 'NORMAL'}
            ],
            'server_http_port': 8080,
            'server_socket_port': 8081,
        }), encoding='utf-8')

        rows = mod.parse_pair(pcap, metadata)

    assert len(rows) == 2
    assert rows[0]['window_duration_sec'] == 1.0
    assert rows[0]['packet_count'] == 1
    assert rows[0]['packets_per_sec'] == 1.0
    assert rows[0]['avg_interarrival'] == 0.0
    assert rows[1]['packet_count'] == 2
    assert rows[1]['packets_per_sec'] == 2.0
    assert abs(rows[1]['avg_interarrival'] - 0.6) < 1e-9
    assert rows[1]['syn_count'] == 2
    assert rows[1]['new_tcp_connections'] == 1



def test_server_fixed_window_duration_and_timeline():
    import sys
    server_dir = str(ROOT / 'server')
    sys.path.insert(0, server_dir)
    try:
        mod = load('server_policy_test', ROOT / 'server' / 'server.py')
    finally:
        try:
            sys.path.remove(server_dir)
        except ValueError:
            pass

    timeline = mod._normalize_timeline([
        {'start_sec': 0, 'end_sec': 2, 'label': 'NORMAL'},
        {'start_sec': 2, 'end_sec': 5, 'label': 'HIGH_REQUEST_RATE'},
    ])
    assert timeline[-1]['end_sec'] == 5

    try:
        mod._normalize_timeline([
            {'start_sec': 0, 'end_sec': 1.5, 'label': 'NORMAL'},
        ])
    except RuntimeError as exc:
        assert 'whole seconds' in str(exc)
    else:
        raise AssertionError('server accepted a fractional timeline boundary')

    assert mod._dataset_duration_for_run({
        'status': 'completed',
        'experiment_start_epoch': 100.0,
        'experiment_end_epoch': 106.4,
    }, 5) == 5
    assert mod._dataset_duration_for_run({
        'status': 'stopped',
        'experiment_start_epoch': 100.0,
        'experiment_end_epoch': 104.9,
    }, 10) == 4
    assert mod._dataset_duration_for_run({
        'status': 'error',
        'experiment_start_epoch': None,
        'experiment_end_epoch': None,
    }, 10) == 0

def test_utf8_metadata_write():
    mod = load('pcap_manager_utf8_test', ROOT / 'server' / 'pcap_manager.py')
    with tempfile.TemporaryDirectory() as td:
        manager = mod.PcapManager(td)
        pcap = pathlib.Path(td) / 'run.pcap'
        path = manager.write_metadata(str(pcap), {'baseline': 'данные'})
        payload = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
        assert payload['baseline'] == 'данные'



def test_linux_deb_upgrade_policy():
    linux_dir = ROOT / 'installer' / 'linux' / 'client'
    build = (linux_dir / 'build_client_deb.sh').read_text(encoding='utf-8')
    launcher = (linux_dir / 'interchange-client').read_text(encoding='utf-8')
    preinst = (linux_dir / 'preinst').read_text(encoding='utf-8')
    postrm = (linux_dir / 'postrm').read_text(encoding='utf-8')

    assert 'VERSION="6.3.16"' in build
    assert 'Architecture: $ARCH' in build
    assert 'python3-pyqt5' in build
    assert '/usr/lib/interchange-client' in build
    assert '/usr/lib/interchange-client' in launcher
    assert 'INTERCHANGE_QT_API=PyQt5' in launcher
    assert '--diagnose' in launcher
    assert 'dpkg --compare-versions' in preinst
    assert 'interchange-upgrade-638' in preinst
    assert 'rm -rf /opt/interchange/client' not in postrm



def test_shared_live_feature_schema():
    import sys
    server_dir = str(ROOT / 'server')
    sys.path.insert(0, server_dir)
    try:
        parser_mod = load('parser_shared_schema_test', ROOT / 'parser' / 'pcap_to_csv.py')
        feature_mod = load('traffic_features_schema_test', ROOT / 'server' / 'traffic_features.py')
    finally:
        try:
            sys.path.remove(server_dir)
        except ValueError:
            pass

    assert parser_mod.FIXED_WINDOW_SEC == 1.0
    assert parser_mod.CSV_COLUMNS[-len(feature_mod.FEATURE_COLUMNS):] == feature_mod.FEATURE_COLUMNS
    assert parser_mod.finalize_window.__module__ == 'traffic_features'
    assert len(feature_mod.FEATURE_COLUMNS) == 28
    assert feature_mod.MODEL_AVAILABLE_FEATURES[0] == 'window_duration_sec'


def test_model_runtime_multiclass_result():
    import sys
    import types
    server_dir = str(ROOT / 'server')
    sys.path.insert(0, server_dir)
    try:
        traffic = load('traffic_features_model_test', ROOT / 'server' / 'traffic_features.py')
        runtime = load('model_runtime_test', ROOT / 'server' / 'model_runtime.py')
    finally:
        try:
            sys.path.remove(server_dir)
        except ValueError:
            pass

    class FakeModel(object):
        n_features_in_ = len(traffic.FEATURE_COLUMNS)
        classes_ = ['NORMAL', 'FREQUENT_RECONNECT']

        def predict(self, rows):
            assert len(rows[0]) == len(traffic.FEATURE_COLUMNS)
            return ['FREQUENT_RECONNECT']

        def predict_proba(self, rows):
            return [[0.08, 0.92]]

    fake_joblib = types.SimpleNamespace(load=lambda path: FakeModel())
    old_joblib = sys.modules.get('joblib')
    sys.modules['joblib'] = fake_joblib
    try:
        with tempfile.TemporaryDirectory() as td:
            model_path = pathlib.Path(td) / 'rf.joblib'
            model_path.write_bytes(b'test')
            manager = runtime.ModelManager()
            status = manager.load(model_path)
            assert status['loaded'] is True
            assert status['window_sec'] == 1.0
            assert status['classes'] == ['NORMAL', 'FREQUENT_RECONNECT']

            metrics = traffic.finalize_window(traffic.make_empty_window())
            result = manager.predict_window(
                'client-1', '10.0.0.2', 100.0, metrics
            )
            assert result['status'] == 'ANOMALY'
            assert result['prediction'] == 'FREQUENT_RECONNECT'
            assert result['anomaly_type'] == 'FREQUENT_RECONNECT'
            assert abs(result['confidence'] - 0.92) < 1e-12
            assert result['class_probabilities']['NORMAL'] == 0.08
            assert result['class_probabilities']['FREQUENT_RECONNECT'] == 0.92
    finally:
        if old_joblib is None:
            sys.modules.pop('joblib', None)
        else:
            sys.modules['joblib'] = old_joblib




def test_experiment_force_delete_wiring():
    server_source = (ROOT / 'server' / 'server.py').read_text(encoding='utf-8')
    admin_source = (ROOT / 'server' / 'admin_panel.py').read_text(encoding='utf-8')
    client_source = (ROOT / 'client' / 'client_network.py').read_text(encoding='utf-8')
    db_source = (ROOT / 'server' / 'db.py').read_text(encoding='utf-8')

    assert '/admin/experiment/delete' in server_source
    assert 'def delete_experiment(' in server_source
    assert 'experiment_force_stop' in server_source
    assert 'Force stop & delete' in admin_source
    assert 'def _force_stop_experiment(' in client_source
    assert 'args=(run_id, timeline, params, stop_event)' in client_source
    assert 'def delete_experiment_run(' in db_source


def test_model_monitor_wiring():
    server_source = (ROOT / 'server' / 'server.py').read_text(encoding='utf-8')
    admin_source = (ROOT / 'server' / 'admin_panel.py').read_text(encoding='utf-8')
    monitor_source = (ROOT / 'server' / 'live_monitor.py').read_text(encoding='utf-8')

    assert '/admin/model/load' in server_source
    assert '/admin/model/unload' in server_source
    assert '/admin/model/monitor' in server_source
    assert 'LiveTrafficMonitor' in server_source
    assert 'Model & traffic' in admin_source
    assert 'Class / anomaly type' in admin_source
    assert 'predict_window' in monitor_source
    assert 'PcapReader' in monitor_source
    assert 'import csv' not in monitor_source
    assert 'FIXED_WINDOW_SEC' in monitor_source


def test_training_pcap_progress_wiring():
    admin_source = (ROOT / 'server' / 'admin_panel.py').read_text(encoding='utf-8')
    assert 'Training PCAP preparation' in admin_source
    assert 'self.training_pcap_progress = QProgressBar()' in admin_source
    assert 'percent = min(99, percent)' in admin_source
    assert 'Finalizing PCAP capture...' in admin_source
    assert 'PCAP ready' in admin_source


def test_model_test_manager_scores_live_windows_without_pcap():
    import sys
    server_dir = str(ROOT / 'server')
    sys.path.insert(0, server_dir)
    try:
        mod = load('model_test_manager_test', ROOT / 'server' / 'model_test.py')
    finally:
        try:
            sys.path.remove(server_dir)
        except ValueError:
            pass

    class FakeHub(object):
        def __init__(self):
            self.sent = []
        def online_users(self):
            return {'client-1'}
        def send_to(self, user_id, payload):
            self.sent.append((user_id, dict(payload)))
            return True

    class FakeModel(object):
        def __init__(self):
            self.rows = []
        def status(self):
            return {'loaded': True}
        def history_for(self, user_id):
            return list(self.rows)

    class FakeMonitor(object):
        def snapshot(self):
            return {
                'model': {'loaded': True},
                'capture': {'state': 'running'},
                'clients': [{'user_id': 'client-1'}],
            }

    fake_user = {'active': 1}
    old_get_user = mod.db.get_user
    old_active = mod.db.get_active_experiment_for_user
    mod.db.get_user = lambda user_id: fake_user
    mod.db.get_active_experiment_for_user = lambda user_id: None
    try:
        hub = FakeHub()
        model = FakeModel()
        manager = mod.ModelTestManager(hub, model, FakeMonitor())
        timeline = [
            {'start_sec': 0, 'end_sec': 10, 'label': 'NORMAL', 'params': {}},
        ]
        started = manager.start('client-1', '/tmp/baseline', timeline)
        test_id = started['test_id']
        assert test_id < 0
        assert hub.sent[-1][1]['type'] == 'experiment_start'
        assert hub.sent[-1][1]['params']['record_pcap'] is False
        assert manager.handle_status('client-1', {
            'run_id': test_id, 'status': 'running'
        }) is True
        origin = manager.snapshot()['start_epoch']
        model.rows.append({
            'window_start_epoch': origin + 1.0,
            'window_end_epoch': origin + 2.0,
            'prediction': 'NORMAL',
            'confidence': 0.93,
        })
        manager._collect_results(test_id)
        snapshot = manager.snapshot()
        assert snapshot['record_pcap'] is False
        assert snapshot['record_csv'] is False
        assert snapshot['summary']['scored_windows'] == 1
        assert snapshot['summary']['correct_windows'] == 1
        assert abs(snapshot['summary']['accuracy'] - 1.0) < 1e-12
        assert snapshot['results'][0]['expected'] == 'NORMAL'
        assert snapshot['results'][0]['prediction'] == 'NORMAL'
        manager.stop()
    finally:
        mod.db.get_user = old_get_user
        mod.db.get_active_experiment_for_user = old_active


def test_model_test_http_and_ui_wiring():
    server_source = (ROOT / 'server' / 'server.py').read_text(encoding='utf-8')
    admin_source = (ROOT / 'server' / 'admin_panel.py').read_text(encoding='utf-8')
    model_test_source = (ROOT / 'server' / 'model_test.py').read_text(encoding='utf-8')
    assert '/admin/model/test/start' in server_source
    assert '/admin/model/test/stop' in server_source
    assert '/admin/model/test/status' in server_source
    assert 'ModelTestManager' in server_source
    assert 'Model test' in admin_source
    assert 'Use training scenario' in admin_source
    assert 'Run live model test' in admin_source
    assert 'Per-second validation results' in admin_source
    assert 'record_pcap' in model_test_source
    assert 'PcapManager' not in model_test_source
    assert 'import csv' not in model_test_source
    assert 'PcapManager' not in model_test_source
    monitor_source = (ROOT / 'server' / 'live_monitor.py').read_text(encoding='utf-8')
    assert '_client_grace_sec = 10.0' in monitor_source


def test_admin_long_pages_are_scrollable():
    qt_source = (ROOT / 'server' / 'qt_compat.py').read_text(encoding='utf-8')
    admin_source = (ROOT / 'server' / 'admin_panel.py').read_text(encoding='utf-8')
    assert 'QScrollArea' in qt_source
    assert 'QScrollArea' in admin_source
    assert 'self.experiment_scroll = QScrollArea()' in admin_source
    assert 'self.model_test_scroll = QScrollArea()' in admin_source
    assert 'setWidgetResizable(True)' in admin_source
    assert 'self.setMinimumSize(760, 500)' in admin_source
    assert 'self.model_test_timeline.setMinimumHeight(210)' in admin_source
    assert 'self.model_test_results.setMinimumHeight(230)' in admin_source


def test_random_forest_training_pipeline_wiring():
    train_path = ROOT / 'server' / 'ml' / 'train_random_forest.py'
    check_path = ROOT / 'server' / 'ml' / 'check_model.py'
    readme_path = ROOT / 'server' / 'ml' / 'README.md'
    assert train_path.exists()
    assert check_path.exists()
    assert readme_path.exists()

    train_source = train_path.read_text(encoding='utf-8')
    check_source = check_path.read_text(encoding='utf-8')
    assert 'from traffic_features import FEATURE_COLUMNS, FIXED_WINDOW_SEC' in train_source
    assert 'GroupShuffleSplit' in train_source
    assert 'class_weight="balanced_subsample"' in train_source
    assert 'window_duration_sec' in train_source
    assert 'feature_schema_sha256' in train_source
    assert 'interchange_random_forest' in train_source
    assert 'ModelManager' in check_source
    assert 'FIXED_WINDOW_SEC' not in check_source or 'traffic_features' in check_source


def test_windows_client_icons_are_frozen_resources():
    gui = (ROOT / 'client' / 'client_gui.py').read_text(encoding='utf-8')
    win_spec = (ROOT / 'installer' / 'windows' / 'client' / 'InterchangeClient.spec').read_text(encoding='utf-8')
    mac_spec = (ROOT / 'installer' / 'macos' / 'client' / 'InterchangeClient.spec').read_text(encoding='utf-8')
    build = (ROOT / 'installer' / 'windows' / 'client' / 'build_client_installer.bat').read_text(encoding='utf-8')

    for filename in ('file.png', 'folder.png', 'send_white.png'):
        path = ROOT / 'client' / 'icons' / filename
        assert path.is_file() and path.stat().st_size > 0
        assert filename in gui

    assert '(str(client / "icons"), "icons")' in win_spec
    assert '(str(client / "icons"), "icons")' in mac_spec
    assert 'def resource_path(*parts):' in gui
    assert 'required_ui_resources()' in gui
    assert 'dist\\Interchange\\Interchange.exe" --self-test' in build
    assert '%LOCALAPPDATA%\\Programs\\Inno Setup 6\\ISCC.exe' in build




def test_client_gui_stays_quiet_during_synthetic_traffic():
    gui = (ROOT / 'client' / 'client_gui.py').read_text(encoding='utf-8')
    net = (ROOT / 'client' / 'client_network.py').read_text(encoding='utf-8')
    core = (ROOT / 'server' / 'server_core.py').read_text(encoding='utf-8')
    http = (ROOT / 'server' / 'server.py').read_text(encoding='utf-8')

    # Synthetic baseline traffic keeps the network characteristics but no
    # longer becomes normal chat/file-history UI traffic.
    assert 'def send_experiment_message(' in net
    assert 'self.send_experiment_message(run_id, "server", text)' in net
    assert 'quiet=True, experiment_run_id=run_id' in net
    assert 'if not msg.get("experiment"):' in net
    assert 'if is_experiment:' in core
    assert 'X-Experiment-Run-ID' in http
    assert '"status": "experiment_received"' in http

    # Reconnect experiments must honor 0.1 s and must not inherit the normal
    # two-second reconnect backoff.
    assert 'EXPERIMENT_RECONNECT_DELAY = 0.05' in net
    assert 'params, "interval_sec", 1.0, 0.1, 10.0' in net

    # Expensive QWidget rebuilds are debounced and duplicate history renders
    # have been removed.
    assert 'self._contacts_timer.setInterval(120)' in gui
    assert 'self._chat_timer.setInterval(60)' in gui
    assert 'def schedule_contacts_rebuild(self):' in gui
    assert 'def schedule_chat_render(self):' in gui
    assert 'QTimer.singleShot(0, self.render_cached_chat)' not in gui
    assert 'self.net.experiment_changed.connect(self.on_experiment_changed)' in gui


def test_client_cache_batch_history_merge():
    mod = load('client_cache_batch_test', ROOT / 'client' / 'client_cache.py')
    with tempfile.TemporaryDirectory() as td:
        cache = mod.ClientCache(pathlib.Path(td) / 'cache.sqlite3')
        cache.upsert_contact('peer', 'Peer', 'client')
        cache.add_messages_batch([
            {
                'server_message_id': 1,
                'peer_id': 'peer',
                'sender_id': 'me',
                'recipient_id': 'peer',
                'message_type': 'text',
                'text': 'one',
                'created_at': '2026-01-01 00:00:01',
            },
            {
                'server_message_id': 2,
                'peer_id': 'peer',
                'sender_id': 'peer',
                'recipient_id': 'me',
                'message_type': 'text',
                'text': 'two',
                'created_at': '2026-01-01 00:00:02',
            },
        ])
        # Re-merging the same history updates instead of duplicating rows.
        cache.add_messages_batch([
            {
                'server_message_id': 2,
                'peer_id': 'peer',
                'sender_id': 'peer',
                'recipient_id': 'me',
                'message_type': 'text',
                'text': 'two-updated',
                'created_at': '2026-01-01 00:00:02',
            },
        ])
        rows = cache.get_messages('peer')
        assert len(rows) == 2
        assert rows[-1]['text'] == 'two-updated'




def test_dataset_v1_scenario_defaults_are_frozen():
    admin = (ROOT / 'server' / 'admin_panel.py').read_text(encoding='utf-8')
    server = (ROOT / 'server' / 'server.py').read_text(encoding='utf-8')
    client = (ROOT / 'client' / 'client_network.py').read_text(encoding='utf-8')

    assert '"requests_per_sec": 30' in admin
    assert '"interval_sec": 0.1' in admin
    assert '"transfers_per_sec": 15' in admin
    assert '"payload_bytes": 32' in admin
    assert 'payload_size = max(16, min(65536, payload_size))' in server
    assert 'params, "interval_sec", 1.0, 0.1, 10.0' in client
    assert '"HIGH_FREQUENCY_SMALL_TRANSFERS",\n            {"transfers_per_sec": 15, "payload_bytes": 32}' in admin


def test_python37_syntax():
    import sys
    for path in ROOT.rglob('*.py'):
        source = path.read_text(encoding='utf-8')
        if sys.version_info[:2] == (3, 7):
            compile(source, str(path), 'exec')
            continue
        try:
            ast.parse(source, filename=str(path), feature_version=(3, 7))
        except TypeError:
            ast.parse(source, filename=str(path), feature_version=7)


def test_client_account_switch_no_is_side_effect_free_by_construction():
    source = (ROOT / 'client' / 'client_gui.py').read_text(encoding='utf-8')
    assert 'Connection settings...' not in source

    start = source.index('    def switch_account(self):')
    end = source.index('    def contact_name(self, user_id):', start)
    block = source[start:end]

    confirm_pos = block.index('QMessageBox.question')
    no_guard_pos = block.index('if answer != QMessageBox.Yes:')
    stop_pos = block.index('self.net.stop()')
    dialog_pos = block.index('ClientSetupDialog(')
    reset_pos = block.index('dialog.prepare_new_account()')

    assert confirm_pos < no_guard_pos < stop_pos
    assert no_guard_pos < dialog_pos
    assert no_guard_pos < reset_pos
    assert 'dialog.use_another_account()' not in block


def test_setup_switch_confirmation_guards_destructive_reset():
    source = (ROOT / 'client' / 'client_setup.py').read_text(encoding='utf-8')
    start = source.index('    def use_another_account(self):')
    end = source.index('    def values(self):', start)
    block = source[start:end]
    assert block.index('if answer != QMessageBox.Yes:') < block.index('return self.prepare_new_account()')

    prep_start = source.index('    def prepare_new_account(self):')
    prep_end = source.index('    def use_another_account(self):', prep_start)
    prep = source[prep_start:prep_end]
    assert 'self._delete_old_cache()' in prep
    assert 'self._reset_for_new_account()' in prep


if __name__ == '__main__':
    test_pcap_dumpcap_interface_parsing()
    test_one_second_metric_math()
    test_one_second_window_policy()
    test_cross_window_interarrival_and_syn_deduplication()
    test_server_fixed_window_duration_and_timeline()
    test_utf8_metadata_write()
    test_linux_deb_upgrade_policy()
    test_shared_live_feature_schema()
    test_model_runtime_multiclass_result()
    test_experiment_force_delete_wiring()
    test_model_monitor_wiring()
    test_training_pcap_progress_wiring()
    test_model_test_manager_scores_live_windows_without_pcap()
    test_model_test_http_and_ui_wiring()
    test_admin_long_pages_are_scrollable()
    test_random_forest_training_pipeline_wiring()
    test_windows_client_icons_are_frozen_resources()
    test_client_gui_stays_quiet_during_synthetic_traffic()
    test_client_cache_batch_history_merge()
    test_dataset_v1_scenario_defaults_are_frozen()
    test_client_account_switch_no_is_side_effect_free_by_construction()
    test_setup_switch_confirmation_guards_destructive_reset()
    test_python37_syntax()
    print('OK: smoke regressions passed')
