## Build 2 complete: live capture verified end to end (Kip)

Run tree: /home/kip/lr-sandbox/live-1792176400 (onyx-Linux). A real, unscripted Hermes session (the production agent stack, served by the Strata engine through the host bridge) ran inside the boundary, driven turn by turn from the host over the control channel.

**Original session.** Read the Build 1 session notes from its data drive and wrote a status brief, added a Risks and open items section on turn 2, snapshotted mid-session, finished on turn 3. 153 timeline events, 16 model calls, all via the vsock bridge. The brief it wrote is a real document (2,188 bytes, on file).

**Fork.** Resumed from the mid-session snapshot with the correction (replay fidelity 99.85, not the notes' rounded 99.9). Shared prefix with the original: 108 hash-identical events. Fork finished at 182 events / 15 model calls. Its brief carries 99.85 and never 99.9; the original's brief carries 99.9 and never 99.85. Both timelines' hash chains verify. The original was never written by the fork (separate data image; chain intact).

**Replay by record, zero live calls.** A fresh guest replayed the original session with NO model bridge started (a live call was impossible by construction): 153 events, 16 model calls served entirely from the record, 0 REPLAY-MISS, every chat response identical to the original session's, and the brief reproduced byte for byte (2,188 bytes).

**Leakage.** Decryption with a wrong key is rejected. The Strata credential never entered the guest or its record: the guest config carries only a placeholder and the bridge substitutes the real key host-side. Note on method: the estate token is short and appears inside the word "local" throughout the recorded tool schemas (114 occurrences, every one inside "local"), so the runner's leakage gate is now a standalone-token scan; no standalone occurrence exists in either timeline.

**The boot-entropy defect and its fix (the long pole of this ticket).** Fresh guests repeatedly stalled at boot: the serial ends at the agent's first urandom read and the kernel CRNG never initializes. Verified by elimination: Firecracker's entropy device accepts configuration but never surfaces in this kernel (no device registers, with or without a rate limiter), and random.trust_cpu=on is ignored. Healthy boots initialized CRNG from interrupt jitter in about 170s; stalled boots never did (600s timeouts, three times). Fix, now permanent in the harness: the live image (rootfs-live.ext4) has an init that credits 512 host-written random bytes (/data/seed.bin) into the guest kernel pool via RNDADDENTROPY before any agent starts, and run_live_guest.py writes a fresh seed into every data drive. Measured effect: CRNG initialized at 0.89s guest time, LR-READY at 1.1s wall. The fixture image used by Build 1 is untouched.

Artifacts: run tree above (timelines, extracts, serials, shim logs); runner at sandbox/run_live_guest.py (fixed in place); the session brief is the session's own product.

Closing this ticket. Remaining Melange work continues on its own tickets: ONY-188 (early-cutoff measurement), ONY-169 (two doors), ONY-173 (repo).

Author: Kip (Muse)
