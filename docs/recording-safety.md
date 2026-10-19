# Recording safety and replay corrections

The October 19 code review added regressions for four recording boundaries:

- Live PTY reads retain a possible credential token/assignment until it can
  be redacted as a whole. A fixed 64-byte cut could itself split a secret.
  UTF-8 bytes survive transport boundaries, and timeouts stop the child
  process session instead of blocking while draining its PTY.
- Fork-runner tool inputs/outputs, model prompts/tokens and persisted
  context notes pass through known-pattern redaction before ledger writes.
  Low-level TimelineStore.append remains a storage API; arbitrary callers
  must perform their own capture-side redaction.
- An encrypted store refuses to open without a key. Adding a key to an
  existing plaintext timeline is rejected rather than silently producing
  mixed storage; no in-place migration is implied.
- Workspace tar archives are built and restored in memory, avoiding a
  plaintext archive beside an encrypted timeline. Restore uses the safe
  tar data filter and refuses path traversal. The Python build must provide
  `tarfile.data_filter`; older unpatched builds fail closed.

Redaction covers the patterns in `redaction.py`, not arbitrary private
content. Workspace restoration intentionally writes the requested files
to the destination; encryption protects the stored snapshot, not that
working directory. The streaming buffer can retain a long unfinished
token until a delimiter or the capture deadline.

Standalone HTML exports now encode every `<` in embedded JSON, keeping
recorded text and branch names from becoming executable markup.

Chained clamp/explain operations rebuild the chosen computation's inputs
with inherited corrections. A second correction no longer resets the
first one. Synthetic forward verification changes wages to 48,000, then
withholding to 6,200: tax stays 3,088 and refund becomes 3,112, with the
parent unchanged. These are the project's demo arithmetic, not tax advice.

Run the focused regressions with unittest discovery patterns
`test_capture_storage_safety.py`, `test_export_safety.py`, and
`test_review_regressions.py`, followed by the full suite.
