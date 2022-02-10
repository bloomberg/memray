import pytest

from bloomberg.pensieve.reporters.frame_tools import is_cpython_internal
from bloomberg.pensieve.reporters.frame_tools import is_frame_interesting


class TestFrameFiltering:
    @pytest.mark.parametrize(
        "frame, expected",
        [
            [
                (
                    "_PyEval_EvalFrameDefault",
                    "/opt/bb/src/python/python3.8/Python/ceval.c",
                    100,
                ),
                True,
            ],
            [
                ("_PyEvalSomeFunc", "/opt/bb/src/python/python3.8/Python/ceval.c", 100),
                True,
            ],
            [("VectorCall", "/opt/bb/src/python/python3.8/Python/ceval.c", 100), True],
            [("proxy_call", "/opt/bb/src/python/python3.8/Python/ceval.c", 100), True],
            [
                (
                    "function_code_fastcall",
                    "/opt/bb/src/python/python3.8/Modules/gcmodule.c",
                    100,
                ),
                True,
            ],
            [("somefunc", "myapp.py", 100), False],
            [("function_code_fastcall", "myapp.py", 100), False],
        ],
    )
    def test_cpython_internal_calls(self, frame, expected):
        # GIVEN/WHEN/THEN
        assert is_cpython_internal(frame) is expected

    @pytest.mark.parametrize(
        "frame, expected",
        [
            [("somefunc", "runpy.py", 100), False],
            [
                (
                    "_PyEval_EvalFrameDefault",
                    "/opt/bb/src/python/python3.8/Python/ceval.c",
                    100,
                ),
                False,
            ],
            [
                (
                    "PyArg_ParseTuple",
                    "/opt/bb/src/python/python3.8/Python/ceval.c",
                    100,
                ),
                True,
            ],
            [("somefunc", "myapp.py", 100), True],
            [
                (
                    "_PyEval_CompileCode",
                    "/opt/bb/src/python/python3.8/Include/code.h",
                    100,
                ),
                False,
            ],
        ],
    )
    def test_frame_interesting(self, frame, expected):
        # GIVEN/WHEN/THEN
        assert is_frame_interesting(frame) is expected
