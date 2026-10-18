from __future__ import annotations
import fcntl, os, pty, select, struct, subprocess, termios, time
from .grid import Grid
from .redaction import redact_bytes
from .store import TimelineStore

class PtyCapture:
    """Owns the PTY; reads raw output with monotonic timestamps and byte offsets."""
    def __init__(self, store: TimelineStore, branch="main", rows=24, cols=80, keyframe_every=1, grid: Grid | None=None, offset=0):
        self.store,self.branch,self.grid,self.offset,self.every=store,branch,(grid or Grid(rows,cols)),offset,keyframe_every
    def record_bytes(self, raw: bytes, tool_event: int | None=None) -> int:
        safe=redact_bytes(raw); blob=self.store.put_blob(safe)
        eid=self.store.append(self.branch,"terminal_chunk",{"blob":blob,"offset":self.offset,"length":len(safe),"raw_length":len(raw),"tool_event":tool_event})
        self.grid.feed(safe,eid,tool_event,self.offset); self.offset+=len(safe)
        if eid % self.every == 0:
            self.store.append(self.branch,"grid_keyframe",{"blob":self.store.put_blob(self.grid.snapshot()),"through":eid})
        return eid
    # Bytes withheld at the tail of a live stream so a secret split across
    # two PTY reads is still whole when redaction sees it. Longer than any
    # redaction pattern's realistic match.
    TAIL = 64
    def run(self, argv: list[str], timeout=10.0, tool_event: int | None=None) -> int:
        master, slave=pty.openpty()
        # Real TUIs query the window size; a 0x0 PTY makes them fail or guess.
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.grid.rows, self.grid.cols, 0, 0))
        proc=subprocess.Popen(argv,stdin=slave,stdout=slave,stderr=slave,close_fds=True); os.close(slave)
        end=time.monotonic()+timeout; pending=b""
        def push(data: bytes, final: bool=False):
            nonlocal pending
            pending += data
            if final or len(pending) > self.TAIL:
                emit, pending = (pending, b"") if final else (pending[:-self.TAIL], pending[-self.TAIL:])
                if emit: self.record_bytes(emit, tool_event)
        try:
            while time.monotonic()<end and (proc.poll() is None):
                ready,_,_=select.select([master],[],[],.05)
                if ready:
                    try: data=os.read(master,8192)
                    except OSError: break
                    if data: push(data)
            while True:
                try: data=os.read(master,8192)
                except OSError: break
                if not data: break
                push(data)
        finally: os.close(master)
        push(b"", final=True)
        return proc.wait(timeout=1)
