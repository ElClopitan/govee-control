"""Test runner with suite-wide state dir guard.

Run with: python -m tests
"""

import sys
import unittest

# Install suite-wide state dir guard before any tests run
import tests  # noqa: F401  triggers tests/__init__.py which installs the guard

# Run all tests
loader = unittest.TestLoader()
suite = loader.discover("tests")
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
