import socket
import sys

import pytest
from packaging import version

SNAPSHOT_MINIMUM_VERSIONS = {
    "textual": "2.0.0",
    "pytest-textual-snapshot": "1.0",
}


@pytest.fixture
def free_port():
    s = socket.socket()
    s.bind(("", 0))
    port_number = s.getsockname()[1]
    s.close()
    return port_number


def _snapshot_skip_reason():
    if sys.version_info < (3, 8):
        # Every version available for 3.7 is too old
        return f"snapshot tests require textual>={SNAPSHOT_MINIMUM_VERSIONS['textual']}"

    from importlib import metadata  # Added in 3.8

    for lib, min_ver in SNAPSHOT_MINIMUM_VERSIONS.items():
        try:
            ver = version.parse(metadata.version(lib))
        except ImportError:
            return f"snapshot tests require {lib} but it is not installed"

        if ver < version.parse(min_ver):
            return f"snapshot tests require {lib}>={min_ver} but {ver} is installed"

    return None


def pytest_configure(config):
    if config.option.update_snapshots:
        from importlib import metadata  # Added in 3.8

        for lib, min_ver in SNAPSHOT_MINIMUM_VERSIONS.items():
            ver = version.parse(metadata.version(lib))
            if ver != version.parse(min_ver):
                pytest.exit(
                    f"snapshots must be generated with {lib}=={min_ver}"
                    f" or SNAPSHOT_MINIMUM_VERSIONS must be updated to {ver}"
                    f" in {__file__}"
                )
        return

    reason = _snapshot_skip_reason()
    if reason:
        config.issue_config_time_warning(UserWarning(reason), stacklevel=2)
        config.option.warn_unused_snapshots = True


def pytest_collection_modifyitems(config, items):
    reason = _snapshot_skip_reason()
    if reason:
        for item in items:
            if "snap_compare" in item.fixturenames:
                item.add_marker(pytest.mark.skip(reason=reason))
