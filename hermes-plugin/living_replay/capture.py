from __future__ import annotations
import fcntl, os, pty, select, signal, struct, subprocess, termios, time
from .grid import Grid
from .redaction import redact_bytes, split_redaction_buffer
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
    def run(self, argv: list[str], timeout=10.0, tool_event: int | None=None) -> int:
        master, slave=pty.openpty()
        # Real TUIs query the window size; a 0x0 PTY makes them fail or guess.
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.grid.rows, self.grid.cols, 0, 0))
        try:
            proc=subprocess.Popen(argv,stdin=slave,stdout=slave,stderr=slave,close_fds=True,
                                  start_new_session=True)
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        os.set_blocking(master, False)
        end=time.monotonic()+timeout; pending=b""
        def push(data: bytes, final: bool=False):
            nonlocal pending
            pending += data
            emit, pending = split_redaction_buffer(pending, final=final)
            if emit: self.record_bytes(emit, tool_event)
        try:
            while True:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                ready,_,_=select.select([master],[],[],min(.05, remaining))
                if ready:
                    try: data=os.read(master,8192)
                    except BlockingIOError: continue
                    except OSError: break
                    if not data: break
                    push(data)
            return proc.wait(timeout=max(0, end-time.monotonic()))
        except BaseException:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            proc.wait()
            raise
        finally:
            os.close(master)
            push(b"", final=True)
