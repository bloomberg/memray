import mmap
import os
import tempfile

from memray import AllocatorType
from memray import FileReader
from memray import MemoryAllocator
from memray import Tracker

MAX_ITERS = 100000


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
            for _ in range(MAX_ITERS):
                self.allocator.malloc(1234)
                self.allocator.free()

    def time_posix_memalign(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(MAX_ITERS):
                self.allocator.posix_memalign(1234)
                self.allocator.free()

    def time_posix_realloc(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(MAX_ITERS):
                self.allocator.posix_memalign(1234)
                self.allocator.free()

    def time_calloc(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(MAX_ITERS):
                self.allocator.calloc(1234)
                self.allocator.free()

    def time_pvalloc(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(MAX_ITERS):
                self.allocator.pvalloc(1234)
                self.allocator.free()

    def time_valloc(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(MAX_ITERS):
                self.allocator.valloc(1234)
                self.allocator.free()

    def time_realloc(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(MAX_ITERS):
                self.allocator.realloc(1234)
                self.allocator.free()

    def time_mmap(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            for _ in range(MAX_ITERS):
                with mmap.mmap(-1, length=2048, access=mmap.ACCESS_WRITE) as mmap_obj:
                    mmap_obj[0:100] = b"a" * 100


class ParserBenchmarks:
    def setup(self):
        self.tempfile = tempfile.NamedTemporaryFile()
        self.allocator = MemoryAllocator()
        os.unlink(self.tempfile.name)
        self.tracker = Tracker(self.tempfile.name)
        with self.tracker:
            for _ in range(MAX_ITERS):
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
