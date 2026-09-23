#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VERSION="6.3.16"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "ERROR: Build this installer on macOS"
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found"
    exit 1
fi

if ! command -v pkgbuild >/dev/null 2>&1; then
    echo "ERROR: pkgbuild not found"
    exit 1
fi

python3 -c "import requests" >/dev/null 2>&1 || {
    echo "ERROR: Python requests is not installed"
    exit 1
}

python3 -c "import PySide6" >/dev/null 2>&1 || \
python3 -c "import PySide2" >/dev/null 2>&1 || {
    echo "ERROR: PySide6 or PySide2 is required on the build Mac"
    exit 1
}

python3 -c "import PyInstaller" >/dev/null 2>&1 || {
    echo "ERROR: PyInstaller is required on the build Mac"
    echo "Install it with: python3 -m pip install pyinstaller"
    exit 1
}

rm -rf build dist pkgroot pkg_scripts output
mkdir -p output
mkdir -p pkgroot/Applications
mkdir -p pkg_scripts

python3 -m PyInstaller --clean --noconfirm InterchangeClient.spec

cp -R "dist/Interchange.app" "pkgroot/Applications/Interchange.app"
cp preinstall pkg_scripts/preinstall
cp postinstall pkg_scripts/postinstall
chmod 755 pkg_scripts/preinstall
chmod 755 pkg_scripts/postinstall

pkgbuild \
    --root pkgroot \
    --scripts pkg_scripts \
    --identifier com.interchange.client \
    --version "$VERSION" \
    --install-location / \
    "output/InterchangeClient.pkg"

echo
echo "READY:"
echo "$SCRIPT_DIR/output/InterchangeClient.pkg"
