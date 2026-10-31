#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ROLE="${1:-}"
case "$ROLE" in
  server) APP="InterchangeServer"; LABEL="Server" ;;
  admin) APP="InterchangeAdmin"; LABEL="Admin" ;;
  *) echo "Usage: $0 server|admin"; exit 2 ;;
esac
if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERROR: A macOS .pkg must be built on macOS."
  exit 1
fi
command -v pkgbuild >/dev/null || { echo "pkgbuild is required"; exit 1; }
cd "$SCRIPT_DIR/$ROLE"
python3 -m venv .venv-build
PY=".venv-build/bin/python"
"$PY" -m pip install --upgrade pip pyinstaller PySide6
if [ "$ROLE" = server ]; then
  "$PY" -m pip install -r "$PROJECT_ROOT/server/requirements.txt"
else
  "$PY" -m pip install requests
fi
rm -rf build dist pkgroot output
"$PY" -m PyInstaller --clean --noconfirm "$APP.spec"
QT_QPA_PLATFORM=offscreen "dist/$APP.app/Contents/MacOS/$APP" --self-test
mkdir -p "pkgroot/Applications" output
cp -R "dist/$APP.app" "pkgroot/Applications/$APP.app"
pkgbuild --root pkgroot --identifier "com.interchange.$ROLE" \
  --version 6.3.16 --install-location / "output/${APP}.pkg"
echo "READY: $SCRIPT_DIR/$ROLE/output/${APP}.pkg"
