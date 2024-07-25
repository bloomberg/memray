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


if sys.version_info < (3, 8):
    # Ignore unused Textual snapshots on Python 3.7
    def pytest_configure(config):
        config.option.warn_unused_snapshots = True
