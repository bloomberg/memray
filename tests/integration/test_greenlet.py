import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from memray import AllocatorType
from memray import FileReader
from tests.utils import filter_relevant_allocations

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("greenlet") is None, reason="greenlet is not installed"
)


def test_integration_with_greenlet(tmpdir):
    """Verify that we can track Python stacks when greenlet is in use."""
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    subprocess_code = textwrap.dedent(
        f"""
        import greenlet

        from memray import Tracker
        from memray._test import MemoryAllocator


        def apple():
            banana()


        def banana():
            allocator.valloc(1024 * 10)
            animal.switch()
            allocator.valloc(1024 * 30)


        def ant():
            allocator.valloc(1024 * 20)
            fruit.switch()
            allocator.valloc(1024 * 40)
            bat()
            allocator.valloc(1024 * 60)


        def bat():
            allocator.valloc(1024 * 50)


        def test():
            fruit.switch()
            assert fruit.dead
            animal.switch()
            assert animal.dead
            allocator.valloc(1024 * 70)


        allocator = MemoryAllocator()
        output = "{output}"

        with Tracker(output):
            fruit = greenlet.greenlet(apple)
            animal = greenlet.greenlet(ant)
            test()
        """
    )

    # WHEN
    subprocess.run([sys.executable, "-Xdev", "-c", subprocess_code], timeout=5)

    # THEN
    reader = FileReader(output)
    records = list(reader.get_allocation_records())
    vallocs = [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]

    def stack(alloc):
        return [frame[0] for frame in alloc.stack_trace()]

    assert stack(vallocs[0]) == ["valloc", "banana", "apple"]
    assert vallocs[0].size == 10 * 1024

    assert stack(vallocs[1]) == ["valloc", "ant"]
    assert vallocs[1].size == 20 * 1024

    assert stack(vallocs[2]) == ["valloc", "banana", "apple"]
    assert vallocs[2].size == 30 * 1024

    assert stack(vallocs[3]) == ["valloc", "ant"]
    assert vallocs[3].size == 40 * 1024

    assert stack(vallocs[4]) == ["valloc", "bat", "ant"]
    assert vallocs[4].size == 50 * 1024

    assert stack(vallocs[5]) == ["valloc", "ant"]
    assert vallocs[5].size == 60 * 1024

    assert stack(vallocs[6]) == ["valloc", "test", "<module>"]
    assert vallocs[6].size == 70 * 1024


def test_importing_greenlet_after_tracking_starts(tmpdir):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    subprocess_code = textwrap.dedent(
        f"""
        from memray import Tracker
        from memray._test import MemoryAllocator


        def apple():
            banana()


        def banana():
            allocator.valloc(1024 * 10)
            animal.switch()
            allocator.valloc(1024 * 30)


        def ant():
            allocator.valloc(1024 * 20)
            fruit.switch()
            allocator.valloc(1024 * 40)
            bat()
            allocator.valloc(1024 * 60)


        def bat():
            allocator.valloc(1024 * 50)


        def test():
            fruit.switch()
            assert fruit.dead
            animal.switch()
            assert animal.dead
            allocator.valloc(1024 * 70)


        allocator = MemoryAllocator()
        output = "{output}"

        with Tracker(output):
            import greenlet

            fruit = greenlet.greenlet(apple)
            animal = greenlet.greenlet(ant)
            test()
        """
    )

    # WHEN
    subprocess.run([sys.executable, "-Xdev", "-c", subprocess_code], timeout=5)

    # THEN
    reader = FileReader(output)
    records = list(reader.get_allocation_records())
    vallocs = [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]

    def stack(alloc):
        return [frame[0] for frame in alloc.stack_trace()]

    assert stack(vallocs[0]) == ["valloc", "banana", "apple"]
    assert vallocs[0].size == 10 * 1024

    assert stack(vallocs[1]) == ["valloc", "ant"]
    assert vallocs[1].size == 20 * 1024

    assert stack(vallocs[2]) == ["valloc", "banana", "apple"]
    assert vallocs[2].size == 30 * 1024

    assert stack(vallocs[3]) == ["valloc", "ant"]
    assert vallocs[3].size == 40 * 1024

    assert stack(vallocs[4]) == ["valloc", "bat", "ant"]
    assert vallocs[4].size == 50 * 1024

    assert stack(vallocs[5]) == ["valloc", "ant"]
    assert vallocs[5].size == 60 * 1024

    assert stack(vallocs[6]) == ["valloc", "test", "<module>"]
    assert vallocs[6].size == 70 * 1024

    # 0 and 2 are fruit, 1 and 3 and 4 and 5 are animal, 6 is main.
    assert vallocs[0].tid != vallocs[1].tid != vallocs[6].tid
    assert vallocs[0].tid == vallocs[2].tid
    assert vallocs[1].tid == vallocs[3].tid == vallocs[4].tid == vallocs[5].tid


