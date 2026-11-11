# Draft contracts

These JSON Schema 2020-12 contracts describe the proposed offline checkpoint
milestone. They are not registered runtime formats. `chunked-aead-v1` is a
reserved design name whose cryptographic framing still needs implementation
review. The examples use invented IDs, digests, sizes and backend identifiers;
**they are not execution receipts or downloadable checkpoints**.

- [Checkpoint schema](checkpoint.schema.json) and [example](checkpoint.example.json).
- [Operation schema](operation.schema.json), [completed example](operation.completed.example.json)
  and [failed example](operation.failed.example.json).
- [Validator](validate_contracts.py): run with Python and `jsonschema>=4.10`.
  It validates draft schemas, examples, cross-references and rejection fixtures.
  It does not qualify a VM or verify nonexistent example artifact bytes.

```sh
python3 docs/executable-desktop/contracts/validate_contracts.py
```

Required semantic checks beyond JSON Schema:

1. Artifact IDs, disk node IDs and logical resource names are unique. Every
   machine/disk/backing reference resolves to an artifact. Shared role references
   are allowed when one backend container holds multiple state components.
2. Inventory exactly matches the qualified runtime's writable disks and declared
   immutable dependencies. Removing a disk from a manifest cannot make it valid.
3. Backend build, profile/configuration, firmware, CPU/device model, resource
   mapping and encrypted artifact format match the admitted qualification.
4. Actual lengths, digests, encryption tags, backing chains and filesystem
   isolation verify. Manifest validity alone is never sufficient.
5. The anchor belongs to the selected logical branch ancestry; hash and full
   prefix digest match. Checkpoint and journal cursors refer to the same paused
   cut. No newer checkpoint may replace a requested historical one.
6. A completed result's fields satisfy its operation kind. For example, checkpoint
   requires checkpoint ID and anchor; fork_restore requires child branch,
   session/runtime IDs and a restore-verification receipt. The common envelope
   schema is not a substitute for these kind-specific runtime checks.
   Stop recording requires checkpoint/anchor and a preservation receipt.
   Session/child-branch identities must agree between envelope and result;
   restore retries remain bound to the originally reserved checkpoint or the
   branch's latest verified stopped state. Cancellation updates its target
   operation, so there is no separate cancel kind.
7. The manifest digest is stored outside the manifest, in the catalog and
   completion event. Anchor frame precedes manifest publication. Neither embeds
   the digest of a later object that points back to it.

V1 is offline (`io_cursor=0`). Online replay/live continuation requires a new
qualified profile and versioned contract, not silently accepting more fields.
Host paths, launch commands, raw encryption keys and credentials are not allowed
in these public contracts. The supervisor resolves opaque identities locally.
