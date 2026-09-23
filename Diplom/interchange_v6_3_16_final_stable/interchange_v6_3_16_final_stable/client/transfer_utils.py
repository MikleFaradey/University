import hashlib
import tempfile
import zipfile
from pathlib import Path

CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def make_folder_zip(folder: Path) -> Path:
    folder = folder.resolve()
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    zip_path = Path(tmp.name)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        root = folder.name
        zf.writestr(root.rstrip("/") + "/", "")
        for p in folder.rglob("*"):
            rel = p.relative_to(folder)
            arc = (Path(root) / rel).as_posix()
            if p.is_dir():
                zf.writestr(arc.rstrip("/") + "/", "")
            elif p.is_file():
                zf.write(p, arc)
    return zip_path


def safe_extract(zip_path: Path, destination: Path):
    destination = destination.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(destination)
            except ValueError:
                raise RuntimeError(f"Unsafe path in archive: {member.filename}")


            unix_mode = (member.external_attr >> 16) & 0o170000
            if unix_mode == 0o120000:
                raise RuntimeError(f"Symbolic link in archive is not allowed: {member.filename}")

        zf.extractall(destination)
