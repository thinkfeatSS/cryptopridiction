"""
QUANT EDGE V16: Cross-Platform Inter-Process Lock
Specifications:
- Rule 5 & 8: Safe execution and concurrency controls
- Native OS locking via msvcrt (Windows) and fcntl (Unix)
- Zero external dependencies (no sqlalchemy required)
"""

import os
import time

class CrossProcessLock:
    """
    Cross-platform non-blocking inter-process file lock.
    Uses msvcrt on Windows and fcntl on Unix to provide mutual exclusion
    across distinct operating system processes (daemon scanner vs web workers).
    """
    def __init__(self, lockfile_path: str):
        self.lockfile_path = lockfile_path
        self._file = None

    def acquire(self) -> bool:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.lockfile_path)), exist_ok=True)
            self._file = open(self.lockfile_path, "a+")
            if os.name == "nt":
                import msvcrt
                try:
                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                    return True
                except (IOError, OSError):
                    try:
                        self._file.close()
                    except Exception:
                        pass
                    self._file = None
                    return False
            else:
                import fcntl
                try:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except (IOError, OSError):
                    try:
                        self._file.close()
                    except Exception:
                        pass
                    self._file = None
                    return False
        except Exception:
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
            return False

    @property
    def is_locked(self) -> bool:
        return self._file is not None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def release(self):
        if self._file is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            finally:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
