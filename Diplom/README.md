# Interchange v6.3.16 FINAL STABLE

The project now has three independent components:

```text
interchange_v6_3_16_final_stable/
|-- client/
|-- server/
`-- parser/
```

## Experiment model

One experiment produces one continuous PCAP.

Normal traffic runs automatically for the entire experiment:

- random files/folders from the client baseline folder are sent to `server`;
- random alphanumeric text messages are sent to `server`;
- normal heartbeat and Interchange traffic continue.

The Admin Panel contains an `Experiment timeline` editor.

Example:

```text
0   - 30   NORMAL
30  - 50   FREQUENT_RECONNECT
50  - 80   NORMAL
80  - 110  HIGH_REQUEST_RATE
110 - 140  NORMAL
140 - 170  HIGH_FREQUENCY_SMALL_TRANSFERS
```

Intervals use `[start, end)` semantics. Timeline boundaries must be whole
seconds and phases must be continuous.

For anomaly phases, the normal baseline DOES NOT stop. The selected anomaly is
added on top of the same baseline.

## Result of one run

The server creates:

```text
run_000001_user1_TIMELINE_YYYYMMDD_HHMMSS.pcap
run_000001_user1_TIMELINE_YYYYMMDD_HHMMSS.json
```

The JSON contains:

- experiment ID;
- precise server-owned experiment start epoch;
- target client IP;
- complete timeline;
- baseline parameters;
- capture interface/backend;
- Interchange HTTP/socket ports;
- planned duration, dataset duration (complete 1-second windows) and final status;
- fixed dataset window (`window_sec: 1`).

## Parser

The `parser/` folder is completely independent.

It converts one or many PCAP + JSON pairs to a CSV dataset using a project-fixed
1-second window. Labels come directly from the timeline metadata.

Example:

```bash
cd parser
python3 -m pip install -r requirements.txt

./run_parser.sh \
  --input-dir /path/to/server_pcap_folder \
  --output dataset.csv
