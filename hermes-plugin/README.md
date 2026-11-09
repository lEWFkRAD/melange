# Melange — Hermes plugin

Melange is a video codec for computation. This plugin gives Hermes ten
tools that record terminal work as rewindable timelines and edit the
past honestly:

- `melange_record` — run a command in a PTY, record it as a timeline
- `melange_versions` — list the Original and every What-if, with seal status
- `melange_screen` — scrub to any step and see the reconstructed screen
- `melange_where_from` — where a character on screen came from, in plain words
- `melange_note` — pin a note into the recording itself
- `melange_whatif` — fork at a step with a new instruction
- `melange_clamp` — change one recorded input; only its dependents recompute
- `melange_explain` — what went wrong? forward-verified candidate causes
- `melange_shelf` — keep or release a What-if
- `melange_demo` — the bundled flagship: a synthetic return, corrected end to end

All processing is local and stdlib-only. No network calls. Recordings
live under `~/.hermes/plugins-data/melange/`. Capture-side redaction
strips API keys, AWS credentials, password assignments, and SSNs before
anything is stored.

Install:

```bash
hermes plugins install https://github.com/lEWFkRAD/melange
hermes plugins enable melange
```
