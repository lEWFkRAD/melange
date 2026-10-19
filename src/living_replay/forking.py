from __future__ import annotations
import io, tarfile
from pathlib import Path
from .store import TimelineStore

def snapshot_workspace(store: TimelineStore, branch: str, source: str | Path) -> int:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        tar.add(Path(source), arcname=".")
    return store.append(branch,"workspace_snapshot",{"blob":store.put_blob(archive.getvalue()),"format":"tar.gz"})

def restore_workspace(store: TimelineStore, snapshot_event: int, destination: str | Path) -> Path:
    event=store.event(snapshot_event); dest=Path(destination); dest.mkdir(parents=True,exist_ok=True)
    archive=io.BytesIO(store.get_blob(event["payload"]["blob"]))
    with tarfile.open(fileobj=archive, mode="r:gz") as tar:
        if not hasattr(tarfile, "data_filter"):
            raise RuntimeError("safe workspace restore requires tarfile.data_filter")
        members=tar.getmembers()
        for member in members:
            tarfile.data_filter(member, str(dest))
        tar.extractall(dest, members=members, filter="data")
    return dest
