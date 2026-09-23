#!/bin/bash
set -e

USER_ID="user1"
DISPLAY_NAME="Workstation 1"
USER_IP="10.100.3.226"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

exec python3 admin.py add-user "$USER_ID" "$DISPLAY_NAME" --ip "$USER_IP"
