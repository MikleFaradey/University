#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CLIENT_DIR="$ROOT_DIR/client"
VERSION="6.3.16"
PKGNAME="interchange-client"
ARCH="all"

cd "$SCRIPT_DIR"

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "ERROR: dpkg-deb not found"
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found"
    exit 1
fi

python3 - <<'PY'
import pathlib
import sys

if sys.version_info < (3, 7):
    raise SystemExit('ERROR: Python 3.7 or newer is required')
root = pathlib.Path('../../../client').resolve()
for path in root.glob('*.py'):
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
print('Python runtime syntax check: OK (%s)' % sys.version.split()[0])
PY

rm -rf pkgroot output
mkdir -p output

PKG="$SCRIPT_DIR/pkgroot"
mkdir -p "$PKG/DEBIAN"
mkdir -p "$PKG/usr/lib/interchange-client"
mkdir -p "$PKG/usr/bin"
mkdir -p "$PKG/usr/share/applications"
mkdir -p "$PKG/usr/share/icons/hicolor/256x256/apps"
chmod 755 "$PKG" "$PKG/DEBIAN" "$PKG/usr/lib" "$PKG/usr/lib/interchange-client" "$PKG/usr" "$PKG/usr/bin" "$PKG/usr/share" "$PKG/usr/share/applications" "$PKG/usr/share/icons" "$PKG/usr/share/icons/hicolor" "$PKG/usr/share/icons/hicolor/256x256" "$PKG/usr/share/icons/hicolor/256x256/apps"
chmod g-s "$PKG" "$PKG/DEBIAN" "$PKG/usr/lib" "$PKG/usr/lib/interchange-client" "$PKG/usr" "$PKG/usr/bin" "$PKG/usr/share" "$PKG/usr/share/applications" "$PKG/usr/share/icons" "$PKG/usr/share/icons/hicolor" "$PKG/usr/share/icons/hicolor/256x256" "$PKG/usr/share/icons/hicolor/256x256/apps"

cp "$CLIENT_DIR"/*.py "$PKG/usr/lib/interchange-client/"
cp -a "$CLIENT_DIR/assets" "$PKG/usr/lib/interchange-client/"
cp -a "$CLIENT_DIR/icons" "$PKG/usr/lib/interchange-client/"

cp "$SCRIPT_DIR/interchange-client" "$PKG/usr/bin/interchange-client"
cp "$SCRIPT_DIR/interchange.desktop" "$PKG/usr/share/applications/interchange.desktop"
cp "$SCRIPT_DIR/interchange.png" "$PKG/usr/share/icons/hicolor/256x256/apps/interchange.png"
cp "$SCRIPT_DIR/preinst" "$PKG/DEBIAN/preinst"
cp "$SCRIPT_DIR/postinst" "$PKG/DEBIAN/postinst"
cp "$SCRIPT_DIR/postrm" "$PKG/DEBIAN/postrm"

cat > "$PKG/DEBIAN/control" <<EOF
Package: $PKGNAME
Version: $VERSION
Section: net
Priority: optional
Architecture: $ARCH
Maintainer: Interchange
Depends: python3 (>= 3.7), python3-requests, python3-pyqt5
Description: Interchange LAN client
 Native Debian/Astra package using the distribution Python and Qt runtime.
 This avoids frozen Qt/glibc portability problems between Linux releases.
EOF

chmod 755 "$PKG/DEBIAN/preinst" "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"
chmod 755 "$PKG/usr/bin/interchange-client"
find "$PKG/usr/lib/interchange-client" -type d -exec chmod 755 {} +
find "$PKG/usr/lib/interchange-client" -type d -exec chmod g-s {} +
find "$PKG/usr/lib/interchange-client" -type f -exec chmod 644 {} +

OUT="$SCRIPT_DIR/output/${PKGNAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$PKG" "$OUT"
dpkg-deb --info "$OUT" >/dev/null
dpkg-deb --contents "$OUT" >/dev/null

rm -rf "$PKG"

echo
echo "READY:"
echo "$OUT"
echo
echo "Install/upgrade:"
echo "  sudo apt install ./$(basename "$OUT")"
echo
echo "Diagnostics after install:"
echo "  interchange-client --diagnose"
