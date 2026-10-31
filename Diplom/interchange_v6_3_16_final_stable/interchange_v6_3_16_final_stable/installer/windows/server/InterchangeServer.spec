from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

hidden = (collect_submodules("scapy") +
          collect_submodules("sklearn") +
          collect_submodules("joblib"))

root = Path(SPECPATH).resolve()
source = (root / ".." / ".." / ".." / "server").resolve()
installer = (root / ".." / "..").resolve()
a = Analysis(
    [str(source / "server.py")],
    pathex=[str(source)],
    binaries=[],
    datas=[(str(source / "assets"), "assets")],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(installer / "runtime_user_dir.py")],
    excludes=["PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="InterchangeServer", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
    icon=str(root.parent / "client" / "interchange.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="InterchangeServer")
