## What this changes

One change per pull request. Describe it plainly.

## Forward-execution verification

Nothing in this project is accepted on a claim. Paste the check you
ran and its result: the command, and the output that proves the new
behavior by running a timeline forward.

## Gates

- [ ] Full test suite passes locally (`PYTHONPATH=src python3 -m unittest discover -s tests`)
- [ ] If a gate number in the README moved, before and after measurements are included above
- [ ] Redaction and encryption still fail closed (required if you touched `capture.py` or `crypto.py`)
- [ ] Forks still never write to the parent timeline

## Data hygiene

- [ ] Fixtures and examples use synthetic data only: invented people, invented figures, no real recordings

## Docs

- [ ] README, ROADMAP, or docs updated where behavior or status changed
