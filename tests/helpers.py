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

At import time, this module creates a session tempdir and redirects all
production state path constants (arbiter.STATE_DIR, agent_signal.STATE_DIR,
agent_signal.LOCK_FILE, music_sync.STATE_DIR, music_sync.PID_FILE,
music_sync.STOP_FLAG_FILE, music_sync.LOG_FILE) to paths inside it. It also
takes a snapshot of the real repo state/ dir so test_zz_state_guard.py can
detect if any test wrote to the real state/ dir.
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


# Session-wide state dir redirect: create one tempdir for the entire test
# session and redirect all production state path constants to it. This is
# done at import time so it applies to all tests automatically.
#
# We also take a snapshot of the real repo state/ dir so that
# test_zz_state_guard.py can detect if any test wrote to the real state/ dir.

import arbiter
import agent_signal
import music_sync

# Find the repo root (parent of tests/)
_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent
REAL_STATE_DIR = _REPO_ROOT / "state"


def _snapshot_state_dir(state_dir):
    """Take a snapshot of a state directory: {filename: (size, mtime_ns)}."""
    if not state_dir.exists():
        return None
    snapshot = {}
    for f in state_dir.iterdir():
        if f.is_file():
            stat = f.stat()
            snapshot[f.name] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


REAL_STATE_SNAPSHOT = _snapshot_state_dir(REAL_STATE_DIR)

# Create session tempdir
_SESSION_STATE_DIR = Path(tempfile.mkdtemp(prefix="govee-test-state-"))

# Redirect all state path constants to the session tempdir
arbiter.STATE_DIR = _SESSION_STATE_DIR
agent_signal.STATE_DIR = _SESSION_STATE_DIR
agent_signal.LOCK_FILE = _SESSION_STATE_DIR / "agent_signal.lock"
music_sync.STATE_DIR = _SESSION_STATE_DIR
music_sync.PID_FILE = _SESSION_STATE_DIR / "music_sync.pid"
music_sync.STOP_FLAG_FILE = _SESSION_STATE_DIR / "music_stop"
music_sync.LOG_FILE = _SESSION_STATE_DIR / "music_sync.log"


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

    Patches all module-level state path constants (arbiter.STATE_DIR,
    agent_signal.STATE_DIR, agent_signal.LOCK_FILE, music_sync.STATE_DIR,
    music_sync.PID_FILE, music_sync.STOP_FLAG_FILE, music_sync.LOG_FILE)
    to point to a temporary directory. This ensures tests don't write to
    the repo's real state/ dir.

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
        import music_sync

        # arbiter
        self._arbiter_patch = mock.patch.object(arbiter, "STATE_DIR", self.state_dir)
        self._arbiter_patch.start()
        self.addCleanup(self._arbiter_patch.stop)

        # agent_signal
        self._signal_state_patch = mock.patch.object(agent_signal, "STATE_DIR", self.state_dir)
        self._signal_state_patch.start()
        self.addCleanup(self._signal_state_patch.stop)

        self._signal_lock_patch = mock.patch.object(
            agent_signal, "LOCK_FILE", self.state_dir / "agent_signal.lock"
        )
        self._signal_lock_patch.start()
        self.addCleanup(self._signal_lock_patch.stop)

        # music_sync
        self._music_state_patch = mock.patch.object(music_sync, "STATE_DIR", self.state_dir)
        self._music_state_patch.start()
        self.addCleanup(self._music_state_patch.stop)

        self._music_pid_patch = mock.patch.object(
            music_sync, "PID_FILE", self.state_dir / "music_sync.pid"
        )
        self._music_pid_patch.start()
        self.addCleanup(self._music_pid_patch.stop)

        self._music_stop_patch = mock.patch.object(
            music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"
        )
        self._music_stop_patch.start()
        self.addCleanup(self._music_stop_patch.stop)

        self._music_log_patch = mock.patch.object(
            music_sync, "LOG_FILE", self.state_dir / "music_sync.log"
        )
        self._music_log_patch.start()
        self.addCleanup(self._music_log_patch.stop)

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
