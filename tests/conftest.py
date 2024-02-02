import socket
import sys

import pytest


@pytest.fixture
def free_port():
    s = socket.socket()
    s.bind(("", 0))
    port_number = s.getsockname()[1]
    s.close()
    return port_number


def pytest_configure(config):
    # Several of the tree reporter tests require Textual 0.48, which does not
    # support Python 3.7, but skipping those tests causes the test suite to
    # fail due to unused snapshots. Override the configuration for Python 3.7
    # so that unused snapshots are a warning, not an error.
    if sys.version_info < (3, 8):
        config.option.warn_unused_snapshots = True
