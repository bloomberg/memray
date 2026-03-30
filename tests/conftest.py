import importlib
import pkgutil
import socket
import sys

import pytest
import pytest_textual_snapshot as _pytest_textual_snapshot
from packaging import version

# Patch textual imports to avoid pytest-textual-snapshot loading it from the environment
import memray._vendor.textual as _vendored_textual
from memray._vendor.textual.app import App as _vendored_textual_app

sys.modules["textual"] = _vendored_textual
_pytest_textual_snapshot.App = _vendored_textual_app


def _alias_vendored_textual_submodule(modname: str) -> None:
    try:
        mod = importlib.import_module(modname)
    except Exception:
        return
    bare_name = modname.replace("memray._vendor.", "", 1)
    sys.modules[bare_name] = mod


# Also inject commonly used submodules that pytest-textual-snapshot accesses
for _importer, _modname, _ispkg in pkgutil.walk_packages(
    _vendored_textual.__path__,
    prefix="memray._vendor.textual.",
):
    _alias_vendored_textual_submodule(_modname)


SNAPSHOT_MINIMUM_VERSIONS = {
    "pytest-textual-snapshot": "1.1.0",
}

VENDORED_TEXTUAL_VERSION = _vendored_textual.__version__


@pytest.fixture
def free_port():
    s = socket.socket()
    s.bind(("", 0))
    port_number = s.getsockname()[1]
    s.close()
    return port_number


def _snapshot_skip_reason():
    if sys.version_info < (3, 9):
        return "snapshot tests require Python >= 3.9"

    from importlib import metadata

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
        from importlib import metadata

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
