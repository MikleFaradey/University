# Interchange Client v6.3.16

Copy this folder to a client device.

## First run

```bash
chmod +x run_client.sh
./run_client.sh
```

The first-run setup window asks for Server IP, User ID, download folder, and
ports. Use `Test connection` to verify that the server accepts this User ID and
this device IP.

The client configuration is saved to:

```text
~/.config/interchange/client.ini
```

After setup, just run `./run_client.sh`.

The running client intentionally has no separate Connection settings action.
Account replacement is available from:

```text
Account -> Switch account...
```

Choosing **No** in the confirmation leaves the current connection, device
identity, configuration and local chat history untouched.


## Permanent access rejection

If the administrator disables this user, removes the user, or changes the
registered IP so the current device is no longer valid, Interchange shows one
warning dialog.

Press OK and the client closes completely. It does not keep reconnecting.

Temporary network loss still reconnects automatically.


## Controlled experiment modes

The client can receive only the built-in experiment commands from the
Interchange server. It does not execute arbitrary shell commands or Python code.

Supported modes:

- NORMAL: capture-only baseline interval;
- HIGH_REQUEST_RATE: repeated experiment requests over one persistent HTTP connection;
- FREQUENT_RECONNECT: controlled realtime socket reconnects;
- HIGH_FREQUENCY_SMALL_TRANSFERS: repeated small POST payloads to the
  dedicated experiment endpoint.

The experiment runs in a background thread and does not replace the normal
messenger functions.


## Automated baseline dataset folder

The experiment command contains a client-local baseline folder path.

The folder must exist on the client and contain at least one file or subfolder.
During the run, Interchange automatically sends randomly selected content from
that folder to the special `server` user and also sends random alphanumeric
messages.

For anomaly labels, this normal traffic continues while the anomaly overlay is
running.


## v6.0 Timeline execution

A single experiment command contains the full timeline.

The client starts its automated baseline once and keeps it running for the whole
timeline. It then executes phase overlays sequentially:

```text
NORMAL                         = baseline only
FREQUENT_RECONNECT             = baseline + reconnect overlay
HIGH_REQUEST_RATE              = baseline + request-rate overlay
HIGH_FREQUENCY_SMALL_TRANSFERS = baseline + small-transfer overlay
```

The baseline is not restarted between phases.


## Token authorization

The user enters only a display name and server connection settings. The
client generates a hidden 15-character alphanumeric token and stores it in
`client.ini`.

The server identifies the client by token, not by display name or static IP.
A changed DHCP address is accepted automatically after token verification.
