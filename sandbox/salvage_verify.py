#!/usr/bin/env python3
"""Salvage verification for a live-capture tree whose runner died at the
replay leg: verify the orig + fork legs from their extracted timelines."""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/kip/lr-repo/src")
sys.path.insert(0, "/home/kip/lr-repo/sandbox")
from living_replay.crypto import LocalKeyProvider
from living_replay.store import TimelineStore
from run_hermes_guest import strata_key

work = Path(sys.argv[1])
master = (work / "master.b64").read_text().strip()


def load(name):
    store = TimelineStore(work / name / "timeline",
                          key_provider=LocalKeyProvider(__import__("base64").b64decode(master)))
    return store, store.events("main")


def brief(name):
    p = work / name / "ws" / "brief.md"
    return p.read_bytes() if p.exists() else b""


so, eo = load("extract-orig")
sf, ef = load("extract-fork")
if eo:
    print("event keys:", sorted(eo[0].keys()))
mc_o = [e for e in eo if e.get("kind") == "model_call"]
mc_f = [e for e in ef if e.get("kind") == "model_call"]
bo, bf = brief("extract-orig"), brief("extract-fork")
prefix = 0
for a, b in zip(eo, ef):
    if a.get("hash") == b.get("hash"):
        prefix += 1
    else:
        break
key = strata_key()
blob = json.dumps([e.get("payload") for e in eo + ef]).encode()
out = {
    "orig_events": len(eo), "fork_events": len(ef),
    "orig_model_calls": len(mc_o), "fork_model_calls": len(mc_f),
    "orig_model_vias": sorted({(e.get("payload") or {}).get("via") for e in mc_o}),
    "shared_prefix_events": prefix,
    "brief_orig_bytes": len(bo), "brief_fork_bytes": len(bf),
    "orig_has_risks_section": b"Risks and open items" in bo,
    "orig_has_999": b"99.9" in bo, "orig_has_9985": b"99.85" in bo,
    "fork_has_9985": b"99.85" in bf, "fork_has_999": b"99.9" in bf,
    "orig_chain_verify": so.verify("main"),
    "fork_chain_verify": sf.verify("main"),
    "strata_key_in_timelines": bool(key) and key.encode() in blob,
}
print(json.dumps(out, indent=2))
