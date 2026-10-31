INTERCHANGE CLIENT - MACOS INSTALLER BUILD

Output:
output/InterchangeClient.pkg

The .app and .pkg must be built on macOS because PyInstaller packages native
macOS Python/Qt binaries.

Build requirements:
- macOS
- python3
- requests
- PySide6
- PyInstaller
- Apple pkgbuild command

Build:
  cd installer/macos/client
  ./build_client_pkg.command

Install:
  open output/InterchangeClient.pkg

The installer places:
  /Applications/Interchange.app

CLEAN INSTALL POLICY

Before every installation, the package removes old Interchange-owned state for
all normal users under /Users and for /var/root.

Removed:
- .config/interchange
- .interchange
- InterchangeReceived
- InterchangeServerReceived
- Library/Application Support/Interchange
- Library/Caches/Interchange
- com.interchange.client preferences
- previous /Applications/Interchange.app
- system Interchange Application Support / Caches

This removes old ini files, caches, SQLite databases, PCAP files, logs and
spool data stored in Interchange-owned locations.

For complete manual uninstall:
  ./uninstall_client.command

Arbitrary custom folders outside Interchange-owned/default locations are not
recursively deleted.

QT BINDING POLICY

Frozen Windows/macOS builds use PySide6 only. The spec excludes PyQt5,
PyQt6 and PySide2 even if they are installed in the build environment.
The runtime hook selects PySide6 regardless of INTERCHANGE_QT_API inherited
from the user's shell. Linux DEB packages continue to use system PyQt5.
The build runs the frozen client's --self-test before creating the installer;
a failed test stops packaging. Rebuild using the platform build script after
updating the sources; existing installers are not updated automatically.
