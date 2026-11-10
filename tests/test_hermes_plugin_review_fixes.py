"""Regression coverage for the Hermes catalog review requirements."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load_plugin():
    path = ROOT / "hermes-plugin" / "__init__.py"
    spec = importlib.util.spec_from_file_location("melange_review_plugin", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HookContext:
    def __init__(self):
        self.hooks = {}
        self.tools = []

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_tool(self, **registration):
        self.tools.append(registration)


class HermesPluginReviewFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = load_plugin()

    def test_recording_tool_requests_owner_approval_with_exact_command(self):
        ctx = HookContext()
        self.plugin.register(ctx)

        self.assertEqual(set(ctx.hooks), {"pre_tool_call"})
        self.assertEqual(
            ctx.hooks["pre_tool_call"](
                tool_name="melange_record",
                args={"command": "printf 'synthetic recording'"},
                task_id="synthetic-task",
            ),
            {"action": "approve", "message": "printf 'synthetic recording'"},
        )
        self.assertIsNone(
            ctx.hooks["pre_tool_call"](
                tool_name="melange_screen",
                args={"recording": "demo"},
            )
        )

    def test_recording_limits_are_enforced_before_capture(self):
        for field, value in (
            ("timeout", self.plugin.MAX_TIMEOUT + 1),
            ("timeout", self.plugin.MIN_TIMEOUT / 2),
            ("rows", self.plugin.MAX_ROWS + 1),
            ("rows", self.plugin.MIN_ROWS - 1),
            ("cols", self.plugin.MAX_COLS + 1),
            ("cols", self.plugin.MIN_COLS - 1),
        ):
            with self.subTest(field=field):
                result = json.loads(
                    self.plugin.melange_record({"command": "true", field: value})
                )
                self.assertFalse(result["success"])
                self.assertIn(field, result["error"])

    def test_recording_rejects_non_string_commands(self):
        result = json.loads(self.plugin.melange_record({"command": ["printf", "synthetic"]}))
        self.assertFalse(result["success"])
        self.assertIn("non-empty string", result["error"])


if __name__ == "__main__":
    unittest.main()