def test_uninstall_profile_in_greenlet(tmpdir):
    """Verify that memray handles profile function changes in greenlets correctly."""
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    subprocess_code = textwrap.dedent(
        f"""
        import greenlet
        import sys

        from memray import Tracker
        from memray._test import MemoryAllocator

        def foo():
            bar()
            allocator.valloc(1024 * 10)

        def bar():
            baz()

        def baz():
            sys.setprofile(None)
            other.switch()

        def test():
            allocator.valloc(1024 * 70)
            main_greenlet.switch()


        allocator = MemoryAllocator()
        output = "{output}"

        with Tracker(output):
            main_greenlet = greenlet.getcurrent()
            other = greenlet.greenlet(test)
            foo()

        """
    )

    # WHEN
    subprocess.run([sys.executable, "-Xdev", "-c", subprocess_code], timeout=5)

    # THEN
    reader = FileReader(output)
    records = list(reader.get_allocation_records())
    vallocs = [
        record
        for record in filter_relevant_allocations(records)
        if record.allocator == AllocatorType.VALLOC
    ]

    def stack(alloc):
        return [frame[0] for frame in alloc.stack_trace()]

    # Verify allocations and their stack traces (which should be empty
    # because we remove the tracking function)
    assert len(vallocs) == 2

    assert stack(vallocs[0]) == []
    assert vallocs[0].size == 70 * 1024

    assert stack(vallocs[1]) == []
    assert vallocs[1].size == 10 * 1024

    # Verify thread IDs
    main_tid = vallocs[0].tid  # inner greenlet
    outer_tid = vallocs[1].tid  # outer greenlet
    assert main_tid == outer_tid


@pytest.mark.skipif(
    sys.version_info < (3, 11), reason="gen.throw frame links require 3.11"
)
@pytest.mark.parametrize("handled", [False, True])
@pytest.mark.parametrize("native_traces", [False, True])
def test_greenlet_throw_stack(tmp_path, handled, native_traces):
    output = tmp_path / "capture.bin"
    code = textwrap.dedent(f"""
        import greenlet
        import memray
        import sys

        main = greenlet.getcurrent()

        def child():
            main.switch()

        def inner():
            worker = greenlet.greenlet(child)
            worker.switch()
            try:
                yield
            except ValueError:
                try:
                    worker.throw(*sys.exc_info())
                except ValueError:
                    if not {handled!r}:
                        raise
                    yield

        def middle():
            try:
                yield from inner()
            finally:
                marker = bytearray(777_777)

        def outer():
            yield from middle()

        def run():
            gen = outer()
            next(gen)
            try:
                gen.throw(ValueError)
            except ValueError:
                pass
            marker = bytearray(888_888)
            gen.close()

        with memray.Tracker({str(output)!r}, native_traces={native_traces!r}):
            run()
        """)
    subprocess.run([sys.executable, "-Xdev", "-c", code], check=True, timeout=10)
    records = list(FileReader(output).get_allocation_records())
    for size, expected in (
        (777_777, ["middle"] + ([] if handled else ["outer"]) + ["run", "<module>"]),
        (888_888, ["run", "<module>"]),
    ):
        stacks = [
            [name for name, _, _ in record.stack_trace()]
            for record in records
            if size <= record.size <= size + 64
        ]
        assert stacks == [expected]


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="code instrumentation requires 3.12"
)
@pytest.mark.parametrize("mode", ["return", "frame_reuse", "code_reuse", "same_code"])
@pytest.mark.parametrize("native_traces", [False, True])
def test_greenlet_returns_without_profile_events(tmp_path, mode, native_traces):
    output = tmp_path / "capture.bin"
    code = textwrap.dedent(f"""
        import greenlet
        import memray
        import sys
        import types

        main = greenlet.getcurrent()
        mode = {mode!r}

        def leaf():
            return pow(2, 3)

        def transient():
            namespace["paused"]()

        def run():
            transient()
            if mode == "return":
                marker = bytearray(777_777)
                return
            if mode == "code_reuse":
                fn = types.FunctionType(template.replace(co_name="leaf"), namespace)
            elif mode == "same_code":
                fn = namespace["paused"]
            else:
                fn = leaf
            try:
                fn()
            except RuntimeError:
                pass

        def trace(frame, event, arg):
            if event == "call" and frame.f_code.co_name in {{"paused", "leaf"}}:
                marker = bytearray(777_777)
                raise RuntimeError("stop before the profile call event")
            return trace

        namespace = {{"main": main, "sys": sys}}
        source = (
            "def paused():\\n"
            "    global paused\\n"
            "    frame_id = id(sys._getframe())\\n"
            + ("" if mode == "same_code" else "    del paused\\n")
            + "    main.switch()\\n"
        )
        exec(compile(source, "temporary.py", "exec"), namespace)
        template = namespace["paused"].__code__.replace(co_linetable=b"")
        worker = greenlet.greenlet(run)
        worker.switch()
        with memray.Tracker({str(output)!r}, native_traces={native_traces!r}):
            if mode != "return":
                sys.settrace(trace)
            try:
                worker.switch()
            finally:
                sys.settrace(None)
        """)
    subprocess.run([sys.executable, "-Xdev", "-c", code], check=True, timeout=10)
    stacks = [
        [name for name, _, _ in record.stack_trace()]
        for record in FileReader(output).get_allocation_records()
        if 777_777 <= record.size <= 777_777 + 64
    ]
    assert stacks == [["run"]]
