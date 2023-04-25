import pytest

from memray.reporters.frame_tools import is_cpython_internal
from memray.reporters.frame_tools import is_frame_from_import_system
from memray.reporters.frame_tools import is_frame_interesting


class TestFrameFiltering:
    @pytest.mark.parametrize(
        "frame, expected",
        [
            [
                (
                    "_PyEval_EvalFrameDefault",
                    "/src/python/python3.8/Python/ceval.c",
                    100,
                ),
                True,
            ],
            [
                ("_PyEvalSomeFunc", "/src/python/python3.8/Python/ceval.c", 100),
                True,
            ],
            [("VectorCall", "/src/python/python3.8/Python/ceval.c", 100), True],
            [("proxy_call", "/src/python/python3.8/Python/ceval.c", 100), True],
            [
                (
                    "function_code_fastcall",
                    "/src/python/python3.8/Modules/gcmodule.c",
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
                    "/src/python/python3.8/Python/ceval.c",
                    100,
                ),
                False,
            ],
            [
                (
                    "PyArg_ParseTuple",
                    "/src/python/python3.8/Python/ceval.c",
                    100,
                ),
                True,
            ],
            [("somefunc", "myapp.py", 100), True],
            [
                (
                    "_PyEval_CompileCode",
                    "/src/python/python3.8/Include/code.h",
                    100,
                ),
                False,
            ],
        ],
    )
    def test_frame_interesting(self, frame, expected):
        # GIVEN/WHEN/THEN
        assert is_frame_interesting(frame) is expected

    @pytest.mark.parametrize(
        "frame, expected",
        [
            [("somefunc", "runpy.py", 100), False],
            [
                (
                    "_PyEval_EvalFrameDefault",
                    "/src/python/python3.8/Python/ceval.c",
                    100,
                ),
                False,
            ],
            [("somefunc", "<frozen importlib._blabla>", 100), True],
            [("somefunc", "<frozen something else>", 13), False],
            [("somefunc", "<frozen importlib>", 23), True],
            [("somefunc", "<frozen something._blich>", 11), False],
            [("somefunc", "ceval.c", 11), False],
            [("import_name", "ceval.c", 131), True],
            [("import_from", "ceval.c", 21), True],
            [("import_all_from", "ceval.c", 1), True],
            [("import_name", "otherfile.c", 14), False],
            [("import_from", "otherfile.c", 13), False],
            [("import_all_from", "otherfile.c", 12), False],
        ],
    )
    def test_is_frame_from_import_system(self, frame, expected):
        # GIVEN/WHEN/THEN
        assert is_frame_from_import_system(frame) is expected
