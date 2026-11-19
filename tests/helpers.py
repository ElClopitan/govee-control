"""Test helpers for hermetic test isolation."""

import tempfile
from pathlib import Path
from unittest import mock


class StateDirMixin:
    """Mixin that provides a temporary state directory for tests.

    Patches arbiter.STATE_DIR, agent_signal.STATE_DIR, agent_signal.SAVED_STATE_FILE,
    and agent_signal.LOCK_FILE to point to a temporary directory.
    """

    def setUp(self):
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_dir = Path(self._tmpdir.name)

        import arbiter
        import agent_signal

        self._arbiter_patch = mock.patch.object(arbiter, "STATE_DIR", self.state_dir)
        self._arbiter_patch.start()
        self.addCleanup(self._arbiter_patch.stop)

        self._signal_state_patch = mock.patch.object(agent_signal, "STATE_DIR", self.state_dir)
        self._signal_state_patch.start()
        self.addCleanup(self._signal_state_patch.stop)

        self._signal_saved_patch = mock.patch.object(
            agent_signal, "SAVED_STATE_FILE", self.state_dir / "saved_state.json"
        )
        self._signal_saved_patch.start()
        self.addCleanup(self._signal_saved_patch.stop)

        self._signal_lock_patch = mock.patch.object(
            agent_signal, "LOCK_FILE", self.state_dir / "agent_signal.lock"
        )
        self._signal_lock_patch.start()
        self.addCleanup(self._signal_lock_patch.stop)
