INTERCHANGE CLIENT - LINUX / ASTRA / DEBIAN DEB

Release: 6.3.16
Output: output/interchange-client_6.3.16_all.deb

The Linux package is now a native source-based Debian package. It no longer
freezes Python/Qt with PyInstaller. apt installs the distribution Python,
Requests and PyQt5 runtime, so Qt/XCB and glibc dependencies are resolved by
the target Debian/Astra repository instead of being copied from the build PC.

Build requirements:
- bash
- python3 (used only for the Python 3.7 syntax check)
- dpkg-deb

Build:
  cd installer/linux/client
  ./build_client_deb.sh

Install or upgrade:
  sudo apt install ./output/interchange-client_6.3.16_all.deb

Run:
  interchange-client

Diagnostics:
  interchange-client --diagnose

Runtime package dependencies installed by apt:
- python3 (>= 3.7)
- python3-requests
- python3-pyqt5

`python3-pyqt5` pulls the matching Qt5/PyQt5 core/gui and native
platform dependencies from the Linux distribution. The launcher also sets
PYTHONNOUSERSITE=1 so an unrelated/broken PySide installed in ~/.local cannot
override the package-managed Qt runtime.

UPGRADE FIXES

1. Older builds hard-coded Debian package version 6.3.0. This release uses
   6.3.16 so apt/dpkg can perform a real upgrade.
2. Older postrm removed /opt/interchange/client for every maintainer-script
   action. During an upgrade the old package postrm can execute after the new
   package has been unpacked, deleting the newly installed application. postrm
   now only removes user state on an explicit purge and never deletes the
   package payload.
3. Normal upgrades preserve Interchange user identity/config/cache. A first
   install still applies the project's clean-install policy.
4. Desktop starts write launcher failures to:
   ~/.local/state/interchange/launcher.log

If a machine still cannot start the GUI, run `interchange-client --diagnose`;
it performs Python/Requests/PyQt5 imports and a headless Qt application
self-test and prints the exact failure in the terminal.
