# Interchange 6.3.16 packaging

Build native installers **on the target operating system**. Windows and macOS freeze PySide6 from an isolated virtual environment, explicitly excluding PyQt5, PyQt6 and PySide2. Debian/Astra Linux packages distribute source code with system PyQt5, avoiding PyInstaller/glibc portability issues.

| Component | Windows (Inno Setup 6) | macOS (pkgbuild) | Debian/Astra Linux (dpkg-deb) |
| --- | --- | --- | --- |
| Client | `windows/client/build_client_installer.bat` | `macos/client/build_client_pkg.command` | `linux/client/build_client_deb.sh` |
| Server | `windows/server/build_server_installer.bat` | `macos/server/build_server_pkg.command` | `linux/server/build_server_deb.sh` |
| Admin | `windows/admin/build_admin_installer.bat` | `macos/admin/build_admin_pkg.command` | `linux/admin/build_admin_deb.sh` |

Paths above are relative to `installer/`. For Windows/macOS server packaging, Python 3, pip and PySide6-compatible libraries are installed by the scripts in fresh `.venv-build` folders; macOS also requires Xcode Command Line Tools (`pkgbuild`), and Windows requires Inno Setup 6. Linux requires `dpkg-deb` and Python 3.

Packages are independent: install the Server and Admin packages separately on the **same user account** to share `~/.config/interchange/server.ini` and `~/.interchange/lan_exchange.db`. Configure/launch the Server first, then open the Admin Panel. Server data and PCAPs are not removed on uninstall or upgrade. Do not run the server as root/Administrator; the configured user's home must remain writable.

The Linux package launchers are `interchange-server` and `interchange-admin`. The server includes a GUI and optional `--no-gui` mode; run `interchange-server --no-gui` after configuring it from the GUI if running headless. Packet captures require `tcpdump`/appropriate interface permissions (or `dumpcap` on Windows/macOS), installed and configured separately. Grant capabilities only to the capture tool, **never** launch the Python server as root.

macOS: packaged binaries are inside `/Applications/InterchangeServer.app/Contents/MacOS/` and `/Applications/InterchangeAdmin.app/Contents/MacOS/`; the apps may need Gatekeeper approval if not signed/notarized. Windows: installed apps appear in the Start Menu, no service is created automatically. Neither platform silently configures elevated packet capture access.

The macOS and Windows server/admin builders run `--self-test` on each frozen binary before producing the installer. Source and build scripts are committed, **not** prebuilt cross-OS binaries; the GitHub Actions `Build native installers` workflow publishes them as downloadable artifacts after successful platform-specific jobs.
