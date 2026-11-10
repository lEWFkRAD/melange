from __future__ import annotations
import hashlib, json, sqlite3, threading, time
from pathlib import Path
from typing import Any

GENESIS = "0" * 64

def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

class TimelineStore:
    """Append-only, hash-chained SQLite ledger plus content-addressed blobs.

    With `key_provider` set (Build 3), the timeline is encrypted at rest:
    a per-timeline DEK (wrapped in key.json) seals every blob and event
    payload with AES-256-GCM. The public API is unchanged; opening with
    the wrong key raises crypto.TimelineKeyError (fails closed).
    """
    def __init__(self, root: str | Path, key_provider=None):
        self.root = Path(root)
        has_key = (self.root / "key.json").exists()
        if has_key and key_provider is None:
            from .crypto import TimelineKeyError
            raise TimelineKeyError("encrypted timeline requires a key provider")
        if key_provider is not None and not has_key and (
                (self.root / "timeline.sqlite").exists() or
                ((self.root / "objects").exists() and any((self.root / "objects").iterdir()))):
            from .crypto import TimelineKeyError
            raise TimelineKeyError("cannot enable encryption on an existing unencrypted timeline")
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs = self.root / "objects"; self.blobs.mkdir(exist_ok=True)
        self.crypto = None
        if key_provider is not None:
            from .crypto import TimelineCrypto
            self.crypto = TimelineCrypto(self.root, key_provider)
        # Appends arrive from more than one thread (the guest agent's
        # main thread writes screen/context events while its sink thread
        # writes model_call events). Share the connection across threads
        # and serialize appends: append is read-modify-write on the hash
        # chain, so two appends must never interleave.
        self._append_lock = threading.Lock()
        self.db = sqlite3.connect(self.root / "timeline.sqlite",
                                  check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, branch TEXT NOT NULL, parent_event INTEGER,
          kind TEXT NOT NULL, mono_ns INTEGER NOT NULL, payload TEXT NOT NULL,
          prev_hash TEXT NOT NULL, hash TEXT NOT NULL UNIQUE);
        CREATE INDEX IF NOT EXISTS events_branch_id ON events(branch,id);
        """)
        self.db.commit()
    def put_blob(self, data: bytes) -> str:
        # Encrypted timelines address blobs by their ciphertext hash: the
        # plaintext never touches disk, and equality of plaintexts is not
        # leaked by the address (random nonce per blob).
        stored = self.crypto.encrypt(data, b"living-replay-blob") if self.crypto else data
        digest = hashlib.sha256(stored).hexdigest(); target = self.blobs / digest
        if not target.exists(): target.write_bytes(stored)
        return digest
    def get_blob(self, digest: str) -> bytes:
        raw = (self.blobs / digest).read_bytes()
        return self.crypto.decrypt(raw, b"living-replay-blob") if self.crypto else raw
    def _stored_payload(self, branch: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.crypto.encrypt_payload(payload, branch, kind) if self.crypto else payload
    def _open_payload(self, branch: str, kind: str, stored: dict[str, Any]) -> dict[str, Any]:
        if self.crypto and "__enc__" in stored:
            return self.crypto.decrypt_payload(stored, branch, kind)
        return stored
    def append(self, branch: str, kind: str, payload: dict[str, Any], *, parent_event: int | None = None, mono_ns: int | None = None) -> int:
        with self._append_lock:
            return self._append_locked(branch, kind, payload,
                                       parent_event=parent_event, mono_ns=mono_ns)

    def _append_locked(self, branch: str, kind: str, payload: dict[str, Any], *, parent_event: int | None = None, mono_ns: int | None = None) -> int:
        # Branches inherit their prefix logically using parent_event, while each
        # new branch has its own immutable hash chain rooted in genesis.
        # The hash chain covers the STORED payload form, so it verifies
        # identically on encrypted timelines.
        row = self.db.execute("SELECT hash FROM events WHERE branch=? ORDER BY id DESC LIMIT 1", (branch,)).fetchone()
        previous = row["hash"] if row else GENESIS
        stamp = mono_ns if mono_ns is not None else time.monotonic_ns()
        stored_payload = self._stored_payload(branch, kind, payload)
        body = {"branch": branch, "parent_event": parent_event, "kind": kind, "mono_ns": stamp, "payload": stored_payload, "prev_hash": previous}
        digest = hashlib.sha256(canonical(body)).hexdigest()
        cur = self.db.execute("INSERT INTO events(branch,parent_event,kind,mono_ns,payload,prev_hash,hash) VALUES(?,?,?,?,?,?,?)", (branch,parent_event,kind,stamp,canonical(stored_payload).decode(),previous,digest))
        self.db.commit(); return int(cur.lastrowid)
    def event(self, event_id: int) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not row: raise KeyError(event_id)
        out = dict(row); out["payload"] = self._open_payload(out["branch"], out["kind"], json.loads(out["payload"])); return out
    def _events_stored(self, branch: str, through: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events WHERE branch=?" + (" AND id<=?" if through else "") + " ORDER BY id"
        rows = self.db.execute(sql, (branch, through) if through else (branch,)).fetchall()
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]
    def events(self, branch: str, through: int | None = None) -> list[dict[str, Any]]:
        return [{**e, "payload": self._open_payload(e["branch"], e["kind"], e["payload"])}
                for e in self._events_stored(branch, through)]
    def replay_events(self, branch: str, through: int | None = None) -> list[dict[str, Any]]:
        """Return a branch's inherited prefix followed by its local immutable tail.

        `through` is a global event id on the branch's logical timeline.
        On a forked branch the inherited events live on the parent with ids
        at or below the fork checkpoint, while the branch's own first event
        (the fork event) has a larger id — so the fork event must be located
        WITHOUT the through filter. Filtering first hid the fork event
        whenever through <= checkpoint and the whole prefix vanished (M2).
        """
        all_local = self.events(branch)
        fork = next((e for e in all_local if e["kind"] == "fork"), None)
        if not fork:
            return [e for e in all_local if through is None or e["id"] <= through]
        parent = fork["payload"]["parent_branch"]; checkpoint = fork["payload"]["checkpoint"]
        if through is not None and through < fork["id"]:
            # The requested point sits in (or before) the inherited prefix;
            # the branch's logical content there is the parent's, capped at
            # the checkpoint this fork was taken from.
            return self.replay_events(parent, min(through, checkpoint))
        local = [e for e in all_local if through is None or e["id"] <= through]
        return self.replay_events(parent, checkpoint) + local
    def verify(self, branch: str) -> bool:
        previous = GENESIS
        for e in self._events_stored(branch):
            body = {k:e[k] for k in ("branch","parent_event","kind","mono_ns","payload","prev_hash")}
            if e["prev_hash"] != previous or hashlib.sha256(canonical(body)).hexdigest() != e["hash"]: return False
            previous = e["hash"]
        return True
    def fork(self, parent_branch: str, checkpoint: int, new_branch: str, edit: dict[str, Any] | None = None) -> int:
        if self.events(new_branch): raise ValueError("branch already exists")
        return self.append(new_branch, "fork", {"parent_branch":parent_branch,"checkpoint":checkpoint,"edit":edit}, parent_event=checkpoint)
    def typed_edit(self, branch: str, kind: str, target: str, value: Any, **extra: Any) -> int:
        if kind not in {"clamp", "explain", "pin"}: raise ValueError("unsupported edit kind")
        return self.append(branch, "edit", {"edit_kind":kind,"target":target,"value":value,**extra})
