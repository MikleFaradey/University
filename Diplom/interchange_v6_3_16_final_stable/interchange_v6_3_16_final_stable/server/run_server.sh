#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ "$(id -u)" -eq 0 ]; then
    echo "ERROR: Do not run Interchange Server with sudo."
    echo "Run: ./run_server.sh"
    exit 1
fi

USER_HOME="$HOME"
USER_UID="$(id -u)"
USER_GID="$(id -g)"
PYTHON_BIN="$(command -v python3)"

if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: python3 not found"
    exit 1
fi

CONFIG_FILE="$USER_HOME/.config/interchange/server.ini"

echo "Python: $PYTHON_BIN"
echo "Home:   $USER_HOME"
echo "Config: $CONFIG_FILE"
echo "Server process: normal user"

"$PYTHON_BIN" configure_server.py --config "$CONFIG_FILE"

SYSTEM_NAME="$(uname -s 2>/dev/null || true)"

if [ "$SYSTEM_NAME" = "Linux" ]; then
    MIGRATION_MARKER="$USER_HOME/.config/interchange/.normal_user_migration_v608"

    if [ ! -e "$MIGRATION_MARKER" ]; then
        NEED_REPAIR=0

        if [ -e "$USER_HOME/.interchange" ]; then
            OWNER_UID="$(stat -c %u "$USER_HOME/.interchange" 2>/dev/null || echo "$USER_UID")"
            if [ "$OWNER_UID" != "$USER_UID" ]; then
                NEED_REPAIR=1
            fi
        fi

        if [ -e "$USER_HOME/.config/interchange" ]; then
            OWNER_UID="$(stat -c %u "$USER_HOME/.config/interchange" 2>/dev/null || echo "$USER_UID")"
            if [ "$OWNER_UID" != "$USER_UID" ]; then
                NEED_REPAIR=1
            fi
        fi

        if [ "$NEED_REPAIR" -eq 1 ]; then
            echo "Repairing ownership left by older root-server builds..."
            sudo chown -R "$USER_UID:$USER_GID" "$USER_HOME/.interchange" 2>/dev/null || true
            sudo chown -R "$USER_UID:$USER_GID" "$USER_HOME/.config/interchange" 2>/dev/null || true
        fi

        mkdir -p "$(dirname "$MIGRATION_MARKER")"
        touch "$MIGRATION_MARKER"
    fi

    TCPDUMP_BIN="$(command -v tcpdump 2>/dev/null || true)"
    if [ -z "$TCPDUMP_BIN" ] && [ -x /usr/sbin/tcpdump ]; then
        TCPDUMP_BIN="/usr/sbin/tcpdump"
    fi

    if [ -n "$TCPDUMP_BIN" ]; then
        if command -v readlink >/dev/null 2>&1; then
            REAL_TCPDUMP="$(readlink -f "$TCPDUMP_BIN" 2>/dev/null || true)"
            if [ -n "$REAL_TCPDUMP" ]; then
                TCPDUMP_BIN="$REAL_TCPDUMP"
            fi
        fi

        GETCAP_BIN="$(command -v getcap 2>/dev/null || true)"
        SETCAP_BIN="$(command -v setcap 2>/dev/null || true)"

        if [ -z "$GETCAP_BIN" ]; then
            for CANDIDATE in /sbin/getcap /usr/sbin/getcap /usr/bin/getcap /bin/getcap; do
                if [ -x "$CANDIDATE" ]; then
                    GETCAP_BIN="$CANDIDATE"
                    break
                fi
            done
        fi

        if [ -z "$SETCAP_BIN" ]; then
            for CANDIDATE in /sbin/setcap /usr/sbin/setcap /usr/bin/setcap /bin/setcap; do
                if [ -x "$CANDIDATE" ]; then
                    SETCAP_BIN="$CANDIDATE"
                    break
                fi
            done
        fi

        if [ -z "$GETCAP_BIN" ] || [ -z "$SETCAP_BIN" ]; then
            echo
            echo "ERROR: libcap tools were not found."
            echo "Expected getcap/setcap in PATH, /sbin or /usr/sbin."
            echo "Install once:"
            echo "  sudo apt install libcap2-bin"
            echo
            echo "Then run ./run_server.sh again."
            exit 1
        fi

        echo "getcap: $GETCAP_BIN"
        echo "setcap: $SETCAP_BIN"

        CAPS="$("$GETCAP_BIN" "$TCPDUMP_BIN" 2>/dev/null || true)"
        case "$CAPS" in
            *cap_net_admin*cap_net_raw*|*cap_net_raw*cap_net_admin*)
                echo "Packet capture permission: OK"
                ;;
            *)
                echo
                echo "One-time packet capture setup is required."
                echo "Only tcpdump receives capture capabilities."
                echo "server.py and Admin will NOT run as root."
                sudo "$SETCAP_BIN" cap_net_raw,cap_net_admin=eip "$TCPDUMP_BIN"

                CAPS="$("$GETCAP_BIN" "$TCPDUMP_BIN" 2>/dev/null || true)"
                case "$CAPS" in
                    *cap_net_admin*cap_net_raw*|*cap_net_raw*cap_net_admin*)
                        echo "Packet capture permission configured."
                        ;;
                    *)
                        echo "ERROR: tcpdump capabilities could not be configured."
                        echo "Current capabilities: $CAPS"
                        exit 1
                        ;;
                esac
                ;;
        esac
    fi
fi

echo "Starting Interchange Server as user $(id -un)..."

exec "$PYTHON_BIN" server.py \
    --config "$CONFIG_FILE" \
    --no-gui
