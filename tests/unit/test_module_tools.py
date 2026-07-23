from pathlib import Path

import pytest

from memray.reporters.module_tools import _path_to_module
from memray.reporters.module_tools import extract_module_name_and_type
from memray.reporters.module_tools import get_module_for_stack
from memray.reporters.module_tools import get_python_path_info


@pytest.fixture(scope="module")
def path_info():
    return get_python_path_info()


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


def test_extract_module_name_and_type_empty(path_info):
    name, mtype = extract_module_name_and_type("", path_info)
    assert name == "unknown"
    assert mtype == "unknown"


def test_extract_module_name_and_type_frozen(path_info):
    name, mtype = extract_module_name_and_type(
        "<frozen importlib._bootstrap>", path_info
    )
    assert name == "importlib._bootstrap"
    assert mtype == "stdlib"


def test_extract_module_name_and_type_stdlib(path_info):
    stdlib_file = str(path_info["stdlib"] / "json" / "__init__.py")
    name, mtype = extract_module_name_and_type(stdlib_file, path_info)
    assert mtype == "stdlib"
    assert "json" in name


def test_extract_module_name_and_type_site_packages(path_info):
    name, mtype = extract_module_name_and_type(pytest.__file__, path_info)
    assert mtype == "site-packages"
    assert "pytest" in name


def test_extract_module_name_and_type_project(path_info):
    _, mtype = extract_module_name_and_type(__file__, path_info)
    assert mtype in ("project", "unknown")


def test_extract_module_name_and_type_unknown(path_info):
    name, mtype = extract_module_name_and_type(
        "/nonexistent/random/mymodule.py", path_info
    )
    assert mtype == "unknown"
    assert name == "mymodule"


def test_skips_stdlib_leaf_frame(path_info):
    # GIVEN
    stdlib_path = str(path_info["stdlib"] / "json" / "__init__.py")
    stack = [
        ("loads", stdlib_path, 346),
        ("safe_load", pytest.__file__, 10),
    ]

    # THEN
    assert get_module_for_stack(stack, path_info) == "pytest"


def test_skips_frozen_stdlib_frame(path_info):
    # GIVEN
    stack = [
        ("_find", "<frozen importlib._bootstrap>", 100),
        ("safe_load", pytest.__file__, 10),
    ]

    # THEN
    assert get_module_for_stack(stack, path_info) == "pytest"


def test_returns_non_stdlib_leaf_immediately(path_info):
    # GIVEN
    stdlib_path = str(path_info["stdlib"] / "json" / "__init__.py")
    stack = [
        ("safe_load", pytest.__file__, 10),
        ("loads", stdlib_path, 346),
    ]

    # THEN
    assert get_module_for_stack(stack, path_info) == "pytest"


def test_all_stdlib_returns_main(path_info):
    # GIVEN
    stdlib = path_info["stdlib"]
    stack = [
        ("loads", str(stdlib / "json" / "__init__.py"), 346),
        ("decode", str(stdlib / "json" / "decoder.py"), 337),
    ]

    # THEN
    assert get_module_for_stack(stack, path_info) == "<root>"


def test_empty_stack_returns_main(path_info):
    assert get_module_for_stack([], path_info) == "<root>"
