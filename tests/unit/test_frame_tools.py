import pytest

from bloomberg.pensieve.reporters.frame_tools import is_cpython_internal
from bloomberg.pensieve.reporters.frame_tools import is_frame_interesting


class TestFrameFiltering:
    @pytest.mark.parametrize(
        "frame, expected",
        [
            [("_PyEval_EvalFrameDefault", "ceval.c", 100), True],
            [("_PyEvalSomeFunc", "ceval.c", 100), True],
            [("VectorCall", "ceval.c", 100), True],
            [("proxy_call", "ceval.c", 100), True],
            [("function_code_fastcall", "ceval.c", 100), True],
            [("somefunc", "myapp.py", 100), False],
        ],
    )
    def test_cpython_internal_calls(self, frame, expected):
        # GIVEN/WHEN/THEN
        assert is_cpython_internal(frame) is expected

    @pytest.mark.parametrize(
        "frame, expected",
        [
            [("somefunc", "runpy.py", 100), False],
            [("_PyEval_EvalFrameDefault", "ceval.c", 100), False],
            [("PyArg_ParseTuple", "ceval.c", 100), True],
            [("somefunc", "myapp.py", 100), True],
        ],
    )
    def test_frame_interesting(self, frame, expected):
        # GIVEN/WHEN/THEN
        assert is_frame_interesting(frame) is expected
