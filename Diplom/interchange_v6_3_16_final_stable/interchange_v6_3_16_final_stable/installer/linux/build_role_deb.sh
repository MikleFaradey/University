#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/../.." && pwd)"
ROLE="${1:-}"
case "$ROLE" in
  server) PACKAGE="interchange-server"; APP="InterchangeServer"; ENTRY="server.py" ;;
  admin) PACKAGE="interchange-admin"; APP="InterchangeAdmin"; ENTRY="admin_panel.py" ;;
  *) echo "Usage: $0 server|admin"; exit 2 ;;
esac
command -v dpkg-deb >/dev/null || { echo "ERROR: dpkg-deb is required"; exit 1; }
command -v python3 >/dev/null || { echo "ERROR: python3 is required"; exit 1; }
cd "$HERE/$ROLE"
python3 - "$PROJECT" <<'PY'
import pathlib
import sys
folder = pathlib.Path(sys.argv[1]) / 'server'
for source in list(folder.glob('*.py')) + list((folder / 'ml').glob('*.py')):
    compile(source.read_text(encoding='utf-8'), str(source), 'exec')
print('Server source syntax: OK')
PY
rm -rf pkgroot output
PKG="$HERE/$ROLE/pkgroot"
install -d "$PKG/DEBIAN" "$PKG/usr/lib/$PACKAGE" "$PKG/usr/bin" \
  "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/256x256/apps"
if [ "$ROLE" = server ]; then
  cp "$PROJECT/server/"*.py "$PKG/usr/lib/$PACKAGE/"
  cp -R "$PROJECT/server/ml" "$PKG/usr/lib/$PACKAGE/"
  cp -R "$PROJECT/server/assets" "$PKG/usr/lib/$PACKAGE/"
  DEPENDS="python3 (>= 3.7), python3-requests, python3-pyqt5, python3-scapy, python3-sklearn, python3-joblib, tcpdump"
else
  for file in admin_panel.py db.py server_config.py qt_compat.py; do
    cp "$PROJECT/server/$file" "$PKG/usr/lib/$PACKAGE/$file"
  done
  DEPENDS="python3 (>= 3.7), python3-requests, python3-pyqt5"
fi
cat > "$PKG/usr/bin/$PACKAGE" <<EOF
#!/bin/sh
exec /usr/bin/python3 /usr/lib/$PACKAGE/$ENTRY "\$@"
EOF
cat > "$PKG/usr/share/applications/$PACKAGE.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Interchange ${ROLE^}
Exec=$PACKAGE
Icon=$PACKAGE
Terminal=false
Categories=Network;
EOF
cp "$HERE/client/interchange.png" "$PKG/usr/share/icons/hicolor/256x256/apps/$PACKAGE.png"
cat > "$PKG/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: 6.3.16
Section: net
Priority: optional
Architecture: all
Maintainer: Interchange
Depends: $DEPENDS
Description: Interchange ${ROLE} application
 Native Debian/Astra package using the distribution Python and Qt runtime.
 Application data stays in the desktop user's home directory.
EOF
chmod 755 "$PKG/usr/bin/$PACKAGE"
find "$PKG" -type d -exec chmod 755 {} +
find "$PKG" -type f -not -path "$PKG/usr/bin/$PACKAGE" -exec chmod 644 {} +
mkdir -p output
OUTPUT="output/${PACKAGE}_6.3.16_all.deb"
dpkg-deb --root-owner-group --build "$PKG" "$OUTPUT"
dpkg-deb --info "$OUTPUT" >/dev/null
dpkg-deb --contents "$OUTPUT" >/dev/null
rm -rf "$PKG"
echo "READY: $HERE/$ROLE/$OUTPUT"
