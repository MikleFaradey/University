from pathlib import Path
hidden = []

root = Path(SPECPATH).resolve()
source = (root / ".." / ".." / ".." / "server").resolve()
installer = (root / ".." / "..").resolve()
a = Analysis(
    [str(source / "admin_panel.py")],
    pathex=[str(source)],
    binaries=[],
    datas=[],
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
    name="InterchangeAdmin", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    icon=str(root.parent / "client" / "interchange.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="InterchangeAdmin")
