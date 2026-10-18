"""Guest agent — flagship mode (Build 3). Runs the whole synthetic
return demo inside the microVM: timeline, Fact Graph, fork and amended
branch all land on the data drive; the measured results print to the
serial console as one JSON line for the host to assert on."""
import json, sys
from pathlib import Path

sys.path.insert(0, "/opt/living_replay")
from living_replay.flagship import run_flagship

def say(msg): print(msg, flush=True)

out = run_flagship(Path("/data/flagship-run"))
summary = {
    "totalTax": out["figures"]["/totalTax"], "refund": out["figures"]["/refund"],
    "amended_totalTax": out["amended_figures"]["/totalTax"],
    "parent_unchanged": out["parent_unchanged"],
    "recomputed": out["recomputed_nodes"], "graph_nodes": out["graph_nodes"],
    "wages_span": out["provenance_total_tax"]["/wages"]["span"],
    "wages_span_text": out["intake_span_text"],
}
say("LR-FLAGSHIP " + json.dumps(summary))
say("LR-FLAGSHIP-DONE")
import os, time
os.sync()
while True: time.sleep(60)
