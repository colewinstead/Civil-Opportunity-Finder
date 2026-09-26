"""Local OS lock shared by the web process and CLI collection commands."""
import hashlib
import os

from app.config import ROOT


class CollectionFileLock:
    def __init__(self, database_url: str):
        key = hashlib.sha256(database_url.encode()).hexdigest()[:16]
        self.path = ROOT / "data" / f"collection-{key}.lock"
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is not None:
            self.handle.close()  # Closing releases the OS lock, including on crashes.
            self.handle = None
