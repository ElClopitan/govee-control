"""Test helpers for hermetic test isolation.

Also installs a Popen guard that raises AssertionError if any test tries to
spawn a real process without mocking it. Tests that need Popen should use
mock.patch("subprocess.Popen") which overrides this guard inside the with
block and restores it afterwards.

subprocess.run is allowed because it internally calls Popen; guarding Popen
would break subprocess.run. The guard checks the call stack to distinguish
direct Popen calls from Popen calls made by subprocess.run.

Also installs a socket guard that raises AssertionError if any test tries to
send to or connect to a non-loopback address. Tests that need real network
should mock govee functions instead.
"""

import inspect
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

# Install Popen guard (safe to import twice)
_original_popen = subprocess.Popen


def _is_called_from_subprocess_run():
    """Check if Popen is being called from subprocess.run."""
    frame = inspect.currentframe().f_back
    while frame:
        if frame.f_code.co_filename.endswith("subprocess.py"):
            # We're inside the subprocess module
            # Only allow if called from subprocess.run
            return frame.f_code.co_name == "run"
        frame = frame.f_back
    return False


class _GuardedPopen(_original_popen):
    """A Popen replacement that raises AssertionError when instantiated directly."""

    def __init__(self, *args, **kwargs):
        if not _is_called_from_subprocess_run():
            # Called directly from test code - not allowed
            raise AssertionError("real subprocess.Popen in a test: mock it")
        # Called from subprocess.run - allowed, call the real Popen
        super().__init__(*args, **kwargs)


if subprocess.Popen is not _GuardedPopen:
    subprocess.Popen = _GuardedPopen


# Install socket guard (safe to import twice)
_original_sendto = socket.socket.sendto
_original_connect = socket.socket.connect


def _is_loopback(host):
    """Check if a host is a loopback address."""
    return host in ("127.0.0.1", "::1", "localhost")


def _guarded_sendto(self, data, addr):
    """Guarded sendto that raises for non-loopback addresses."""
    host = addr[0]
    if not _is_loopback(host):
        raise AssertionError("real network in a test: mock govee")
    return _original_sendto(self, data, addr)


def _guarded_connect(self, addr):
    """Guarded connect that raises for non-loopback addresses."""
    host = addr[0]
    if not _is_loopback(host):
        raise AssertionError("real network in a test: mock govee")
    return _original_connect(self, addr)


if socket.socket.sendto is not _guarded_sendto:
    socket.socket.sendto = _guarded_sendto
if socket.socket.connect is not _guarded_connect:
    socket.socket.connect = _guarded_connect


def bounded_clock(step=0.1, limit=1000.0):
    """Return a fake clock function that raises AssertionError past `limit` seconds.

    Each call returns the current fake time and advances by `step`.
    Once the time passes `limit`, raises AssertionError to catch infinite loops.
    """
    state = {"time": 0.0}

    def clock():
        t = state["time"]
        state["time"] = t + step
        if state["time"] > limit:
            raise AssertionError(
                "run() did not terminate (fake clock passed %s s)" % limit
            )
        return t

    return clock


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

    def set_mode(self, mode):
        """Set the mode for tests that need it."""
        import arbiter
        arbiter.set_mode(mode)
