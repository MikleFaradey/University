INTERCHANGE CLIENT INSTALLER BUILD

Target:
Windows 10/11 x64

Result:
output\InterchangeClientSetup.exe

Required on the BUILD computer:
- Python 3
- Inno Setup 6
- Internet access for pip packages during the build

Build:
1. Open installer\windows\client
2. Run build_client_installer.bat
3. Take output\InterchangeClientSetup.exe

CLEAN INSTALL POLICY

Every installation of InterchangeClientSetup.exe intentionally removes the
previous local Interchange state before copying the new version.

Removed:
- previous installed program files
- %USERPROFILE%\.config\interchange
- %USERPROFILE%\.interchange
- client.ini
- server.ini if present in the same Interchange config directory
- client cache databases
- server SQLite database if present in .interchange
- WAL/SHM database files if present
- PCAP files under .interchange
- Interchange logs and spool data under .interchange
- %USERPROFILE%\InterchangeReceived
- %USERPROFILE%\InterchangeServerReceived
- %APPDATA%\Interchange
- %LOCALAPPDATA%\Interchange

Uninstall uses the same cleanup policy.

The installer does not recursively delete arbitrary custom folders outside
these Interchange-owned/default locations. This prevents accidental deletion
of unrelated folders such as Documents or Downloads if a user selected them
as a custom destination.

After every new install, Interchange behaves like a first installation and
asks for connection settings again.

QT BINDING POLICY

Frozen Windows/macOS builds use PySide6 only. The spec excludes PyQt5,
PyQt6 and PySide2 even if they are installed in the build environment.
The runtime hook selects PySide6 regardless of INTERCHANGE_QT_API inherited
from the user's shell. Linux DEB packages continue to use system PyQt5.
The build runs the frozen client's --self-test before creating the installer;
a failed test stops packaging. Rebuild using the platform build script after
updating the sources; existing installers are not updated automatically.
