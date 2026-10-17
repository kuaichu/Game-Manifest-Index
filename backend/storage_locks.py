"""Process and cross-process locks shared by data/cache writers."""

from contextlib import contextmanager
import os
import stat
from pathlib import Path
from threading import RLock, local


DATA_LOCK = RLock()
CACHE_LOCK = RLock()
RETENTION_LOCK = RLock()
_HELD_DATA_LOCKS = local()


@contextmanager
def data_file_lock(data_root: Path):
    """Serialize commits, allowing one thread to compose operations on one root.

    The outer call owns the OS lock. Nested store/index/catalog helpers on the
    same thread reuse it, without weakening locking for other threads/processes.
    Callers continue to acquire DATA_LOCK before entering a data transaction.
    """
    key = os.path.normcase(os.path.abspath(data_root))
    held = getattr(_HELD_DATA_LOCKS, "roots", None)
    if held is None:
        held = _HELD_DATA_LOCKS.roots = set()
    if key in held:
        yield
        return
    with _data_file_lock(Path(data_root)):
        held.add(key)
        try:
            yield
        finally:
            held.remove(key)


@contextmanager
def _data_file_lock(data_root: Path):
    """Acquire and release the OS lock once for the outermost caller."""
    data_root = Path(data_root)
    try:
        root_stat = os.lstat(data_root)
    except OSError as error:
        raise OSError("unsafe data root: it must be an existing directory") from error
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode) or getattr(root_stat, "st_file_attributes", 0) & 0x400:
        raise OSError("unsafe data root: symlink/reparse/non-directory")
    root_real = data_root.resolve()
    cache = data_root / ".cache"
    try:
        cache_stat = os.lstat(cache)
    except FileNotFoundError:
        cache.mkdir()
        cache_stat = os.lstat(cache)
    except OSError as error:
        raise OSError("unsafe data cache directory") from error
    if stat.S_ISLNK(cache_stat.st_mode) or not stat.S_ISDIR(cache_stat.st_mode) or getattr(cache_stat, "st_file_attributes", 0) & 0x400:
        raise OSError("unsafe data cache directory: symlink/reparse/non-directory")
    try:
        cache.resolve().relative_to(root_real)
    except ValueError as error:
        raise OSError("unsafe data cache directory: outside data root") from error
    path = cache / ".gmi-data.lock"
    if path.exists() or path.is_symlink():
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400:
            raise OSError("unsafe data lock path")
    else:
        init_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            init_flags |= os.O_BINARY
        try:
            init_fd = os.open(path, init_flags, 0o600)
            with os.fdopen(init_fd, "wb") as init_stream:
                init_stream.write(b"0")
                init_stream.flush()
                os.fsync(init_stream.fileno())
        except FileExistsError:
            pass
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    stream = os.fdopen(fd, "r+b")
    try:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                stream.seek(0)
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()
