from __future__ import annotations
import shutil
from pathlib import Path
from .store import TimelineStore

def snapshot_workspace(store: TimelineStore, branch: str, source: str | Path) -> int:
    source=Path(source); archive=shutil.make_archive(str(store.root / f"snapshot-{branch}"),"gztar",source)
    return store.append(branch,"workspace_snapshot",{"blob":store.put_blob(Path(archive).read_bytes()),"format":"tar.gz"})

def restore_workspace(store: TimelineStore, snapshot_event: int, destination: str | Path) -> Path:
    event=store.event(snapshot_event); dest=Path(destination); dest.mkdir(parents=True,exist_ok=True)
    archive=dest / ".living-replay-snapshot.tar.gz"; archive.write_bytes(store.get_blob(event["payload"]["blob"]))
    shutil.unpack_archive(archive,dest); archive.unlink(); return dest
