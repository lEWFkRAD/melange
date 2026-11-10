from __future__ import annotations
from .grid import Grid
from .store import TimelineStore

def reconstruct(store: TimelineStore, branch: str, through: int | None=None, rows=24, cols=80) -> Grid:
    grid=Grid(rows,cols)
    for event in store.replay_events(branch,through):
        if event["kind"] == "grid_keyframe": grid=Grid.from_snapshot(store.get_blob(event["payload"]["blob"]))
        elif event["kind"] == "terminal_chunk":
            p=event["payload"]; grid.feed(store.get_blob(p["blob"]),event["id"],p.get("tool_event"),p["offset"])
    return grid

def provenance(store: TimelineStore, branch: str, event_id: int, row: int, col: int) -> dict:
    cell=reconstruct(store,branch,event_id).cells[row][col]
    if cell.chunk_id is None: return {"attributed":False,"reason":"control/redraw/empty"}
    return {"attributed": cell.tool_event is not None, "chunk":cell.chunk_id,"tool_event":cell.tool_event,"offset":cell.offset}
