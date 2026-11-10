"""At-rest encryption for timelines (Build 3, gate B3-G3).

Design (from the README's key design): a fresh 256-bit data-encryption
key (DEK) per timeline; every blob and every event payload is encrypted
with AES-256-GCM under the DEK with a distinct random nonce and the
object's identity as AAD. The DEK itself is wrapped by a key-encryption
key held by a KeyProvider and stored, wrapped only, in `key.json` inside
the timeline directory. The master key is supplied out-of-band (env var
or a key file) and is never written into the timeline.

Opening an encrypted timeline with the wrong master key fails at unwrap
time — a clear TimelineKeyError, never garbage plaintext. Hash chains
are computed over the stored (ciphertext-envelope) representation, so
verify() works identically on encrypted timelines.
"""
from __future__ import annotations
import base64, hashlib, json, os
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class TimelineKeyError(Exception):
    """Raised when a timeline cannot be unlocked with the supplied key."""

class KeyProvider(Protocol):
    def wrap(self, dek: bytes) -> bytes: ...
    def unwrap(self, wrapped: bytes) -> bytes: ...

class LocalKeyProvider:
    """KEK from a 32-byte master key (base64 env var or a key file).
    Stands in for a KMS behind the same wrap/unwrap interface."""
    def __init__(self, master_key: bytes):
        if len(master_key) != 32: raise ValueError("master key must be 32 bytes")
        self._kek = AESGCM(master_key)
        self.key_id = hashlib.sha256(master_key).hexdigest()[:16]

    @classmethod
    def from_env(cls, var: str = "LIVING_REPLAY_KEY") -> "LocalKeyProvider":
        raw = os.environ.get(var)
        if not raw: raise TimelineKeyError(f"environment variable {var} is not set")
        return cls(base64.b64decode(raw))

    @classmethod
    def from_file(cls, path: str | Path) -> "LocalKeyProvider":
        return cls(base64.b64decode(Path(path).read_text().strip()))

    @staticmethod
    def generate() -> bytes:
        return AESGCM.generate_key(256)

    def wrap(self, dek: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._kek.encrypt(nonce, dek, b"living-replay-dek")

    def unwrap(self, wrapped: bytes) -> bytes:
        try:
            return self._kek.decrypt(wrapped[:12], wrapped[12:], b"living-replay-dek")
        except InvalidTag as e:
            raise TimelineKeyError("cannot unwrap timeline key: wrong master key") from e

class TimelineCrypto:
    """Per-timeline DEK holder: creates or unlocks key.json in the root."""
    def __init__(self, root: Path, provider: KeyProvider):
        self.provider = provider
        key_file = root / "key.json"
        if key_file.exists():
            meta = json.loads(key_file.read_text())
            if meta.get("kek_id") != getattr(provider, "key_id", None):
                raise TimelineKeyError("timeline was wrapped with a different master key")
            self.dek = provider.unwrap(base64.b64decode(meta["wrapped_dek"]))
        else:
            self.dek = AESGCM.generate_key(256)
            meta = {"version": 1, "algorithm": "AES-256-GCM",
                    "kek_id": getattr(provider, "key_id", None),
                    "wrapped_dek": base64.b64encode(provider.wrap(self.dek)).decode()}
            key_file.write_text(json.dumps(meta, indent=2))
        self._gcm = AESGCM(self.dek)

    def encrypt(self, data: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._gcm.encrypt(nonce, data, aad)

    def decrypt(self, data: bytes, aad: bytes) -> bytes:
        try:
            return self._gcm.decrypt(data[:12], data[12:], aad)
        except InvalidTag as e:
            raise TimelineKeyError("payload authentication failed (wrong key or tampered data)") from e

    def encrypt_payload(self, payload: dict, branch: str, kind: str) -> dict:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        sealed = self.encrypt(raw, f"event:{branch}:{kind}".encode())
        return {"__enc__": base64.b64encode(sealed).decode()}

    def decrypt_payload(self, stored: dict, branch: str, kind: str) -> dict:
        sealed = base64.b64decode(stored["__enc__"])
        raw = self.decrypt(sealed, f"event:{branch}:{kind}".encode())
        return json.loads(raw)
