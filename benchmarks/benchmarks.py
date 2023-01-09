import mmap
import os
import tempfile

from memray import AllocatorType
from memray import FileReader

try:
    from memray._test import MemoryAllocator
except ImportError:
    from memray import MemoryAllocator

from memray import Tracker

from .benchmarking.cases import async_tree_base
from .benchmarking.cases import fannkuch_base
from .benchmarking.cases import mdp_base
from .benchmarking.cases import pprint_format_base
from .benchmarking.cases import raytrace_base

LOOPS = 1000


class TracebackBenchmarks:
    def setup(self):
        self.tempfile = tempfile.NamedTemporaryFile()
        allocator = MemoryAllocator()

        def fac(n):
            if n == 1:
                allocator.valloc(1234)
                allocator.free()
                return 1
            return n * fac(n - 1)

        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            fac(300)

        (self.record,) = [
            record
            for record in FileReader(self.tempfile.name).get_allocation_records()
            if record.allocator == AllocatorType.VALLOC
        ]

    def time_get_stack_trace(self):
        self.record.stack_trace()


class AllocatorBenchmarks:
    def setup(self):
        self.tempfile = tempfile.NamedTemporaryFile()
        self.allocator = MemoryAllocator()

    def time_malloc(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(LOOPS):
                if self.allocator.malloc(1234):
                    self.allocator.free()

    def time_posix_memalign(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(LOOPS):
                if self.allocator.posix_memalign(1234):
                    self.allocator.free()

    def time_posix_realloc(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(LOOPS):
                if self.allocator.posix_memalign(1234):
                    self.allocator.free()

    def time_calloc(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(LOOPS):
                if self.allocator.calloc(1234):
                    self.allocator.free()

    def time_pvalloc(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(LOOPS):
                if self.allocator.pvalloc(1234):
                    self.allocator.free()

    def time_valloc(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(LOOPS):
                if self.allocator.valloc(1234):
                    self.allocator.free()

    def time_realloc(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(LOOPS):
                if self.allocator.realloc(1234):
                    self.allocator.free()

    def time_mmap(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(LOOPS):
                with mmap.mmap(-1, length=2048, access=mmap.ACCESS_WRITE) as mmap_obj:
                    mmap_obj[0:100] = b"a" * 100


class ParserBenchmarks:
    def setup(self):
        self.tempfile = tempfile.NamedTemporaryFile()
        self.allocator = MemoryAllocator()
        os.unlink(self.tempfile.name)
        self.tracker = Tracker(self.tempfile.name)
        with self.tracker:
            for _ in range(LOOPS):
                self.allocator.valloc(1234)
                self.allocator.free()

    def time_end_to_end_parsing(self):
        list(FileReader(self.tempfile.name).get_allocation_records())


def recursive(n, chunk_size):
    """Mimics generally-increasing but spiky usage"""
    if not n:
        return

    allocator = MemoryAllocator()
    allocator.valloc(n * chunk_size)

    # Don't keep allocated memory when recursing, ~50% of the calls.
    if n % 2:
        allocator.free()
        recursive(n - 1, chunk_size)
    else:
        recursive(n - 1, chunk_size)
        allocator.free()


class HighWatermarkBenchmarks:
    def setup(self):
        self.tempfile = tempfile.NamedTemporaryFile()
        os.unlink(self.tempfile.name)
        self.tracker = Tracker(self.tempfile.name)

        with self.tracker:
            recursive(700, 99)

    def time_high_watermark(self):
        list(
            FileReader(self.tempfile.name).get_high_watermark_allocation_records(
                merge_threads=False
            )
        )


class MacroBenchmarksBase:
    def __init_subclass__(cls) -> None:
        for name in dir(cls):
            if name.startswith("bench_"):
                bench_name = name[len("bench_") :]
                setattr(cls, f"time_{bench_name}", getattr(cls, name))

    def bench_async_tree_cpu(self):
        with self.tracker:
            async_tree_base.run_benchmark("none")

    def bench_async_tree_io(self):
        with self.tracker:
            async_tree_base.run_benchmark("io")

    def bench_async_tree_memoization(self):
        with self.tracker:
            async_tree_base.run_benchmark("memoization")

    def bench_async_tree_cpu_io_mixed(self):
        with self.tracker:
            async_tree_base.run_benchmark("cpu_io_mixed")

    def bench_fannkuch(self):
        with self.tracker:
            fannkuch_base.run_benchmark()

    def bench_mdp(self):
        with self.tracker:
            mdp_base.run_benchmark()

    def bench_pprint_format(self):
        with self.tracker:
            pprint_format_base.run_benchmark()

    def bench_raytrace(self):
        with self.tracker:
            raytrace_base.run_benchmark()


class MacroBenchmarksDefault(MacroBenchmarksBase):
    def setup(self):
        self.tracker_args = ("/dev/null",)
        self.tracker_kwargs = {}
        self.tracker = Tracker(*self.tracker_args, **self.tracker_kwargs)


class MacroBenchmarksPythonAllocators(MacroBenchmarksBase):
    def setup(self):
        self.tracker_args = ("/dev/null",)
        self.tracker_kwargs = {"trace_python_allocators": True}
        self.tracker = Tracker(*self.tracker_args, **self.tracker_kwargs)


class MacroBenchmarksPythonNative(MacroBenchmarksBase):
    def setup(self):
        self.tracker_args = ("/dev/null",)
        self.tracker_kwargs = {"native_traces": True}
        self.tracker = Tracker(*self.tracker_args, **self.tracker_kwargs)


class MacroBenchmarksPythonAll(MacroBenchmarksBase):
    def setup(self):
        self.tracker_args = ("/dev/null",)
        self.tracker_kwargs = {"native_traces": True, "trace_python_allocators": True}
        self.tracker = Tracker(*self.tracker_args, **self.tracker_kwargs)


class FileSizeBenchmarks:
    def setup(self):
        self.tempfile = tempfile.NamedTemporaryFile()
        os.unlink(self.tempfile.name)
        self.tracker = Tracker(self.tempfile.name)

    def track_async_tree_cpu(self):
        with self.tracker:
            async_tree_base.run_benchmark("none")
        return os.stat(self.tempfile.name).st_size

    def track_async_tree_io(self):
        with self.tracker:
            async_tree_base.run_benchmark("io")
        return os.stat(self.tempfile.name).st_size

    def track_async_tree_memoization(self):
        with self.tracker:
            async_tree_base.run_benchmark("memoization")
        return os.stat(self.tempfile.name).st_size

    def track_async_tree_cpu_io_mixed(self):
        with self.tracker:
            async_tree_base.run_benchmark("cpu_io_mixed")
        return os.stat(self.tempfile.name).st_size

    def track_fannkuch(self):
        with self.tracker:
            fannkuch_base.run_benchmark()
        return os.stat(self.tempfile.name).st_size

    def track_mdp(self):
        with self.tracker:
            mdp_base.run_benchmark()
        return os.stat(self.tempfile.name).st_size

    def track_pprint_format(self):
        with self.tracker:
            pprint_format_base.run_benchmark()
        return os.stat(self.tempfile.name).st_size

    def track_raytrace(self):
        with self.tracker:
            raytrace_base.run_benchmark()
        return os.stat(self.tempfile.name).st_size
