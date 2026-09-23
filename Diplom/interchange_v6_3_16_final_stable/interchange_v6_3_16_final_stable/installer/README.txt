INTERCHANGE INSTALLERS

Windows client:
  installer/windows/client
  Builds InterchangeClientSetup.exe with PyInstaller + Inno Setup.

Linux / Astra / Debian client:
  installer/linux/client
  Builds interchange-client_6.3.16_all.deb.
  The DEB installs the Python source and uses distribution-managed
  python3-requests + PyQt5/Qt5. It intentionally does NOT use PyInstaller on
  Linux, avoiding Qt/XCB/glibc incompatibilities between Linux releases.

macOS client:
  installer/macos/client
  Builds the native .app/.pkg on macOS using PyInstaller.

See each platform BUILD_README.txt for commands.
