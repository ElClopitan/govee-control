"""Suite-wide guard: fail if any test wrote to the repo's real state/ dir.

This test runs last (named test_zz_ so it sorts after all other tests).
It checks that the repo's real state/ directory was not created or modified
by the test suite. If it was, the test fails with a clear message.

This complements the import-time patches in tests/__init__.py which redirect
state writes to a temp dir. This test catches any writes that slip through.
"""

import os
import unittest
from pathlib import Path


class TestStateDirGuard(unittest.TestCase):
    """Verify no test wrote to the repo's real state/ dir."""

    def test_state_dir_not_written(self):
        """Fail if the repo's real state/ dir exists and has files."""
        # Find the repo root (parent of tests/)
        tests_dir = Path(__file__).parent
        repo_root = tests_dir.parent
        state_dir = repo_root / "state"

        if not state_dir.exists():
            # No state/ dir - good
            return

        # Check if state/ has any files (not just the directory)
        files = list(state_dir.iterdir())
        if not files:
            # Empty state/ dir - probably pre-existing, not written by tests
            return

        # state/ has files - this is bad
        file_list = ", ".join(f.name for f in files)
        self.fail(
            f"Tests wrote to the repo's real state/ dir: {file_list}. "
            f"State writes should be mocked or redirected to a temp dir."
        )


if __name__ == "__main__":
    unittest.main()
