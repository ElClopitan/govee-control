"""Test helpers for hermetic test isolation."""

import sys
import tempfile
from pathlib import Path
from unittest import mock


class StateDirMixin:
    """Mixin that provides a temporary state directory for tests.

    Patches arbiter.STATE_DIR, agent_signal.STATE_DIR, and agent_signal.LOCK_FILE
    to point to a temporary directory. agent_signal now uses arbiter.signal_file()
    for the signal path, so only arbiter.STATE_DIR needs patching for that.

    Also patches sys.stdin with a default that returns {} (isatty=True) so tests
    that call cmd_needs_input or cmd_clear don't block on real stdin. Tests that
    need specific stdin can override by patching sys.stdin themselves.
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

        self._signal_lock_patch = mock.patch.object(
            agent_signal, "LOCK_FILE", self.state_dir / "agent_signal.lock"
        )
        self._signal_lock_patch.start()
        self.addCleanup(self._signal_lock_patch.stop)

        # Default stdin: isatty=True so read_hook_input() returns {} immediately
        # without blocking. Tests that need stdin data override this.
        self._stdin_patch = mock.patch.object(
            sys, "stdin", mock.Mock(isatty=lambda: True)
        )
        self._stdin_patch.start()
        self.addCleanup(self._stdin_patch.stop)
