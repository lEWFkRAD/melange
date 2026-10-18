from __future__ import annotations
import argparse
from .replay import provenance, reconstruct
from .store import TimelineStore

def main():
    p=argparse.ArgumentParser(description="Minimal Living Replay terminal scrubber")
    p.add_argument("timeline"); p.add_argument("branch"); p.add_argument("--event",type=int); p.add_argument("--cell",nargs=2,type=int,metavar=("ROW","COL"))
    a=p.parse_args(); store=TimelineStore(a.timeline); grid=reconstruct(store,a.branch,a.event)
    print(grid.screen())
    if a.cell: print(provenance(store,a.branch,a.event or store.events(a.branch)[-1]["id"],*a.cell))
if __name__ == "__main__": main()
