#!/usr/bin/env python3
"""Copy the engine modules the Hermes plugin needs into hermes-plugin/.

`hermes plugins install` copies only the plugin directory, so the plugin
cannot import from ../src. This keeps a bundled copy of the modules it uses.

  python tools/sync_hermes_plugin.py          refresh the bundled copy
  python tools/sync_hermes_plugin.py --check  exit 1 if it is out of date
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "living_replay"
DST = ROOT / "hermes-plugin" / "living_replay"
ENTRY = ["__init__", "bridge", "shelf", "capture", "ingest", "store", "flagship"]


def closure():
    mods = {p.stem for p in SRC.glob("*.py")}
    need, todo = set(), list(ENTRY)
    while todo:
        mod = todo.pop()
        if mod in need:
            continue
        need.add(mod)
        text = (SRC / f"{mod}.py").read_text()
        deps = set(re.findall(r"from (?:\.|living_replay\.)(\w+) import", text))
        for names in re.findall(r"from (?:\.|living_replay) import ([\w, ]+)", text):
            deps |= {n.strip() for n in names.split(",")}
        todo += sorted(deps & mods)
    return sorted(need)


def main():
    check = "--check" in sys.argv
    wanted = {f"{m}.py": (SRC / f"{m}.py").read_bytes() for m in closure()}
    have = {p.name: p.read_bytes() for p in DST.glob("*.py")} if DST.is_dir() else {}
    if check:
        if wanted != have:
            stale = sorted(set(wanted) ^ set(have) | {n for n in wanted if have.get(n) != wanted[n]})
            print("hermes-plugin/living_replay is out of date:", ", ".join(stale))
            print("run: python tools/sync_hermes_plugin.py")
            return 1
        return 0
    DST.mkdir(exist_ok=True)
    for name in set(have) - set(wanted):
        (DST / name).unlink()
    for name, data in wanted.items():
        (DST / name).write_bytes(data)
    print(f"bundled {len(wanted)} modules into {DST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
