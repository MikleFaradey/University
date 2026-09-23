# Interchange Server v4.0

Copy this folder to the server device.

## First run

```bash
chmod +x run_server.sh
./run_server.sh
```

The first-run setup window asks for the server receive directory, database file,
relay spool directory, HTTP port, Socket port, and whether to open the server
monitor GUI.

The server configuration is saved to:

```text
~/.config/interchange/server.ini
```

When the server monitor GUI is enabled, edit settings later through:

```text
Settings -> Server settings...
```

Restart the server after changing settings.

## Admin Panel

```bash
chmod +x run_admin.sh
./run_admin.sh
```

The Admin Panel automatically uses the database file and HTTP port from
`server.ini`. No separate Admin Panel configuration is needed.


## Live user registry

The Admin Panel and the running server use the same SQLite database.

In v4.1 the server watches the user table automatically. Adding, editing,
enabling, or disabling a user in the Admin Panel takes effect without restarting
the server.


## ML experiments and PCAP

Server settings now include:

- PCAP folder
- Capture interface

`auto` is recommended on Linux. The server prefers `dumpcap`, then `tcpdump`.

The Admin Panel `Experiment timeline` tab contains:

- the fixed whole-second timeline editor;
- `Run experiment + PCAP`;
- `Stop selected run`;
- `Force stop & delete`, which also works on a stuck active run;
- a table of recent experiment runs and PCAP paths.

`Stop selected run` is server-authoritative: capture and DB state are finalized
without waiting indefinitely for a client acknowledgement. `Force stop & delete`
also sends a client-side force reset, cancels the watchdog, terminates local
packet capture and removes the selected run plus its partial capture artifacts.

The server captures only traffic for the selected client IP and the configured
Interchange HTTP/socket ports.


## Baseline path at experiment start

The Admin Panel has a `Client baseline folder` field.

The path is interpreted on the target client computer. The server does not
browse or copy this folder itself. The path is included in experiment metadata
so each PCAP run remains reproducible.


## v6.0 Experiment Timeline

The old one-label-per-run experiment model is replaced by a timeline.

Open Admin Panel -> `Experiment timeline`.

Choose:

1. target client;
2. client baseline folder path;
3. timeline phases;
4. `Run experiment + PCAP`.

Rules:

- first phase starts at 0;
- phases are continuous;
- every start/end is a whole number of seconds;
- maximum experiment duration is 3600 seconds.

The server starts one PCAP before the timeline command is sent. The client
reports the precise experiment start epoch, which is written into JSON metadata
for automatic parser alignment.


## Recommended launch model

Server:

```bash
./run_server.sh
```

Admin Panel:

```bash
./run_admin.sh
```

Server settings:

```bash
./run_server_settings.sh
```

`run_server.sh` handles sudo itself. Do not run `sudo ./run_server.sh`.

The graphical first-run/setup dialog always runs as the normal desktop user.
The actual network server then runs headless with sudo so tcpdump can capture
traffic without Qt display permission problems.


## v6.0.6 Linux/Astra startup

Run the server as the normal desktop user:

```bash
./run_server.sh
```

The launcher asks for the sudo password only to authorize future tcpdump
capture. It does not elevate server.py.

Then, in another terminal:

```bash
./run_admin.sh
```

Do not start either application with sudo.


## v6.0.8 Linux/Astra capture permissions

Start:

```bash
./run_server.sh
```

If tcpdump does not yet have capture capabilities, the launcher asks for the
sudo password once to configure the tcpdump executable. The running server is
still the normal desktop user.

Admin can then start and stop PCAP experiments without sudo:

```bash
./run_admin.sh
```


## Token authorization

New client requests appear in Admin with status `PENDING`.

Use:

- Approve
- Reject
- Block

In v6.3.0 the server stores public token and password verifiers, a password
salt and KDF parameters. It never stores the raw token or raw password. Client
IP addresses are updated as `Last IP` and are not authentication credentials.

## Random Forest training (v6.3.16)

Use `ml/train_random_forest.py` to train a multiclass model from parser CSVs.
The trainer imports the exact canonical feature order from `traffic_features.py`
and splits by complete experiment/PCAP groups. See `ml/README.md`.
