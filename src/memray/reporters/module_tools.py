"""Utilities for extracting module names from file paths."""

import site
import sys
import sysconfig
from pathlib import Path
from typing import Iterable
from typing import List
from typing import Optional
from typing import Tuple

from typing_extensions import TypedDict


class PathInfo(TypedDict):
    stdlib: Optional[Path]
    site_packages: List[Path]
    sys_path: List[Path]


def get_python_path_info() -> PathInfo:
    """Get information about Python's search paths.

    Returns:
        dict: Dictionary containing stdlib path, site-packages paths, and sys.path entries.
    """
    libdest = sysconfig.get_config_var("LIBDEST")
    stdlib: Optional[Path] = Path(libdest) if libdest else None

    # Get site-packages directories
    site_packages: List[Path] = [Path(p) for p in site.getsitepackages()]

    # Get user site-packages
    user_site = site.getusersitepackages()
    if Path(user_site).exists():
        site_packages.append(Path(user_site))

    return {
        "stdlib": stdlib,
        "site_packages": site_packages,
        "sys_path": [Path(p) for p in sys.path if p],
    }


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def extract_module_name_and_type(filename: str, path_info: PathInfo) -> Tuple[str, str]:
    """Extract Python module name and type from file path.

    Returns:
        tuple: (module_name, module_type) where module_type is one of:
               'stdlib', 'site-packages', 'project', or 'unknown'
    """
    if not filename:
        return ("unknown", "unknown")

    if filename.startswith("<frozen "):
        return (filename[len("<frozen ") : -1], "stdlib")

    file_path = Path(filename)

    for site_pkg in path_info["site_packages"]:
        if _is_relative_to(file_path, site_pkg):
            return (_path_to_module(file_path.relative_to(site_pkg)), "site-packages")

    if path_info["stdlib"] and _is_relative_to(file_path, path_info["stdlib"]):
        return (_path_to_module(file_path.relative_to(path_info["stdlib"])), "stdlib")

    for path_entry in path_info["sys_path"]:
        if _is_relative_to(file_path, path_entry):
            return (_path_to_module(file_path.relative_to(path_entry)), "project")

    # Fallback: use just the filename, not the full absolute path
    return (_path_to_module(Path(file_path.name)), "unknown")


def _path_to_module(path: Path) -> str:
    if path.is_absolute():
        raise ValueError(f"Expected a relative path, got: {path}")

    if path.name == "__init__.py":
        path = path.parent
    elif path.suffix == ".py":
        path = path.with_suffix("")

    return ".".join(path.parts)


def get_module_for_stack(
    stack: Iterable[Tuple[str, str, int]],
    path_info: PathInfo,
) -> str:
    """Find the top-level module of the closest non-stdlib frame in a stack.

    Walks frames from leaf to root, returning the first non-stdlib module's
    top-level package name. Returns "__main__" if every frame is stdlib
    or the stack is empty.
    """
    for frame in stack:
        module_name, module_type = extract_module_name_and_type(frame[1], path_info)
        if module_type != "stdlib":
            return module_name.split(".")[0]
    return "__main__"