```

Each CSV row is exactly one 1-second sample and includes `experiment_id`,
`window_duration_sec`, traffic features, and `label`.

Keeping `experiment_id` is important: later train/test splits should be made by
whole experiments instead of randomly mixing neighboring windows.

See `DATASET_POLICY.md` for the fixed-window metric contract.


## v6.3.7 - fixed one-second dataset contract

The dataset window is now a project invariant: **exactly 1 second**. The parser
rejects non-1-second overrides and validates whole-second timeline boundaries.

Metric behavior was adapted for this resolution:

- every count field is the count for one exact second and therefore also an
  event-per-second value;
- `packets_per_sec` and `bytes_per_sec` are retained as exact aliases for
  compatibility;
- inter-arrival timing follows the continuous packet stream across neighboring
  seconds, avoiding artificial zero timing for sparse one-packet windows;
- `new_tcp_connections` deduplicates SYN retransmissions by flow tuple;
- stopped/error/timeout captures expose only complete seconds to the dataset,
  while planned duration remains available separately;
- CSV rows explicitly include `window_duration_sec = 1.0`;
- parser CSV and metadata JSON use UTF-8.

Metadata schema version is 4.


## v6.0.1 hotfix

Fixed Admin Panel startup after the v6.0 Experiment Timeline migration.

The old `refresh_scenarios()` startup call was left behind even though the old
scenario editor had been removed. The Admin Panel now starts directly with the
timeline editor and recent experiment runs.


## v6.0.2 hotfix - tcpdump Permission denied

On Debian/Astra, tcpdump may drop privileges to the dedicated `tcpdump` user
before opening the output PCAP file. If the server is started with sudo while
HOME is preserved as the normal user's home directory, that account may not be
allowed to write inside `~/.interchange/pcap`.

When Interchange server is running as root, v6.0.2 starts tcpdump with
`-Z root`, so the PCAP file can be created in the configured user PCAP folder.


## v6.0.3 - server launcher restored

The v6.0.2 PCAP hotfix accidentally kept the older `run_server.sh`.
v6.0.3 restores the intended deployment model without removing any v6 timeline,
PCAP, Admin Panel, or parser features.

Standard server start is now:

```bash
cd server
./run_server.sh
```

The launcher:

1. uses the normal desktop user's Python and HOME;
2. opens first-run Server Setup as the normal user if needed;
3. starts `server.py` with sudo;
4. preserves the same HOME/config/database;
5. adds `/usr/sbin` to PATH for tcpdump;
6. forces the root server to run headless, avoiding Qt/X11/Wayland errors.

To edit server settings later:

```bash
./run_server_settings.sh
```

The Admin Panel is still started normally, without sudo:

```bash
./run_admin.sh
```


## v6.0.4 - Astra tcpdump savefile fix

On some hardened Astra/Debian installations, tcpdump can capture packets as
root but still receives `Permission denied` when it opens a PCAP file under the
desktop user's HOME.

v6.0.4 no longer asks tcpdump to open the destination path.

For the tcpdump backend:

1. the sudo/root Python server opens the configured PCAP file;
2. tcpdump writes binary PCAP to stdout with `-w -`;
3. Python redirects that stream into the already-open file.

This avoids tcpdump savefile path permission/privilege-drop behavior while
keeping the configured PCAP folder unchanged.


## v6.0.5 - server-authoritative experiment time

Experiment wall-clock timestamps are now produced only by the server.

Why:
PCAP packet timestamps are generated on the server machine. Older builds used
`time.time()` from the client as `experiment_start_epoch`. If the two machines
had different clocks, the parser could place every packet outside the planned
timeline and produce CSV windows containing only zeros.

New timing model:

1. Server starts PCAP capture.
2. Server records `experiment_start_epoch` using its own `time.time()`.
3. Server sends the experiment start command to the client.
4. Client starts its local work and uses only `time.monotonic()` for elapsed
   phase scheduling.
5. Client reports states (`running`, `phase`, `completed`) without wall-clock
   timestamps.
6. Server records the experiment finish time using its own clock.
7. Parser aligns PCAP packets to the server-owned `experiment_start_epoch`.

Metadata schema version is now 3 and includes:

- `clock_source`: `server`
- `timing_model`: `server_epoch_client_monotonic`

The small LAN command-delivery delay should be considered relative to the 1-second ML
window size and does not depend on clock synchronization between machines.


## v6.0.6 - server/admin permission architecture fix

The whole server is no longer started with sudo.

Correct Linux/Astra runtime model:

- `server.py`: normal desktop user
- `admin_panel.py`: normal desktop user
- SQLite database: normal desktop user
- PCAP files and capture logs: normal desktop user
- `tcpdump` only: elevated through `sudo -n`

`run_server.sh` asks for sudo authorization once at server startup and keeps
that authorization alive while the server is running. This lets Admin start
experiments later without a password dialog while preventing root ownership of
the database, WAL/SHM files, PCAP files, config, spool and received files.

The first v6.0.6 launch also repairs ownership left by v6.0.3-v6.0.5 in
Interchange paths inside the user's HOME. Permission bits are not changed.

Start:

```bash
cd server
./run_server.sh
```

Do NOT use:

```bash
sudo ./run_server.sh
```

Admin remains:

```bash
./run_admin.sh
```

Both can run at the same time and share the SQLite WAL database.


## v6.0.7 - false Server Offline status fix

The client previously allowed a presence snapshot to overwrite the state of the
built-in `server` contact. This could show `Server - Offline` even while the
client had already completed `hello_ok` and was actively connected.

The `server` contact is now derived directly from the confirmed realtime
connection state:

- connected -> Server is Online
- disconnected -> Server status is Unknown

Ordinary client contacts still use the server presence map.


## v6.0.8 - packet capture without runtime sudo

v6.0.6/v6.0.7 still invoked tcpdump through `sudo -n` when Admin started an
experiment. On systems where sudo credentials are tied to a terminal/TTY, the
capture could fail with:

```text
sudo: a password is required
```

v6.0.8 removes runtime sudo completely.

Linux/Astra model:

- `server.py`: normal user
- `admin_panel.py`: normal user
- SQLite and PCAP files: normal user
- `tcpdump`: normal process with Linux capture capabilities

On the first server start, `run_server.sh` checks tcpdump. If required, it asks
for sudo once and executes:

```bash
setcap cap_net_raw,cap_net_admin=eip /path/to/tcpdump
```

After that, pressing `Run experiment + PCAP` never calls sudo and never asks
for a password.

If `getcap`/`setcap` are missing, install once:

```bash
sudo apt install libcap2-bin
```

Then start normally:

```bash
./run_server.sh
```

Never use `sudo ./run_server.sh`.


## v6.0.9 - Debian/Astra libcap path fix

Some Debian/Astra installations place `getcap` and `setcap` in `/sbin` or
`/usr/sbin`, while the normal desktop user's PATH does not include those
directories. v6.0.8 therefore incorrectly reported that libcap tools were
missing even when `libcap2-bin` was installed.

v6.0.9 explicitly searches:

- PATH
- `/sbin`
- `/usr/sbin`
- `/usr/bin`
- `/bin`

and invokes the discovered absolute paths.


## v6.0.10 - anomaly content refinement only

This build intentionally does not change the working server/Admin/PCAP/timing
architecture from v6.0.9.

Only two anomaly generators were refined:

### HIGH_REQUEST_RATE

The client still generates the configured number of requests per second, but
the requests now use one persistent HTTP/TCP connection.

Expected behavior:

- high application request rate;
- approximately one TCP connection for the anomaly overlay;
- no artificial "one request = one new TCP connection" effect.

### HIGH_FREQUENCY_SMALL_TRANSFERS

The direction is now intentionally:

```text
SERVER -> CLIENT
```

The client opens one experiment stream. The server sends small payload bursts
at `transfers_per_sec`, each with `payload_bytes` bytes, until the phase ends.

The payload is discarded by the client and does not create files, transfers,
chat messages, or database history rows.

Unchanged:

- NORMAL baseline;
- FREQUENT_RECONNECT;
- timeline scheduling with whole-second boundaries;
- server-authoritative experiment time;
- PCAP capture and permissions;
- Admin Panel;
- database;
- parser and feature extraction;
- client/server connection logic.


## v6.1.0 - cross-platform launch and Windows capture

The application source remains shared across operating systems.

Launchers:

- Linux/Astra/macOS: `.sh`
- Windows: `.bat`

Windows launchers were added for client, server, Admin Panel, server settings,
capture diagnostics and parser.

Windows PCAP capture uses `dumpcap.exe` from Wireshark with Npcap. The capture
manager searches common Wireshark locations even when dumpcap is not in PATH
and can auto-select the adapter used to reach the experiment client.

See `WINDOWS_SETUP.txt`.

The tested experiment/anomaly behavior from v6.0.10 was intentionally left
unchanged.


## v6.1.1 - Windows setup text color fix

Windows can supply a dark system text palette even when the Interchange setup
dialog uses a custom light background. In v6.1.0 this could make form labels,
button text and checkbox text appear white on the light setup window.

v6.1.1 explicitly sets dark text colors for:

- labels;
- checkboxes;
- line edits;
- spin boxes;
- buttons.

Only the client/server setup-dialog styles were changed. Networking, Admin,
database, PCAP capture, experiment generation, timing and parser logic are
unchanged from v6.1.0.


## v6.1.2 - client authorization recovery

Client access rejections no longer terminate the application.

For fatal authorization errors such as:

- disabled user;
- unknown User ID;
- registered IP mismatch;

the chat window is hidden and the client immediately returns to the
authorization dialog.

The dialog keeps the current server/download settings available for editing
and highlights the User ID field. `Save and reconnect` performs a real
hello/authentication check before the dialog can close. Invalid replacement
credentials therefore remain in the authorization window instead of causing
a repeated chat-close loop.

Pressing Cancel exits the client.

No server, Admin, PCAP, timeline, anomaly, database or parser behavior was
changed.


## v6.1.3 - presentation-clean source

All ordinary source-code comments were removed from Python and shell launcher
files. Interpreter shebang lines were retained because they are executable
directives, not explanatory source comments.

Runtime behavior is unchanged from v6.1.2.


## v6.1.4 - Windows client installer

A Windows installer build project is included under:

`installer/windows/client`

Run `build_client_installer.bat` on Windows to create
`output/InterchangeClientSetup.exe`.

Every installation is intentionally a clean installation. Existing local
Interchange configuration, caches, database files, PCAP files, logs, spool
data and default Interchange receive folders are removed before the new
application is copied.

Arbitrary custom directories outside Interchange-owned/default locations are
not recursively deleted.


## v6.1.5 - client installers for all platforms

Installer build projects are now included for:

- Windows: `installer/windows/client`
- Linux/Astra/Debian: `installer/linux/client`
- macOS: `installer/macos/client`

Each platform performs a clean Interchange reset before installation.

The Linux DEB must be built on the target Linux distribution/architecture.
The macOS PKG must be built on macOS. This is required because PyInstaller
packages native Python/Qt binaries for the build operating system.

Application runtime behavior is unchanged from v6.1.4.


## v6.2.0 - token authorization

Client authorization no longer depends on a static client IP address.

First connection:

1. The client enters a display name and the fixed server address.
2. The client generates a private 15-character alphanumeric token.
3. The client sends an authorization request.
4. Admin sees the new client as `PENDING`.
5. Admin selects `Approve`.
6. The waiting client detects approval automatically and opens the chat.

Later connections use the same hidden token. The current client IP is stored
only as `Last IP` and is updated when the client connects. A DHCP address
change does not require a new authorization request.

The display name is not an authentication key and duplicate names are allowed.

In v6.2.0 the raw token was stored only in the client configuration and the
server stored a SHA-256 token hash. v6.3.0 replaces this with public
challenge-response verifiers and password authentication.

Admin access states:

- PENDING
- APPROVED
- REJECTED
- BLOCKED

Only APPROVED clients can open the realtime chat or use authenticated HTTP
operations such as history, file transfer and experiment traffic.

PCAP capture still uses the current client IP for the capture filter. Because
the server updates `Last IP` on successful token authentication, experiments
continue to work with DHCP clients.

All installer clean-reset behavior remains active. Reinstalling the client
deletes the old local token, so a clean installation creates a new identity
and requires approval again.


## v6.3.0 - password + hidden-token challenge authentication

The client now uses two user-side secrets: a hidden 15-character device token
and a password chosen by the user. The token is stored in client.ini. The raw
password is never stored. On every new application launch the user enters the
password again. During the running process only derived authentication material
is kept in memory so network reconnects do not require another prompt.

The raw password and raw device token are never transmitted to the server.
Registration sends public cryptographic verifiers. Authentication uses fresh
challenge-response proofs, an ephemeral Diffie-Hellman exchange, mutual session
proofs and a derived per-login session key. The password proof secret is derived
from both the password and the hidden token, so a server database alone does not
contain enough material to test password guesses without also obtaining the
client token. A separate token proof is required as well.

Authenticated HTTP operations are protected with HMAC-SHA256 over the request
method, path, user identity, one-time nonce and operation-specific parameters.
The server rejects reused nonces.

The display name and client IP are not authentication credentials. The IP is
kept only as Last IP for presence and PCAP capture targeting.

This protocol protects authentication credentials and request authenticity. It
does not claim payload confidentiality for the existing realtime chat channel;
TLS can be added later if full traffic confidentiality is required.


## v6.3.1 - Admin server visibility fix

The Admin Panel is installed with the server and its local `/users` status
request is now treated as a local administrative request.

The v6.3.0 secure-auth change had accidentally required a client HTTP session
for this Admin status request. As a result, Admin received HTTP 403 and showed
`Server unavailable` even while the server was running.

Local loopback requests to `/users` are now allowed without a client session.
Remote `/users` requests still require the normal authenticated client session.

No PCAP, experiment, anomaly, parser or client authentication behavior was
changed.


## v6.3.2 - contact name display fix

The generated internal client ID is no longer displayed in gray next to the
contact display name in the chat/contact list.

The internal ID is still used by the application for routing, cache keys,
authorization and server-side identity. Only its visual label was removed.

No authentication, networking, PCAP, experiment, anomaly or parser behavior
was changed.


## v6.3.3 - switch account

The sign-in window now includes `Use another account`.

When selected:

- the current account local chat cache is deleted;
- SQLite WAL and SHM cache files are deleted as well;
- the old local user ID is removed from client settings;
- a new private 15-character device token is generated;
- the display name is cleared;
- the dialog returns to new-account registration mode;
- the new name and password create a new `PENDING` authorization request;
- Admin approval is required again.

Server address, download directory and port settings are retained for
convenience.

The old server-side account record and its server history are not deleted.
The client no longer possesses its old local identity after switching.

The same account-switch flow is also available from the Settings menu while
the client application is open.


## v6.3.4 - blocked account recovery without restart

A blocked account could previously leave the primary authorization button
disabled after selecting `Use another account`. Restarting the application
created a fresh dialog and accidentally cleared that stale UI state.

The account-switch path now performs a complete transient authorization reset:

- authorization polling is stopped;
- the poll busy flag is cleared;
- pending-request state is cleared;
- stale authentication results are cleared;
- the previous blocked/reauthorization dialog state is cleared;
- the old local chat cache is deleted;
- the old local user ID is removed;
- a fresh 15-character device token is generated;
- name and password fields are cleared;
- editable connection fields are re-enabled;
- `Request access` is explicitly enabled and becomes the default action;
- registration mode is restored immediately.

Registration mode itself also explicitly enables `Request access`, providing
an additional guard against stale button state.

No application restart is required after blocking a user and switching to a
new account.

Server authorization, challenge-response cryptography, PCAP capture,
experiments, anomalies and parser behavior were not changed.

## v6.3.5 - stability and cross-platform PCAP fix

- Fixed Windows `dumpcap -D` interface discovery: `pcap_manager.py` used
  `re.match()` without importing `re`, which could break automatic capture
  interface selection on Windows.
- Historical behavior: the parser preserved a final partial custom window.
  This was superseded by v6.3.7, where the project window is fixed at exactly
  1 second and trailing partial seconds are intentionally excluded.
- Python source compatibility target is explicitly Python 3.7+.
- Added dependency-free regression smoke tests under `tests/`.


## v6.3.8 - Linux/Astra DEB reliability fix

The Linux client DEB was redesigned after the packaged client could install
successfully but fail to run or disappear during an upgrade.

Key fixes:

- package version is now `6.3.8` instead of the stale hard-coded `6.3.0`;
- the Linux DEB no longer freezes Qt/Python with PyInstaller; it installs the
  client source under `/usr/lib/interchange-client` and uses the distribution
  `python3`, `python3-requests` and `python3-pyqt5` packages;
- this lets apt resolve the matching Qt/XCB/glibc dependencies for the actual
  Debian/Astra release;
- the application payload moved away from `/opt/interchange/client`, because
  the legacy package `postrm` could delete that path during the first upgrade;
- the new `preinst` temporarily moves existing Interchange state out of the
  legacy cleanup paths while upgrading from versions older than 6.3.8, and
  `postinst` restores it afterwards;
- the new `postrm` never recursively deletes the application during upgrades;
- `interchange-client --diagnose` checks Python, Requests, PyQt5 and performs
  a headless Qt/application self-test;
- graphical startup failures are logged to
  `~/.local/state/interchange/launcher.log`.

Build the package with:

```bash
cd installer/linux/client
./build_client_deb.sh
```

Install or upgrade with:

```bash
sudo apt install ./output/interchange-client_6.3.8_all.deb
```

The one-second dataset policy introduced in v6.3.7 is unchanged.


## v6.3.9 - live model monitor and multiclass anomaly display

The Admin Panel now contains a third tab, `Model & traffic`. It is a real live
inference path rather than a CSV viewer.

- choose a trusted `.joblib`, `.pkl` or `.pickle` model through the system file
  dialog;
- load or unload the model without restarting the server;
- every online client with a known IP is monitored independently;
- tcpdump/dumpcap packets are streamed into RAM and aggregated into the fixed
  1-second project window;
- `parser/pcap_to_csv.py` and live inference use the same
  `server/traffic_features.py` implementation;
- the model receives the one-second feature vector directly, without creating
  or rereading a CSV file;
- the live table shows connection state, NORMAL/ANOMALY, the exact predicted
  class/anomaly type, confidence, latest completed window, packets/s and
  bytes/s;
- double-clicking a client shows every class probability, the full latest
  feature vector and up to 60 seconds of recent prediction history;
- the event log records model load/unload, anomaly-type transitions and recovery
  to NORMAL;
- the first partial second after a capture start/restart is discarded, so the
  model receives only complete 1-second windows;
- automatic client blocking is intentionally disabled. This release is
  observation-only.

The runtime accepts a normal sklearn estimator when its schema matches the 28
canonical traffic features. It also accepts a 29-feature model that includes
`window_duration_sec`, and an Interchange joblib package containing `model`,
`feature_names` and optional `class_names` metadata. See
`server/MODEL_MONITOR.md`.

Server ML dependencies are listed in `server/requirements.txt`. Python 3.7 is
kept on `scikit-learn==1.0.2`; newer Python versions may use newer compatible
scikit-learn releases.

Security note: joblib/pickle files can execute Python code while loading. Only
trusted local model files should be loaded. The model-management HTTP endpoints
are restricted to the local Admin process.


## v6.3.10 - force stop/delete and brand refresh

This release closes the failure mode where an experiment could stay in
`stopping` indefinitely if the client worker was stuck in network/file I/O.

- `Stop selected run` is server-authoritative: the server sends a cooperative
  stop to the client, then immediately stops the PCAP capture, cancels the
  watchdog, records the run as `stopped`, and frees the active-run slot.
- `Force stop & delete` is available for any selected run, including
  `starting`, `running`, and `stopping` runs. For an active run it sends a
  force-reset command to the client, kills local capture, cancels the watchdog,
  deletes the DB row, and removes the partial `.pcap`, `.json`, and
  `.capture.log` artifacts.
- Client experiment workers now own a dedicated stop event. A detached stuck
  worker cannot observe the stop event of a later run, so starting a new test
  after force deletion is safe.
- Baseline file uploads used by experiments are cancellation-aware and have a
  bounded experiment-mode read timeout.
- The application logo and installer icons were replaced with a simpler
  two-way transfer mark and cleaner Interchange wordmark.
- Windows and macOS installer version metadata is now kept in sync with the
  release version.

The fixed one-second dataset/model window and live multiclass model monitor are
unchanged.


## v6.3.11 - account switch safety and client menu cleanup

- Removed `Connection settings...` from the running client UI. Connection
  parameters continue to be handled by the first-run/sign-in flow.
- `Switch account...` now asks for confirmation before stopping the network or
  constructing the account-reset dialog. Choosing **No** is a strict no-op:
  current connection, identity, config and local chat cache remain untouched.
- The destructive reset helper is called only after an explicit **Yes**.


## v6.3.12 - PCAP progress and scenario model validation

Training experiments now expose PCAP preparation progress directly in the
Admin timeline tab. The percentage is based on the planned timeline and the
actual experiment clock. While the capture is still open the progress is capped
at 99%; 100% is shown only after the server has closed/finalized the PCAP. The
progress panel also shows elapsed/remaining time and the current scenario phase.

`Model & traffic` now contains a second workspace, `Model test`. It uses the
same timeline concept as the training window: choose a client, baseline folder,
phase durations, traffic/anomaly type and parameters, then run the scenario.
No training PCAP and no CSV dataset file are created. The existing live packet
stream is aggregated by `traffic_features.py` into the fixed one-second vector
and passed straight to the loaded model.

Every complete one-second window is compared with the class expected from the
scenario phase. The UI shows current progress, current phase, expected class,
predicted class, confidence, per-second match/mismatch rows, overall accuracy,
average confidence and per-class correct/total counts. A one-second window that
crosses a phase boundary is excluded from accuracy scoring because it contains
traffic from two expected classes. Model-test state/results are memory-only.

Training experiments and model tests use the same client scenario slot. A model
test cannot start while that client has an active training capture, and a
training capture cannot start while that client has an active model test.


## v6.3.13 - Scrollable admin interface

Long admin views no longer require a tall desktop. The Experiment timeline page
uses a scroll area, and the Model test page has its own scroll area so scenario
configuration, progress and per-second results remain reachable on small or
high-DPI displays. The Admin window minimum size is now 760x500.


## Random Forest training

The release includes a complete grouped multiclass training pipeline under
`server/ml/`. It consumes the CSV produced by the project parser and preserves
the fixed 1-second / 28-feature contract used by live inference.

```bash
python3 -m pip install -r server/requirements.txt
python3 server/ml/train_random_forest.py \
  --dataset ./dataset \
  --output ./models/interchange_rf_v1.joblib
