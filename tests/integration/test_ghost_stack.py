"""Tests for ghost_stack functionality.

These tests verify that ghost_stack (fast unwinding) works correctly:
1. C++ exceptions propagate correctly through patched frames
2. Ghost_stack frames exactly match libunwind frames
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from memray._test_utils import GhostStackTestContext, has_ghost_stack_support

HERE = Path(__file__).parent
TEST_GHOST_STACK_EXTENSION = HERE / "ghost_stack_test_extension"

pytestmark = pytest.mark.skipif(
    not has_ghost_stack_support(),
    reason="ghost_stack not available on this platform",
)


@pytest.fixture
def ghost_stack_extension(tmpdir, monkeypatch):
    """Compile and import the ghost_stack test extension."""
    extension_path = tmpdir / "ghost_stack_test_extension"
    shutil.copytree(TEST_GHOST_STACK_EXTENSION, extension_path)
    subprocess.run(
        [sys.executable, str(extension_path / "setup.py"), "build_ext", "--inplace"],
        check=True,
        cwd=extension_path,
        capture_output=True,
    )
    with monkeypatch.context() as ctx:
        ctx.setattr(sys, "path", [*sys.path, str(extension_path)])
        import ghost_stack_test

        yield ghost_stack_test


class TestGhostStackExceptions:
    """Test C++ exception safety through ghost_stack trampolines."""

    def test_basic_exception(self, ghost_stack_extension):
        """Verify std::runtime_error works through ghost_stack frames."""
        with GhostStackTestContext() as ctx:
            ghost_stack_extension.set_capture_callback(ctx.backtrace)
            assert ghost_stack_extension.test_basic_exception() is True

    def test_raii_cleanup(self, ghost_stack_extension):
        """Verify RAII destructors are called during exception unwinding."""
        with GhostStackTestContext() as ctx:
            ghost_stack_extension.set_capture_callback(ctx.backtrace)
            destructor_count = ghost_stack_extension.test_raii_cleanup()
            assert destructor_count == 1, "destructor should be called during unwinding"

    def test_raii_cleanup_order(self, ghost_stack_extension):
        """Verify LIFO destructor order (3 guards)."""
        with GhostStackTestContext() as ctx:
            ghost_stack_extension.set_capture_callback(ctx.backtrace)
            cleanup_order = ghost_stack_extension.test_raii_cleanup_order()
            # Expected: [10, 20, 30, 3, 2, 1] = construct g1, g2, g3, then destruct g3, g2, g1
            assert cleanup_order == [10, 20, 30, 3, 2, 1]

    def test_nested_try_catch(self, ghost_stack_extension):
        """Verify nested exception handling."""
        with GhostStackTestContext() as ctx:
            ghost_stack_extension.set_capture_callback(ctx.backtrace)
            result = ghost_stack_extension.test_nested_try_catch()
            assert result == "outer"

    def test_different_exception_types(self, ghost_stack_extension):
        """Verify int, const char*, std::string exceptions work."""
        with GhostStackTestContext() as ctx:
            ghost_stack_extension.set_capture_callback(ctx.backtrace)
            assert ghost_stack_extension.test_different_exception_types() is True


class TestGhostStackEquivalence:
    """Test that ghost_stack frames exactly match libunwind frames."""

    def _capture_frames_at_depth(self, ctx, depth=0):
        """Capture ghost_stack and libunwind frames at given recursion depth."""
        ctx.reset()

        if depth > 0:
            return self._capture_frames_at_depth(ctx, depth - 1)

        # Capture libunwind first (before ghost_stack patches return addresses)
        libunwind_frames = ctx.libunwind_backtrace()

        # Now capture ghost_stack
        ghost_frames = ctx.backtrace()

        ctx.reset()
        return ghost_frames, libunwind_frames

    def _find_common_start(self, ghost_frames, libunwind_frames, max_skip=3):
        """Find indices where frames start matching (max skip of 3 frames each)."""
        libunwind_set = set(libunwind_frames[:max_skip + 1])
        for gi in range(min(max_skip + 1, len(ghost_frames))):
            gf = ghost_frames[gi]
            if gf in libunwind_set:
                li = libunwind_frames.index(gf)
                if li <= max_skip:
                    return gi, li
        return None, None

    def test_frames_match_shallow(self):
        """Verify ghost_stack frame IPs match libunwind frame IPs."""
        with GhostStackTestContext() as ctx:
            ghost_frames, libunwind_frames = self._capture_frames_at_depth(ctx, depth=0)

            assert len(ghost_frames) > 0, "ghost_stack should capture frames"
            assert len(libunwind_frames) > 0, "libunwind should capture frames"

            # Find where frames start matching (skip at most 3 capture internals)
            gi, li = self._find_common_start(ghost_frames, libunwind_frames)
            assert gi is not None, (
                f"should find common frames within first 3\n"
                f"ghost: {[hex(f) for f in ghost_frames]}\n"
                f"libunwind: {[hex(f) for f in libunwind_frames]}"
            )

            ghost_tail = ghost_frames[gi:]
            libunwind_tail = libunwind_frames[li:]

            assert ghost_tail == libunwind_tail, (
                f"frame IPs must match exactly from common start\n"
                f"ghost[{gi}:]: {[hex(f) for f in ghost_tail]}\n"
                f"libunwind[{li}:]: {[hex(f) for f in libunwind_tail]}"
            )

    def test_frames_match_deep(self):
        """Verify frame matching at recursion depth 10."""
        with GhostStackTestContext() as ctx:
            ghost_frames, libunwind_frames = self._capture_frames_at_depth(ctx, depth=10)

            assert len(ghost_frames) >= 10, "should capture at least 10 frames"
            assert len(libunwind_frames) >= 10, "libunwind should capture at least 10 frames"

            # Find where frames start matching (skip at most 3 capture internals)
            gi, li = self._find_common_start(ghost_frames, libunwind_frames)
            assert gi is not None, (
                f"should find common frames within first 3\n"
                f"ghost: {[hex(f) for f in ghost_frames]}\n"
                f"libunwind: {[hex(f) for f in libunwind_frames]}"
            )

            ghost_tail = ghost_frames[gi:]
            libunwind_tail = libunwind_frames[li:]

            assert ghost_tail == libunwind_tail, (
                f"frame IPs must match exactly from common start\n"
                f"ghost[{gi}:]: {[hex(f) for f in ghost_tail]}\n"
                f"libunwind[{li}:]: {[hex(f) for f in libunwind_tail]}"
            )


class TestGhostStackThreadSafety:
    """Test thread safety of ghost_stack."""

    def test_rapid_reset(self):
        """Verify rapid reset/capture cycles work."""
        with GhostStackTestContext() as ctx:
            for _ in range(1000):
                frames = ctx.backtrace()
                assert len(frames) > 0, "should capture frames"
                ctx.reset()

    def test_multiple_threads(self):
        """Verify ghost_stack works correctly across multiple threads."""
        import threading

        errors = []

        def thread_func():
            try:
                with GhostStackTestContext() as ctx:
                    for _ in range(100):
                        frames = ctx.backtrace()
                        if len(frames) == 0:
                            errors.append("No frames captured")
                        ctx.reset()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=thread_func) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
