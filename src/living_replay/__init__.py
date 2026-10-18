"""Living Replay Build 1 reference implementation."""

from .store import TimelineStore
from .grid import Grid

try:  # PTY capture is POSIX-only (pty/fcntl); the rest of the library is not.
    from .capture import PtyCapture
except ImportError:  # pragma: no cover - Windows hosts
    PtyCapture = None

__all__ = ["TimelineStore", "Grid", "PtyCapture"]
