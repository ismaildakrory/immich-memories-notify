"""File locking utility for concurrent access protection."""

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


@contextmanager
def file_lock(filepath: str, exclusive: bool = True) -> Generator[None, None, None]:
    """
    Context manager for file locking.

    Args:
        filepath: Path to the file to lock
        exclusive: If True, use exclusive lock (write); if False, use shared lock (read)

    Usage:
        with file_lock('/path/to/file.json', exclusive=True):
            # Safe to read/write the file
            pass
    """
    lock_path = Path(filepath).with_suffix(Path(filepath).suffix + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_file = open(lock_path, 'w')
    try:
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lock_file.fileno(), lock_type)
        yield
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


@contextmanager
def read_lock(filepath: str) -> Generator[None, None, None]:
    """Acquire a shared (read) lock on a file."""
    with file_lock(filepath, exclusive=False):
        yield


@contextmanager
def write_lock(filepath: str) -> Generator[None, None, None]:
    """Acquire an exclusive (write) lock on a file."""
    with file_lock(filepath, exclusive=True):
        yield