python3 server/ml/check_model.py ./models/interchange_rf_v1.joblib
```

The trainer splits by whole experiment/PCAP groups and writes the model plus
metrics JSON, confusion matrix and feature-importance reports. See
`server/ml/README.md` for details.


## v6.3.14 - Random Forest training pipeline

- Added production Random Forest training and model validation utilities.
- Training validates the exact one-second window and canonical 28-feature order.
- Train/test data are separated by whole experiments/PCAPs to avoid leakage.
- The generated `.joblib` loads directly in the existing Model & traffic tab.


## v6.3.15 - Windows composer icon packaging fix

- The Windows PyInstaller bundle now includes `client/icons`.
- File, folder, and send buttons use bundled PNG runtime icons, avoiding a dependency on the Qt SVG image plugin.
- Client resources are resolved consistently from source installs, native Linux packages, and PyInstaller bundles.
- The Windows build script runs the frozen executable with `--self-test` before creating the Inno Setup installer, so a build with missing UI resources fails early.
- Inno Setup 6 discovery also checks `%LOCALAPPDATA%\Programs\Inno Setup 6` and `PATH`.


## v6.3.16 - final client stability freeze

This release freezes the current messenger/dataset architecture before the main
dataset collection run.  The fixed one-second feature schema and 28 model
features are unchanged.

- Synthetic experiment messages now use the normal socket path but are not
  written into user chat history or rendered in the messenger UI.
- Baseline experiment file uploads use the authenticated upload body path but
  are discarded after validation; they no longer create transfer/history rows
  or progress/status floods in the client UI.
- Contact-list and chat-bubble rebuilds are debounced, duplicate history
  rendering was removed, and history batches are merged in one SQLite
  transaction.
- File-transfer progress signals are rate-limited to keep the Qt event queue
  responsive during large transfers.
- Presence/history/task synchronization is suspended during synthetic tests
  and refreshed once after the test finishes.
- Server presence broadcasts are suppressed during intentional reconnect
  storms and replaced by one final authoritative snapshot.
- `FREQUENT_RECONNECT` now honors `interval_sec=0.1`; synthetic reconnects use
  a 50 ms retry delay instead of the normal two-second connection backoff.
- The client top bar shows the currently active traffic-test phase without
  adding experiment messages to chats.
- Windows bundled file/folder/send icons, safe account switching, PCAP progress,
  live multiclass model monitoring/testing, Random Forest training and the
  one-second dataset policy remain intact.

From this release onward, the project should be treated as feature-frozen for
dataset collection unless a real bug is found or the technical specification
changes.

See `DATASET_COLLECTION_CHECKLIST.md` before starting the main PCAP series.
