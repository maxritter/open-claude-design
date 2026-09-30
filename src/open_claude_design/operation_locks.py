"""Serialize scoped permission changes across local coding-agent processes."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import stat
import time
from collections.abc import Iterator
from pathlib import Path

from open_claude_design.auth import DesignAuthError, _open_secure_parent
from open_claude_design.config import CLAUDE_DESIGN_OPERATION_LOCK_PARTS, CLAUDE_DESIGN_OPERATION_LOCK_SECONDS
from open_claude_design.errors import ClaudeDesignSafetyError


@contextlib.contextmanager
def operation_lock(
    key: str, *, home: Path | None = None, timeout: float = CLAUDE_DESIGN_OPERATION_LOCK_SECONDS
) -> Iterator[None]:
    filename = hashlib.sha256(key.encode()).hexdigest() + ".lock"
    path = (home or Path.home()).joinpath(*CLAUDE_DESIGN_OPERATION_LOCK_PARTS, filename)
    try:
        parent = _open_secure_parent(path, create=True)
    except DesignAuthError as error:
        raise ClaudeDesignSafetyError("The operation-lock directory is unsafe.") from error
    assert parent is not None
    descriptor: int | None = None
    acquired = False
    try:
        if os.fstat(parent).st_uid != os.getuid():
            raise ClaudeDesignSafetyError("The operation-lock directory has another owner.")
        os.fchmod(parent, 0o700)
        descriptor = os.open(filename, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=parent)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_nlink != 1:
            raise ClaudeDesignSafetyError("The operation-lock file is unsafe.")
        os.fchmod(descriptor, 0o600)
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ClaudeDesignSafetyError(
                        "Another local agent is changing these permissions; retry after it finishes."
                    ) from None
                time.sleep(0.05)
        yield
    finally:
        if descriptor is not None:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        os.close(parent)
