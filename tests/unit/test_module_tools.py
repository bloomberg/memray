from pathlib import Path

import pytest

from memray.reporters.module_tools import ModuleResolver
from memray.reporters.module_tools import _path_to_module
from memray.reporters.module_tools import get_python_path_info


@pytest.fixture(scope="module")
def path_info():
    return get_python_path_info()


@pytest.fixture
def resolver(path_info):
    return ModuleResolver(path_info)


def test_path_info_has_expected_keys():
    info = get_python_path_info()
    assert "stdlib" in info
    assert "site_packages" in info
    assert "sys_path" in info


def test_path_info_stdlib_points_to_sysconfig_libdest():
    import sysconfig

    info = get_python_path_info()
    assert info["stdlib"] is not None
    assert info["stdlib"] == Path(sysconfig.get_config_var("LIBDEST"))


def test_path_info_site_packages_is_list_of_paths():
    info = get_python_path_info()
    assert isinstance(info["site_packages"], list)
    for p in info["site_packages"]:
        assert isinstance(p, Path)


def test_path_info_sys_path_is_list_of_paths():
    info = get_python_path_info()
    assert isinstance(info["sys_path"], list)
    for p in info["sys_path"]:
        assert isinstance(p, Path)


def test_path_info_includes_user_site_packages(tmp_path):
    import unittest.mock

    user_site = tmp_path / "user-site-packages"
    user_site.mkdir()
    with unittest.mock.patch("site.getusersitepackages", return_value=str(user_site)):
        info = get_python_path_info()
    assert Path(user_site) in info["site_packages"]


@pytest.mark.parametrize(
    "path, expected",
    [
        ("mymodule.py", "mymodule"),
        ("pandas/io/parsers.py", "pandas.io.parsers"),
        ("requests/__init__.py", "requests"),
        ("pkg/utils", "pkg.utils"),
        ("numpy/core/__init__.py", "numpy.core"),
    ],
)
def test_path_to_module(path, expected):
    assert _path_to_module(Path(path)) == expected


def test_extract_module_name_and_type_empty(resolver):
    name, mtype = resolver.extract_module_name_and_type("")
    assert name == "unknown"
    assert mtype == "unknown"


def test_extract_module_name_and_type_frozen(resolver):
    name, mtype = resolver.extract_module_name_and_type("<frozen importlib._bootstrap>")
    assert name == "importlib._bootstrap"
    assert mtype == "stdlib"


def test_extract_module_name_and_type_stdlib(resolver, path_info):
    stdlib_file = str(path_info["stdlib"] / "json" / "__init__.py")
    name, mtype = resolver.extract_module_name_and_type(stdlib_file)
    assert mtype == "stdlib"
    assert "json" in name


def test_extract_module_name_and_type_site_packages(resolver):
    name, mtype = resolver.extract_module_name_and_type(pytest.__file__)
    assert mtype == "site-packages"
    assert "pytest" in name


def test_extract_module_name_and_type_project(resolver):
    _, mtype = resolver.extract_module_name_and_type(__file__)
    assert mtype in ("project", "unknown")


def test_extract_module_name_and_type_unknown(resolver):
    name, mtype = resolver.extract_module_name_and_type(
        "/nonexistent/random/mymodule.py"
    )
    assert mtype == "unknown"
    assert name == "mymodule"


def test_extract_module_name_and_type_is_cached(resolver):
    # GIVEN / WHEN
    first = resolver.extract_module_name_and_type(pytest.__file__)
    second = resolver.extract_module_name_and_type(pytest.__file__)

    # THEN
    assert first == second
    assert resolver._cache[pytest.__file__] == first


def test_skips_stdlib_leaf_frame(resolver, path_info):
    # GIVEN
    stdlib_path = str(path_info["stdlib"] / "json" / "__init__.py")
    stack = [
        ("loads", stdlib_path, 346),
        ("safe_load", pytest.__file__, 10),
    ]

    # THEN
    assert resolver.get_module_for_stack(stack) == "pytest"


def test_skips_frozen_stdlib_frame(resolver):
    # GIVEN
    stack = [
        ("_find", "<frozen importlib._bootstrap>", 100),
        ("safe_load", pytest.__file__, 10),
    ]

    # THEN
    assert resolver.get_module_for_stack(stack) == "pytest"


def test_returns_non_stdlib_leaf_immediately(resolver, path_info):
    # GIVEN
    stdlib_path = str(path_info["stdlib"] / "json" / "__init__.py")
    stack = [
        ("safe_load", pytest.__file__, 10),
        ("loads", stdlib_path, 346),
    ]

    # THEN
    assert resolver.get_module_for_stack(stack) == "pytest"


def test_all_stdlib_returns_root(resolver, path_info):
    # GIVEN
    stdlib = path_info["stdlib"]
    stack = [
        ("loads", str(stdlib / "json" / "__init__.py"), 346),
        ("decode", str(stdlib / "json" / "decoder.py"), 337),
    ]

    # THEN
    assert resolver.get_module_for_stack(stack) == "<root>"


def test_empty_stack_returns_root(resolver):
    assert resolver.get_module_for_stack([]) == "<root>"


def _memray_frame_path(path_info):
    site_packages = path_info["site_packages"]
    if not site_packages:
        pytest.skip("No site-packages directory to anchor a memray path")
    return str(site_packages[0] / "memray" / "commands" / "run.py")


def test_memray_own_frames_return_root(resolver, path_info):
    # GIVEN
    stdlib_path = str(path_info["stdlib"] / "json" / "__init__.py")
    stack = [
        ("loads", stdlib_path, 346),
        ("_run_tracker", _memray_frame_path(path_info), 100),
    ]

    # THEN
    # memray's own driver frames must not be attributed as a module; they are
    # treated as the root boundary.
    assert resolver.get_module_for_stack(stack) == "<root>"


def test_memray_frames_do_not_shadow_user_frames(resolver, path_info):
    # GIVEN
    stack = [
        ("work", pytest.__file__, 10),
        ("_run_tracker", _memray_frame_path(path_info), 100),
    ]

    # THEN
    assert resolver.get_module_for_stack(stack) == "pytest"
