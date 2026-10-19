"""Where uploaded and result files live while they are needed (then the janitor deletes them).

Files are stored on the service machine's disk under SERVICE_DATA_DIR, by random id only: a user's
file name never becomes part of a path. Uploads arrive in chunks (resumable: the client asks how
much arrived and continues from there).
"""

import hashlib
import os
import shutil
from pathlib import Path


class StorageError(Exception):
    pass


def _safe_id(value):
    if not value or not all(c in "0123456789abcdefghijklmnopqrstuvwxyz_" for c in value) or len(value) > 64:
        raise StorageError("bad id")
    return value


class LocalStorage:
    def __init__(self, root):
        self.root = Path(root).resolve()
        for sub in ("uploads", "outputs", "tmp"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- uploads
    def upload_path(self, upload_id):
        return self.root / "uploads" / f"{_safe_id(upload_id)}.bin"

    def upload_size(self, upload_id):
        p = self.upload_path(upload_id)
        return p.stat().st_size if p.exists() else 0

    def append_chunk(self, upload_id, offset, data, max_size):
        """Write `data` at `offset` (must be the current size: chunks arrive in order; a resent
        chunk that was already stored is accepted as long as it matches). Returns the new size."""
        p = self.upload_path(upload_id)
        size = p.stat().st_size if p.exists() else 0
        if offset > size:
            raise StorageError(f"missing data: the server has {size} bytes, this chunk starts at {offset}")
        end = offset + len(data)
        if end > max_size:
            raise StorageError("more data than the declared file size")
        if offset < size:                               # a chunk sent again after a lost reply
            with open(p, "rb") as f:
                f.seek(offset)
                existing = f.read(min(len(data), size - offset))
            if existing != data[:len(existing)]:
                raise StorageError("this chunk differs from the data already received")
            data = data[len(existing):]
            offset += len(existing)
            if not data:
                return size
        with open(p, "ab") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        return offset + len(data)

    def sha256(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()

    # ---------------------------------------------------------- outputs
    def output_path(self, job_id, output_id):
        folder = self.root / "outputs" / _safe_id(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{_safe_id(output_id)}.bin"

    def tmp_path(self, name):
        return self.root / "tmp" / _safe_id(name)

    # ---------------------------------------------------------- deleting
    def delete(self, path):
        if not path:
            return False
        p = Path(path).resolve()
        if self.root not in p.parents:
            raise StorageError("refusing to delete outside the storage folder")
        try:
            p.unlink()
            parent = p.parent
            if parent != self.root / "outputs" and parent.parent == self.root / "outputs" and not any(parent.iterdir()):
                parent.rmdir()
            return True
        except FileNotFoundError:
            return False

    def delete_job_folder(self, job_id):
        shutil.rmtree(self.root / "outputs" / _safe_id(job_id), ignore_errors=True)

    def used_bytes(self):
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())
