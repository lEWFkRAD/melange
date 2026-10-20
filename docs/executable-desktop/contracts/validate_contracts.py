"""Validate design examples only; this does not qualify an executable runtime."""

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checkpoint_references(document):
    artifacts = [item["id"] for item in document["artifacts"]]
    require(len(artifacts) == len(set(artifacts)), "duplicate artifact ID")
    nodes = [disk["node_id"] for disk in document["disks"]]
    require(len(nodes) == len(set(nodes)), "duplicate disk node")
    names = [item["name"] for item in document["resource_bindings"]]
    require(len(names) == len(set(names)), "duplicate resource name")
    disk_bindings = {item["name"] for item in document["resource_bindings"] if item["kind"] == "disk"}
    require(set(nodes) == disk_bindings, "disk resource inventory mismatch")
    references = list(document["machine_state"].values())
    for disk in document["disks"]:
        references.append(disk["snapshot_artifact"])
        references.extend(disk["backing_artifacts"])
    require(set(references) <= set(artifacts), "unresolved artifact reference")


def operation_result(document):
    if document["state"] != "completed":
        return
    required = {
        "start": {"session_id", "runtime_id"},
        "checkpoint": {"checkpoint_id", "anchor"},
        "stop_recording": {"session_id", "checkpoint_id", "anchor", "verification_receipt_id"},
        "fork_restore": {"child_branch", "session_id", "runtime_id", "verification_receipt_id"},
        "restore": {"session_id", "runtime_id", "verification_receipt_id"},
        "continue": {"session_id", "runtime_id", "live_frame_path"},
        "input": {"input_id"},
    }[document["kind"]]
    require(required <= document["result"].keys(), "missing operation-kind result")
    result = document["result"]
    if "session_id" in result:
        require(result["session_id"] == document["session_id"], "session identity mismatch")
    if "child_branch" in result:
        require(result["child_branch"] == document["branch"], "branch identity mismatch")
    if "live_frame_path" in result:
        require(result["live_frame_path"] == f'/api/runtime/v1/sessions/{document["session_id"]}/frames', "live frame session mismatch")
    if document["kind"] in ("checkpoint", "stop_recording"):
        require(result["anchor"]["branch"] == document["branch"], "checkpoint branch mismatch")


def main():
    schemas = {name: read(name + ".schema.json") for name in ("checkpoint", "operation")}
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    validators = {name: Draft202012Validator(schema, format_checker=FormatChecker()) for name, schema in schemas.items()}

    def validate(kind, document):
        validators[kind].validate(document)
        (checkpoint_references if kind == "checkpoint" else operation_result)(document)

    checkpoint = read("checkpoint.example.json")
    completed = read("operation.completed.example.json")
    failed = read("operation.failed.example.json")
    for kind, document in (("checkpoint", checkpoint), ("operation", completed), ("operation", failed)):
        validate(kind, document)
    require(completed["result"]["checkpoint_id"] == checkpoint["checkpoint_id"], "example checkpoint mismatch")
    require(completed["result"]["anchor"] == checkpoint["anchor"], "example anchor mismatch")

    cases = []

    def reject(name, kind, base, mutate):
        document = copy.deepcopy(base)
        mutate(document)
        try:
            validate(kind, document)
        except (ValidationError, ValueError):
            cases.append(name)
            return
        raise RuntimeError("Invalid design fixture accepted: " + name)

    reject("unknown version", "checkpoint", checkpoint, lambda d: d.update(schema_version="2.0"))
    reject("host launch command", "checkpoint", checkpoint, lambda d: d.update(command="run something"))
    reject("missing machine state", "checkpoint", checkpoint, lambda d: d.pop("machine_state"))
    reject("invalid digest", "checkpoint", checkpoint, lambda d: d["anchor"].update(event_hash="bad"))
    reject("invalid UUID", "checkpoint", checkpoint, lambda d: d.update(checkpoint_id="bad"))
    reject("live I/O in offline profile", "checkpoint", checkpoint, lambda d: d["barrier"].update(io_mode="live"))
    reject("unresolved input", "checkpoint", checkpoint, lambda d: d["barrier"].update(unresolved_inputs=1))
    reject("missing referenced disk artifact", "checkpoint", checkpoint, lambda d: d["artifacts"].pop())
    reject("duplicate artifact", "checkpoint", checkpoint, lambda d: d["artifacts"].append(d["artifacts"][0]))
    reject("missing disk binding", "checkpoint", checkpoint, lambda d: d["resource_bindings"].pop(0))
    reject("completed without result", "operation", completed, lambda d: d.update(result=None))
    reject("completed with error", "operation", completed, lambda d: d.update(error=failed["error"]))
    reject("failed without error", "operation", failed, lambda d: d.update(error=None))
    reject("queued with result", "operation", completed, lambda d: d.update(state="queued"))
    reject("missing checkpoint result anchor", "operation", completed, lambda d: d["result"].pop("anchor"))
    reject("negative revision", "operation", completed, lambda d: d.update(revision=-1))
    reject("stop without preservation receipt", "operation", completed, lambda d: d.update(kind="stop_recording"))
    reject("conflicting session IDs", "operation", completed, lambda d: d["result"].update(session_id="88888888-8888-4888-8888-888888888888"))
    reject("conflicting child branch", "operation", completed, lambda d: d["result"].update(child_branch="another-branch"))
    reject("conflicting checkpoint branch", "operation", completed, lambda d: d["result"]["anchor"].update(branch="another-branch"))
    print(f"Design contracts: 2 schemas, 3 examples, {len(cases)} rejection cases passed.")
    print("No VM restored; example artifacts are illustrative and unverified.")


if __name__ == "__main__":
    main()
