from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENDOR_TXT = ROOT / "vendor.txt"
TEXTUAL_VERSION_PATCH = (
    ROOT / "tools" / "vendoring" / "patches" / "textual-version.patch"
)
SETUP_PY = ROOT / "setup.py"


def _read_vendor_txt_version() -> str:
    match = re.search(
        r"^textual==([^\s]+)$",
        VENDOR_TXT.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise SystemExit(f"missing textual pin in {VENDOR_TXT}")
    return match.group(1)


def _read_patch_version() -> str:
    match = re.search(
        r'^\+__version__ = "([^"]+)"$',
        TEXTUAL_VERSION_PATCH.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise SystemExit(
            f"missing textual __version__ patch in {TEXTUAL_VERSION_PATCH}"
        )
    return match.group(1)


def _read_setup_py_test_pin() -> str:
    match = re.search(
        r'^\s*"textual==([^"]+)",\s*$',
        SETUP_PY.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise SystemExit(f"missing textual test pin in {SETUP_PY}")
    return match.group(1)


def main() -> int:
    vendor_txt_version = _read_vendor_txt_version()
    patch_version = _read_patch_version()
    setup_py_version = _read_setup_py_test_pin()
    if vendor_txt_version != patch_version:
        print(
            "textual version mismatch:"
            f" vendor.txt has {vendor_txt_version},"
            f" textual-version.patch has {patch_version}",
            file=sys.stderr,
        )
        return 1
    if vendor_txt_version != setup_py_version:
        print(
            "textual version mismatch:"
            f" vendor.txt has {vendor_txt_version},"
            f" setup.py has {setup_py_version}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
