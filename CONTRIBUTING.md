# Contributing to Melange

Thanks for being here. Melange is a video codec for computation: agent
sessions are recorded as timelines of keyframes and deltas, and those
timelines stay executable. You can rewind one, fork it, apply an edit, and
run it forward again. The pinned timeline is the Golden Path.

This guide covers setup, the test suite, and the rules a pull request has
to meet. The rules come from how the project was built, and they are the
reason the gate numbers in the README mean anything.

## Setup

You need Python 3.11 or newer (development happens on 3.12), on Linux.
The terminal capture layer is POSIX today, so the full suite expects a
Linux host with `tmux` available.

```bash
git clone https://github.com/lEWFkRAD/melange.git
cd melange
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test,solver,crypto,gui]"
```

The extras map to subsystems: `test` (pyte, the reference terminal),
`solver` (z3), `crypto` (at-rest encryption), `gui` (X11 surface).

## Running the tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

The whole suite should pass before you open a pull request. One test
skips itself unless it is on a sandbox host with `LR_SANDBOX_DIR` set
(the Firecracker integration test); that skip is expected on a normal
machine. GUI tests need an X server or Xvfb.

## Running the live service

The bridge also runs as a local service with encrypted timeline stores
and a shelf UI:

```bash
service/run.sh
```

It binds to 127.0.0.1:8798. The static surface in `surface-export/` is a
baked snapshot of the flagship example for static hosting; anything
interactive needs the live service behind it.

## The rules

1. **Nothing is accepted without forward-execution verification.**
   A fix, an edit operator, a solver result: each one is proven by
   running the timeline forward and comparing the outcome. A pull
   request that changes behavior must include the verification it ran,
   with the command and the result. Claims in prose do not count.
2. **The gates are the contract.** The README lists measured gates for
   replay fidelity, fork correctness, redaction, and the rest. If your
   change moves a gate number, show the before and after measurements
   in the pull request. A gate regression without an explanation and a
   maintainer decision will not merge.
3. **Synthetic data only.** Never commit a real recording, a real name,
   a real figure, or anyone's data. Fixtures and demos use invented
   people and invented numbers, always. The flagship example (Dana Ruiz)
   is the pattern to follow.
4. **Redaction and encryption fail closed.** Capture redacts before
   bytes reach storage, and encrypted stores refuse to open with the
   wrong key. Changes near `capture.py` or `crypto.py` must keep the
   redaction gate at zero seeded secrets in the persisted timeline.
5. **Forks never write to the parent.** A branch may diverge freely;
   the original timeline stays byte-identical. Tests assert this, and
   the invariant is not negotiable.
6. **Small, evidenced pull requests.** One change per pull request,
   with the test run and any gate measurements in the description.
   The pull request template walks you through it.

## Where to start

`ROADMAP.md` lists the open work, including pieces sized for a first
contribution: documentation, test corpora for terminal edge cases,
packaging, and CI hardening. If you want to take something larger, open
an issue first and describe the approach, especially where it touches
an invariant above. Design background lives in `docs/`, starting with
`docs/project-writeup-2026-10-16.md` and `docs/melange-ux-design.md`.

## Conduct

Participation is covered by `CODE_OF_CONDUCT.md`. Short version: argue
with the work, respect the people, bring evidence.
