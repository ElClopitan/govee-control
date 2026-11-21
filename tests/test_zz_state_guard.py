"""Suite-wide guard: fail if any test wrote to the repo's real state/ dir.

This test runs last (named test_zz_ so it sorts after all other tests).
It compares a fresh snapshot of the repo's real state/ directory against
the snapshot taken at helpers.py import time. If the snapshots differ
(new, removed, or changed files), the test fails with a clear message.

The preventive measure is in tests/helpers.py which redirects all state
path constants to a session tempdir at import time. This test catches
any writes that slip through.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import helpers


class TestStateDirGuard(unittest.TestCase):
    """Verify no test wrote to the repo's real state/ dir."""

    def test_state_dir_not_written(self):
        """Fail if the repo's real state/ dir differs from the import-time snapshot."""
        current_snapshot = helpers._snapshot_state_dir(helpers.REAL_STATE_DIR)
        original_snapshot = helpers.REAL_STATE_SNAPSHOT

        # Both None: no state/ dir at either time - good
        if current_snapshot is None and original_snapshot is None:
            return

        # Original was None but current exists: state/ was created
        if original_snapshot is None and current_snapshot is not None:
            file_list = ", ".join(current_snapshot.keys())
            self.fail(
                f"Tests created the repo's real state/ dir with files: {file_list}. "
                f"State writes should be mocked or redirected to a temp dir."
            )

        # Current is None but original existed: state/ was deleted
        if original_snapshot is not None and current_snapshot is None:
            self.fail(
                f"Tests deleted the repo's real state/ dir (had files: "
                f"{', '.join(original_snapshot.keys())})."
            )

        # Both exist: compare
        added = set(current_snapshot.keys()) - set(original_snapshot.keys())
        removed = set(original_snapshot.keys()) - set(current_snapshot.keys())
        changed = []
        for name in set(current_snapshot.keys()) & set(original_snapshot.keys()):
            if current_snapshot[name] != original_snapshot[name]:
                changed.append(name)

        if added or removed or changed:
            parts = []
            if added:
                parts.append(f"added: {', '.join(sorted(added))}")
            if removed:
                parts.append(f"removed: {', '.join(sorted(removed))}")
            if changed:
                parts.append(f"changed: {', '.join(sorted(changed))}")
            self.fail(
                f"Tests modified the repo's real state/ dir ({'; '.join(parts)}). "
                f"State writes should be mocked or redirected to a temp dir."
            )


if __name__ == "__main__":
    unittest.main()
