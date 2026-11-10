"""The Hermes plugin must work from its own directory alone."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class HermesPluginBundleTest(unittest.TestCase):
    def test_bundled_engine_matches_src(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "sync_hermes_plugin.py"), "--check"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_plugin_imports_without_repo_src(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / "melange"
            shutil.copytree(ROOT / "hermes-plugin", plugin,
                            ignore=shutil.ignore_patterns("__pycache__"))
            code = (
                "import importlib.util, sys;"
                f"spec = importlib.util.spec_from_file_location('melange_plugin', r'{plugin / '__init__.py'}');"
                "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod);"
                "assert len(mod.TOOLS) == 10;"
                f"assert all(r'{tmp}' in m.__file__ for n, m in sys.modules.items()"
                " if n.startswith('living_replay') and getattr(m, '__file__', None))"
            )
            result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                    text=True, cwd=tmp, env={"PATH": "/usr/bin:/bin"})
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
