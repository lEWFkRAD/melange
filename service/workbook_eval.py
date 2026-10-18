"""Workbook evaluation adapter for the Melange service.

House-rule checks and clamp forks need a branch's values recomputed
from its inputs. For workbook recordings that computation lives in the
Excel lane's workbook_profile (formula graph extracted from the .xlsx,
evaluated on the canonical incremental Engine) — the same evaluator
the M7 pin demo used. This adapter locates that profile lazily:

- profile_dir: the registry entry's "profile_dir", else
  $MELANGE_EXCEL_DIR, else ~/workspace/your_files/melange-excel;
- fixture: the registry entry's "fixture", else
  <profile_dir>/melange-fixture.xlsx.

The import happens on first use, so the service runs fine (and every
non-workbook endpoint works) on a Python without openpyxl; a clamp
request then fails honestly instead of at startup.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_MODELS: dict[str, object] = {}


def _profile_dir(entry: dict) -> Path:
    raw = entry.get("profile_dir") or os.environ.get("MELANGE_EXCEL_DIR") \
        or str(Path.home() / "workspace" / "your_files" / "melange-excel")
    return Path(os.path.expanduser(raw))


def _model(entry: dict):
    profile_dir = _profile_dir(entry)
    fixture = Path(os.path.expanduser(
        entry.get("fixture") or str(profile_dir / "melange-fixture.xlsx")))
    key = str(fixture)
    if key not in _MODELS:
        if str(profile_dir) not in sys.path:
            sys.path.insert(0, str(profile_dir))
        import workbook_profile as wp
        _MODELS[key] = (wp, wp.load_model(fixture))
    return _MODELS[key]


def make_evaluate(entry: dict, base_inputs: dict):
    """evaluate(overrides) -> full values dict, M7-demo semantics."""
    wp, model = _model(entry)

    def evaluate(overrides):
        eng = wp.build_engine(model, base_inputs)
        values = eng.build()
        for target, value in overrides.items():
            values = eng.edit(target, value)
        return values

    return evaluate
