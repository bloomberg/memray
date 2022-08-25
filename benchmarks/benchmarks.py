import mmap
import os
import tempfile

import numpy as np
from skimage import data
from skimage.registration import phase_cross_correlation
from scipy.ndimage import fourier_shift
from skimage.transform import rescale

from . import pystone

from memray import AllocatorType
from memray import FileReader
from memray._test import MemoryAllocator
from memray import Tracker

MAX_ITERS = 100000


def check(n):
    l = [0] * n
    s = repr(l)
    other = "[" + ", ".join(["0"] * n) + "]"
    return s == other


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


class HighLevelBenchmarks:
    def setup(self):
        self.tempfile = tempfile.NamedTemporaryFile()
        self.allocator = MemoryAllocator()

    def time_lot_of_allocs(self):
        L = []

        def f():
            g()
            g()
            g()
            g()
            g()
            g()
            g()
            g()
            g()
            g()
            if len(L) < 100_000:
                f()

        def g():
            h()
            h()
            h()
            h()
            h()
            h()
            h()
            h()
            h()
            h()
            h()
            h()

        def h():
            L.append(list())
            x = list()
            del x
            L.append(list())
            x = list()
            del x
            L.append(list())
            x = list()
            del x
            L.append(list())
            x = list()
            del x
            L.append(list())
            x = list()
            del x
            L.append(list())
            x = list()
            del x
            L.append(list())
            x = list()
            del x
            L.append(list())
            x = list()
            del x
            L.append(list())
            x = list()
            del x
            L.append(list())
            x = list()
            del x

        f()

    def time_scikit_image(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            image = data.camera()
            scale = 4
            image = rescale(image, scale, anti_aliasing=True)
            shift = (-22.4, 13.32)
            offset_image = fourier_shift(np.fft.fftn(image), shift)
            offset_image = np.fft.ifftn(offset_image)
            shift, error, diffphase = phase_cross_correlation(image, offset_image)
            image_product = np.fft.fft2(image) * np.fft.fft2(offset_image).conj()
            cc_image = np.fft.fftshift(np.fft.ifft2(image_product))

    def time_scikit_image_with_native_traces(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name, native_traces=True):
            image = data.camera()
            scale = 4
            image = rescale(image, scale, anti_aliasing=True)
            shift = (-22.4, 13.32)
            offset_image = fourier_shift(np.fft.fftn(image), shift)
            offset_image = np.fft.ifftn(offset_image)
            shift, error, diffphase = phase_cross_correlation(image, offset_image)
            image_product = np.fft.fft2(image) * np.fft.fft2(offset_image).conj()
            cc_image = np.fft.fftshift(np.fft.ifft2(image_product))

    def time_pystone(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            pystone.main(loops=1000)

    def time_python_objects(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name):
            check(1000000)

    def time_python_objects_native(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name, native_traces=True):
            check(1000000)

    def time_python_objects_python_allocators(self):
        os.unlink(self.tempfile.name)
        with Tracker(self.tempfile.name, trace_python_allocators=True):
            check(1000000)
