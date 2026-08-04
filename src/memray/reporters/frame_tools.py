"""Tools for processing and filtering stack frames."""

import contextlib
import functools
import linecache
import os
import re
from typing import Tuple

Symbol = str
File = str
Lineno = int
StackFrame = Tuple[Symbol, File, Lineno]

RE_CPYTHON_PATHS = re.compile(r"(Include|Objects|Modules|Python|cpython).*\.[c|h]$")

SYMBOL_IGNORELIST = {
    "PyObject_Call",
    "call_function",
    "classmethoddescr_call",
    "cmpwrapper_call",
    "do_call_core",
    "fast_function",
    "function_call",
    "function_code_fastcall",
    "instance_call",
    "instancemethod_call",
    "instancemethod_call",
    "methoddescr_call",
    "proxy_call",
    "slot_tp_call",
    "trace_call_function",
    "type_call",
    "weakref_call",
    "wrap_call",
    "wrapper_call",
    "wrapperdescr_call",
}


@functools.lru_cache(maxsize=1000)
def _is_cpython_internal_symbol(symbol: str, file: str) -> bool:
    if "PyEval_EvalFrameEx" in symbol or "_PyEval_EvalFrameDefault" in symbol:
        is_candidate = True
    elif symbol.startswith("_TAIL_CALL_") and ".llvm." in symbol:
        # Python 3.14 tail call interpreter uses LLVM-generated functions
        is_candidate = True
    elif symbol.startswith(("PyEval", "_Py")):
        is_candidate = True
    elif "vectorcall" in symbol.lower():
        is_candidate = True
    elif symbol in SYMBOL_IGNORELIST:
        is_candidate = True
    elif "Objects/call.c" in file:
        is_candidate = True
    else:
        is_candidate = False

    if is_candidate:
        return re.search(RE_CPYTHON_PATHS, file) is not None
    return False


def is_cpython_internal(frame: StackFrame) -> bool:
    symbol, file, _ = frame
    return _is_cpython_internal_symbol(symbol, file)


def is_frame_interesting(frame: StackFrame) -> bool:
    function, file, _ = frame

    if file.endswith("runpy.py") or file == "<frozen runpy>":
        return False

    return not _is_cpython_internal_symbol(function, file)


def is_frame_from_import_system(frame: StackFrame) -> bool:
    function, file, _ = frame
    if "frozen importlib" in file:
        return True
    if function in {"import_name", "import_from", "import_all_from"} and file.endswith(
        "ceval.c"
    ):
        return True
    return False


@functools.cache
def is_confidential_file(file: str) -> bool:
    """Attempt to guess whether the file is likely to contain secrets.

    We don't want to include secrets in flame graphs, since flame graphs may be
    shared with other people.

    We assume that Python source files won't contain keys, certificates, or
    other tokens, but other files might. We assume that a file with a `.py`
    extension is a Python source file, and that an executable file is likely to
    be a Python source file too. We assume that any world-readable file will
    not contain secrets.

    These heuristics may not always be correct, and flame graphs may wind up
    having secrets embedded in them. Don't share a Memray flame graph with
    someone unless you trust them.
    """
    if file.endswith(".py"):
        return False
    with contextlib.suppress(OSError):
        st = os.stat(file)
        if st.st_mode & 0o111 or st.st_mode & 0o004:
            return False
    return True


def source_line_from_frame(
    frame: StackFrame, confidential_files: str = "default"
) -> str:
    function, filename, lineno = frame

    if confidential_files == "all":
        is_confidential = True
    elif confidential_files == "none":
        is_confidential = False
    else:
        is_confidential = is_confidential_file(filename)

    if is_confidential:
        return f"{function} at {filename}:{lineno}"
    return linecache.getline(filename, lineno) or f"{function} at {filename}:{lineno}"
