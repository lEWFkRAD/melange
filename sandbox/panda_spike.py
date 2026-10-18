"""PANDA spike (Build 3, B3-G5) — run INSIDE the pandare/panda container.

Measured stages, printed as SPIKE lines, never faked past a failure:
boot -> transform a seeded file with a stock binary -> record the
execution -> replay it under taint2 -> inventory the taint-label/query
surface for the actual rung-4 question (can the input FILE's bytes be
labeled so an output byte query names their ranges?).
"""
import sys, time

RESULTS = {}

def stage(name, ok, detail=""):
    RESULTS[name] = (ok, detail)
    print(f"SPIKE {name}: {'OK' if ok else 'FAIL'} {detail}", flush=True)

t0 = time.time()
try:
    from pandare import Panda
    panda = Panda(generic="x86_64", mem="256M", expect_prompt=True)
    stage("boot", True, f"{time.time()-t0:.0f}s")
except Exception as e:
    stage("boot", False, repr(e)); sys.exit(0)

def work():
    try:
        panda.run_serial_cmd("printf 'amount=21\\n' > /root/in.txt")
        out = panda.run_serial_cmd("sed s/21/42/ /root/in.txt > /root/out.txt; cat /root/out.txt")
        stage("transform", "amount=42" in out, out.strip()[:80])
    except Exception as e:
        stage("transform", False, repr(e))
    try:
        panda.record_cmd("sed s/21/42/ /root/in.txt > /root/out.txt", "spike_rec")
        stage("record", True)
    except Exception as e:
        stage("record", False, repr(e))
    try:
        panda.load_plugin("taint2")
        stage("taint2-load", True, f"taint_enabled={panda.taint_enabled() if hasattr(panda, 'taint_enabled') else '?'}")
    except Exception as e:
        stage("taint2-load", False, repr(e))
    try:
        panda.begin_replay("spike_rec")
        panda.end_replay()
        stage("taint-replay", True)
    except Exception as e:
        stage("taint-replay", False, repr(e))
    label_api = [n for n in dir(panda) if n.startswith("taint_label") or n.startswith("taint_get") or n.startswith("taint_check")]
    stage("taint-api", bool(label_api), ",".join(label_api))
    file_label = [n for n in dir(panda) if "file" in n.lower() and ("taint" in n.lower() or "label" in n.lower())]
    stage("file-label-api", bool(file_label),
          ",".join(file_label) if file_label else
          "no file-label entry point in this build: taint2 labels RAM/registers by address, "
          "so labeling a guest FILE's bytes needs the separate file_taint plugin or in-guest cooperation")
    panda.end_analysis()

panda.queue_blocking(work)
panda.run()
print("SPIKE DONE", RESULTS, flush=True)
