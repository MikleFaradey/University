from pathlib import Path

root = Path(SPECPATH).resolve()
client = (root / ".." / ".." / ".." / "client").resolve()

a = Analysis(
    [str(client / "client_gui.py")],
    pathex=[str(client)],
    binaries=[],
    datas=[
        (str(client / "assets"), "assets"),
        (str(client / "icons"), "icons"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(root / "runtime_user_dir.py")],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Interchange",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / "interchange.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Interchange",
)
