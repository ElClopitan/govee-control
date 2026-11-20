"""Test suite initialization.

Replaces subprocess.Popen with a guard that raises AssertionError if any test
tries to spawn a real process without mocking it. Tests that need Popen should
use mock.patch("subprocess.Popen") which overrides this guard inside the with
block and restores it afterwards.

subprocess.run is allowed because it internally calls Popen; guarding Popen
would break subprocess.run. The guard checks the call stack to distinguish
direct Popen calls from Popen calls made by subprocess.run.
"""

import inspect
import subprocess

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


subprocess.Popen = _GuardedPopen
