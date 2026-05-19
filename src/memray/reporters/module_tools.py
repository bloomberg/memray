"""Utilities for extracting module names from file paths."""

import site
import sys
import sysconfig
from pathlib import Path
from typing import Dict
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


def _path_to_module(path: Path) -> str:
    if path.is_absolute():
        raise ValueError(f"Expected a relative path, got: {path}")

    if path.name == "__init__.py":
        path = path.parent
    elif path.suffix == ".py":
        path = path.with_suffix("")

    return ".".join(path.parts)


class ModuleResolver:
    """Resolve file paths to module names, caching results per file name.

    Holds the Python search path info and a cache so that the (relatively
    expensive) classification is only computed once per file name.
    """

    def __init__(self, path_info: Optional[PathInfo] = None) -> None:
        self._path_info: PathInfo = (
            path_info if path_info is not None else get_python_path_info()
        )
        self._cache: Dict[str, Tuple[str, str]] = {}

    def extract_module_name_and_type(self, filename: str) -> Tuple[str, str]:
        """Extract Python module name and type from a file path.

        Returns:
            tuple: (module_name, module_type) where module_type is one of:
                   'stdlib', 'site-packages', 'project', or 'unknown'
        """
        try:
            return self._cache[filename]
        except KeyError:
            result = self._extract_module_name_and_type_impl(filename)
            self._cache[filename] = result
            return result

    def _extract_module_name_and_type_impl(self, filename: str) -> Tuple[str, str]:
        if not filename:
            return ("unknown", "unknown")

        if filename.startswith("<frozen "):
            return (filename[len("<frozen ") : -1], "stdlib")

        file_path = Path(filename)

        for site_pkg in self._path_info["site_packages"]:
            if _is_relative_to(file_path, site_pkg):
                return (
                    _path_to_module(file_path.relative_to(site_pkg)),
                    "site-packages",
                )

        stdlib = self._path_info["stdlib"]
        if stdlib and _is_relative_to(file_path, stdlib):
            return (_path_to_module(file_path.relative_to(stdlib)), "stdlib")

        for path_entry in self._path_info["sys_path"]:
            if _is_relative_to(file_path, path_entry):
                return (_path_to_module(file_path.relative_to(path_entry)), "project")

        # Fallback: use just the filename, not the full absolute path
        return (_path_to_module(Path(file_path.name)), "unknown")

    def get_module_for_stack(self, stack: Iterable[Tuple[str, str, int]]) -> str:
        """Find the top-level module of the closest non-stdlib frame in a stack.

        Walks frames from leaf to root, returning the first non-stdlib module's
        top-level package name. Returns "<root>" if we reach Memray's own calls
        into the user's code, or if all frames are stdlib or the stack's empty.
        """
        for frame in stack:
            module_name, module_type = self.extract_module_name_and_type(frame[1])
            if module_type != "stdlib":
                top_level = module_name.split(".")[0]
                if top_level == "memray":
                    return "<root>"
                return top_level
        return "<root>"
