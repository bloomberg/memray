import collections
import contextlib
import os
import pathlib
import platform
import sys

cimport cython

import threading
from datetime import datetime

from rich import print as pprint
from rich.progress import Progress
from rich.progress import SpinnerColumn

from posix.time cimport CLOCK_MONOTONIC
from posix.time cimport clock_gettime
from posix.time cimport timespec

from _memray.algorithm cimport count
from _memray.hooks cimport Allocator
from _memray.hooks cimport isDeallocator
from _memray.logging cimport setLogThreshold
from _memray.native_resolver cimport unwindHere
from _memray.record_reader cimport RecordReader
from _memray.record_reader cimport RecordResult
from _memray.record_writer cimport RecordWriter
from _memray.record_writer cimport createRecordWriter
from _memray.records cimport AggregatedAllocation
from _memray.records cimport Allocation as _Allocation
from _memray.records cimport FileFormat as _FileFormat
from _memray.records cimport MemoryRecord
from _memray.records cimport MemorySnapshot as _MemorySnapshot
from _memray.sink cimport FileSink
from _memray.sink cimport NullSink
from _memray.sink cimport Sink
from _memray.sink cimport SocketSink
from _memray.snapshot cimport NO_THREAD_INFO
from _memray.snapshot cimport AbstractAggregator
from _memray.snapshot cimport AggregatedCaptureReaggregator
from _memray.snapshot cimport AllocationLifetime
from _memray.snapshot cimport AllocationLifetimeAggregator
from _memray.snapshot cimport AllocationStatsAggregator
from _memray.snapshot cimport HighWatermark
from _memray.snapshot cimport HighWaterMarkAggregator
from _memray.snapshot cimport HighWatermarkFinder
from _memray.snapshot cimport HighWaterMarkLocationKey
from _memray.snapshot cimport Py_GetSnapshotAllocationRecords
from _memray.snapshot cimport Py_ListFromSnapshotAllocationRecords
from _memray.snapshot cimport SnapshotAllocationAggregator
from _memray.snapshot cimport TemporaryAllocationsAggregator
from _memray.socket_reader_thread cimport BackgroundSocketReader
from _memray.source cimport FileSource
from _memray.source cimport SocketSource
from _memray.tracking_api cimport Tracker as NativeTracker
from _memray.tracking_api cimport install_trace_function
from cpython cimport PyErr_CheckSignals
from libc.math cimport ceil
from libc.stdint cimport uint64_t
from libcpp cimport bool
from libcpp.limits cimport numeric_limits
from libcpp.memory cimport make_shared
from libcpp.memory cimport make_unique
from libcpp.memory cimport shared_ptr
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string as cppstring
from libcpp.unordered_map cimport unordered_map
from libcpp.utility cimport move
from libcpp.vector cimport vector

from ._destination import Destination
from ._destination import FileDestination
from ._destination import SocketDestination
from ._metadata import Metadata
from ._stats import Stats
from ._thread_name_interceptor import ThreadNameInterceptor


cdef extern from "pthread.h" nogil:
    int pthread_atfork(void (*prepare)(), void (*parent)(), void (*child)())

# NOTE: We can't reinitialize tracking in a child process until the interpreter
#       has reinitialized its locks, so we do it in a Python fork handler.
#       But, Python fork handlers aren't guaranteed to run for every fork, and
#       the child process must never inherit an active tracker, so we must use
#       a pthread fork handler to disable tracking before forking.
pthread_atfork(&NativeTracker.prepareFork, &NativeTracker.parentFork, NULL)
os.register_at_fork(after_in_child=NativeTracker.childFork)


def set_log_level(int level):
    """Configure which log messages will be printed to stderr by memray.

    By default, only log records of severity `logging.WARNING` or higher will
    be printed, but you can adjust this threshold.

    Args:
        level (int): The lowest severity level that a log record can have and
            still be printed.
    """
    setLogThreshold(level)


cpdef enum AllocatorType:
    MALLOC = 1
    FREE = 2
    CALLOC = 3
    REALLOC = 4
    POSIX_MEMALIGN = 5
    ALIGNED_ALLOC = 6
    MEMALIGN = 7
    VALLOC = 8
    PVALLOC = 9
    MMAP = 10
    MUNMAP = 11
    PYMALLOC_MALLOC = 12
    PYMALLOC_CALLOC = 13
    PYMALLOC_REALLOC = 14
    PYMALLOC_FREE = 15

cpdef enum PythonAllocatorType:
    PYTHON_ALLOCATOR_PYMALLOC = 1
    PYTHON_ALLOCATOR_PYMALLOC_DEBUG = 2
    PYTHON_ALLOCATOR_MALLOC = 3
    PYTHON_ALLOCATOR_OTHER = 4

cpdef enum FileFormat:
    ALL_ALLOCATIONS = _FileFormat.ALL_ALLOCATIONS
    AGGREGATED_ALLOCATIONS = _FileFormat.AGGREGATED_ALLOCATIONS


def size_fmt(num, suffix='B'):
    for unit in ['','K','M','G','T','P','E','Z']:
        if abs(num) < 1024.0:
            return f"{num:5.3f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Y{suffix}"

# Memray core

cdef stack_trace(
    RecordReader* reader,
    tid,
    allocator,
    python_stack_id,
    max_stacks=None,
):
    if allocator in (AllocatorType.FREE, AllocatorType.MUNMAP):
        raise NotImplementedError("Stack traces for deallocations aren't captured.")

    assert reader != NULL, "Cannot get stack trace without reader."
    cdef ssize_t to_skip
    cdef ssize_t to_keep

    if max_stacks is not None:
        return reader.Py_GetStackFrame(python_stack_id, max_stacks)

    stack_trace = reader.Py_GetStackFrame(python_stack_id)
    if tid == reader.getMainThreadTid():
        to_skip = reader.getSkippedFramesOnMainThread()
        to_keep = max(len(stack_trace) - to_skip, 0)
        del stack_trace[to_keep:]
    return stack_trace


cdef native_stack_trace(
    RecordReader* reader,
    allocator,
    native_stack_id,
    generation,
    max_stacks=None,
):
    if allocator in (AllocatorType.FREE, AllocatorType.MUNMAP):
        raise NotImplementedError("Stack traces for deallocations aren't captured.")

    assert reader != NULL, "Cannot get stack trace without reader."
    if max_stacks is None:
        return reader.Py_GetNativeStackFrame(native_stack_id, generation)
    return reader.Py_GetNativeStackFrame(native_stack_id, generation, max_stacks)


cdef hybrid_stack_trace(
    RecordReader* reader,
    tid,
    allocator,
    python_stack_id,
    native_stack_id,
    generation,
    max_stacks=None,
):
    # This function merges a Python stack and a native stack into
    # a "hybrid" stack. It substitutes _PyFrame_EvalFrameDefault calls in
    # the native stack with the corresponding frame in the Python stack.
    # This sounds easy, but there are several tricky aspects:
    # 1. For the thread that called Tracker.__enter__, we want to hide
    #    frames (both Python and C) above the one that made that call.
    #    For other threads we want to keep all frames.
    # 2. If _PyFrame_EvalFrameDefault allocates memory before calling our
    #    profile function, we'll have too few Python frames to pair up
    #    every _PyFrame_EvalFrameDefault call. This happens in 3.11.
    # 3. Since Python 3.11, one _PyFrame_EvalFrameDefault call can evaluate
    #    many Python frames. If a frame's is_entry_frame flag is unset, it
    #    uses the same _PyFrame_EvalFrameDefault call as its caller.
    # 4. If the interpreter was stripped, we may not be able to recognize
    #    every (or even any) _PyFrame_EvalFrameDefault call, so we may
    #    have extra Python frames left after pairing.
    cdef vector[unsigned char] is_entry_frame
    native_stack = native_stack_trace(reader, allocator, native_stack_id, generation)
    python_stack = reader.Py_GetStackFrameAndEntryInfo(python_stack_id, &is_entry_frame)

    cdef ssize_t num_non_entry_frames = count(
        is_entry_frame.begin(), is_entry_frame.end(), 0
    )

    # Entry frames replace native frames; non-entry frames are inserted.
    hybrid_stack = [None] * (len(native_stack) + num_non_entry_frames)

    # Both stacks are from most recent to least, but we must pair things up
    # least recent to most to handle cases where _PyFrame_EvalFrameDefault
    # allocated memory before calling the profile function.
    native_stack.reverse()
    cdef ssize_t pidx = len(python_stack) - 1
    cdef ssize_t hidx = len(hybrid_stack) - 1

    cdef ssize_t to_skip = 0
    if tid == reader.getMainThreadTid():
        to_skip = reader.getSkippedFramesOnMainThread()
    cdef ssize_t first_kept_frame = pidx - to_skip

    for native_frame in native_stack:
        symbol = native_frame[0]
        if pidx >= 0 and "_PyEval_EvalFrameDefault" in symbol:
            while True:
                # If we're not keeping all frames and we've reached the
                # first one we want to keep, remove frames above it.
                if to_skip != 0 and pidx == first_kept_frame:
                    del hybrid_stack[hidx + 1:]

                assert hidx >= 0
                hybrid_stack[hidx] = python_stack[pidx]
                hidx -= 1
                pidx -= 1

                # Stop when we either run out of Python frames or reach the
                # entry frame being evaluated by the next eval loop.
                if pidx < 0 or is_entry_frame[pidx]:
                    break
        else:
            assert hidx >= 0
            hybrid_stack[hidx] = native_frame
            hidx -= 1

    if pidx >= 0:
        # We ran out of native frames without using up all of our Python
        # frames. We've seen this happen on stripped interpreters on Alpine
        # Linux in CI. Presumably this indicates that unwinding failed to
        # symbolify some of the calls to _PyEval_EvalFrameDefault.
        return python_stack
    assert hidx == -1

    return hybrid_stack[:max_stacks]


@cython.freelist(1024)
cdef class AllocationRecord:
    cdef object _tuple
    cdef dict _stack_trace_cache
    cdef shared_ptr[RecordReader] _reader

    def __init__(self, record):
        self._tuple = record
        self._stack_trace_cache = {}

    def __eq__(self, other):
        cdef AllocationRecord _other
        if isinstance(other, AllocationRecord):
            _other = other
            return self._tuple == _other._tuple
        return NotImplemented

    def __hash__(self):
        return hash(self._tuple)

    @property
    def tid(self):
        return self._tuple[0]

    @property
    def address(self):
        return self._tuple[1]

    @property
    def size(self):
        return self._tuple[2]

    @property
    def allocator(self):
        return self._tuple[3]

    @property
    def stack_id(self):
        return self._tuple[4]

    @property
    def n_allocations(self):
        return self._tuple[5]

    @property
    def native_stack_id(self):
        return self._tuple[6]

    @property
    def native_segment_generation(self):
        return self._tuple[7]

    @property
    def thread_name(self):
        if self.tid == -1:
            return "merged thread"
        assert self._reader.get() != NULL, "Cannot get thread name without reader."
        return self._reader.get().getThreadName(self.tid)

    def stack_trace(self, max_stacks=None):
        cache_key = ("python", max_stacks)
        if cache_key not in self._stack_trace_cache:
            self._stack_trace_cache[cache_key] = stack_trace(
                self._reader.get(),
                self.tid,
                self.allocator,
                self.stack_id,
                max_stacks,
            )
        return self._stack_trace_cache[cache_key]

    def native_stack_trace(self, max_stacks=None):
        cache_key = ("native", max_stacks)
        if cache_key not in self._stack_trace_cache:
            self._stack_trace_cache[cache_key] = native_stack_trace(
                self._reader.get(),
                self.allocator,
                self.native_stack_id,
                self.native_segment_generation,
                max_stacks,
            )
        return self._stack_trace_cache[cache_key]

    def hybrid_stack_trace(self, max_stacks=None):
        cache_key = ("hybrid", max_stacks)
        if cache_key not in self._stack_trace_cache:
            self._stack_trace_cache[cache_key] = hybrid_stack_trace(
                self._reader.get(),
                self.tid,
                self.allocator,
                self.stack_id,
                self.native_stack_id,
                self.native_segment_generation,
                max_stacks,
            )
        return self._stack_trace_cache[cache_key]

    def __repr__(self):
        return (f"AllocationRecord<tid={hex(self.tid)}, address={hex(self.address)}, "
                f"size={'N/A' if not self.size else size_fmt(self.size)}, allocator={self.allocator!r}, "
                f"allocations={self.n_allocations}>")


@cython.freelist(1024)
cdef class Interval:
    cdef public size_t allocated_before_snapshot
    cdef public object deallocated_before_snapshot
    cdef public size_t n_allocations
    cdef public size_t n_bytes

    def __cinit__(
        self,
        size_t allocated_before_snapshot,
        object deallocated_before_snapshot,
        size_t n_allocations,
        size_t n_bytes,
    ):
        self.allocated_before_snapshot = allocated_before_snapshot
        self.deallocated_before_snapshot = deallocated_before_snapshot
        self.n_allocations = n_allocations
        self.n_bytes = n_bytes

    def __eq__(self, other):
        if type(other) is not Interval:
            return NotImplemented
        return (
            self.allocated_before_snapshot,
            self.deallocated_before_snapshot,
            self.n_allocations,
            self.n_bytes,
        ) == (
            other.allocated_before_snapshot,
            other.deallocated_before_snapshot,
            other.n_allocations,
            other.n_bytes,
        )

    def __repr__(self):
        return (
            f"Interval(allocated_before_snapshot={self.allocated_before_snapshot},"
            f" deallocated_before_snapshot={self.deallocated_before_snapshot},"
            f" n_allocations={self.n_allocations},"
            f" n_bytes={self.n_bytes})"
        )


@cython.freelist(1024)
cdef class TemporalAllocationRecord:
    cdef object _tuple
    cdef dict _stack_trace_cache
    cdef shared_ptr[RecordReader] _reader
    cdef public object intervals

    def __cinit__(self, record):
        self._tuple = record
        self._stack_trace_cache = {}
        self.intervals = []

    def __eq__(self, other):
        if type(other) != TemporalAllocationRecord:
            return NotImplemented
        cdef TemporalAllocationRecord o = other
        return self._tuple == o._tuple and self._intervals == o._intervals

    def __hash__(self):
        return hash(self._tuple)

    @property
    def tid(self):
        return self._tuple[0]

    @property
    def allocator(self):
        return self._tuple[1]

    @property
    def stack_id(self):
        return self._tuple[2]

    @property
    def native_stack_id(self):
        return self._tuple[3]

    @property
    def native_segment_generation(self):
        return self._tuple[4]

    @property
    def thread_name(self):
        assert self._reader.get() != NULL, "Cannot get thread name without reader."
        return self._reader.get().getThreadName(self.tid)

    def stack_trace(self, max_stacks=None):
        cache_key = ("python", max_stacks)
        if cache_key not in self._stack_trace_cache:
            self._stack_trace_cache[cache_key] = stack_trace(
                self._reader.get(),
                self.tid,
                self.allocator,
                self.stack_id,
                max_stacks,
            )
        return self._stack_trace_cache[cache_key]

    def native_stack_trace(self, max_stacks=None):
        cache_key = ("native", max_stacks)
        if cache_key not in self._stack_trace_cache:
            self._stack_trace_cache[cache_key] = native_stack_trace(
                self._reader.get(),
                self.allocator,
                self.native_stack_id,
                self.native_segment_generation,
                max_stacks,
            )
        return self._stack_trace_cache[cache_key]

    def hybrid_stack_trace(self, max_stacks=None):
        cache_key = ("hybrid", max_stacks)
        if cache_key not in self._stack_trace_cache:
            self._stack_trace_cache[cache_key] = hybrid_stack_trace(
                self._reader.get(),
                self.tid,
                self.allocator,
                self.stack_id,
                self.native_stack_id,
                self.native_segment_generation,
                max_stacks,
            )
        return self._stack_trace_cache[cache_key]


cdef create_temporal_allocation_record(
    const HighWaterMarkLocationKey& key,
    shared_ptr[RecordReader] reader,
):
    cdef object elem = (
        key.thread_id,
        <int>key.allocator,
        key.python_frame_id,
        key.native_frame_id,
        key.native_segment_generation,
    )
    cdef TemporalAllocationRecord alloc = TemporalAllocationRecord(elem)
    alloc._reader = reader
    return alloc


cdef class TemporalAllocationGenerator:
    cdef vector[AllocationLifetime] lifetimes
    cdef shared_ptr[RecordReader] reader

    cdef TemporalAllocationRecord curr_record
    cdef HighWaterMarkLocationKey last_key
    cdef size_t idx

    cdef setup(
        self,
        vector[AllocationLifetime]&& lifetimes,
        shared_ptr[RecordReader] reader,
    ):
        self.lifetimes = move(lifetimes)
        self.reader = move(reader)

    def __iter__(self):
        return self

    def __next__(self):
        to_return = None
        cdef AllocationLifetime lifetime
        while self.idx < self.lifetimes.size():
            lifetime = self.lifetimes[self.idx]
            self.idx += 1

            if lifetime.key != self.last_key:
                if self.curr_record is not None:
                    to_return = self.curr_record
                self.last_key = lifetime.key
                self.curr_record = create_temporal_allocation_record(
                    lifetime.key, self.reader
                )

            if lifetime.deallocatedBeforeSnapshot == <size_t>(-1):
                deallocated_before_snapshot = None
            else:
                deallocated_before_snapshot = lifetime.deallocatedBeforeSnapshot

            self.curr_record.intervals.append(
                Interval(
                    lifetime.allocatedBeforeSnapshot,
                    deallocated_before_snapshot,
                    lifetime.n_allocations,
                    lifetime.n_bytes,
                )
            )

            if to_return is not None:
                return to_return

        if self.curr_record is not None:
            to_return = self.curr_record
            self.curr_record = None
            return to_return
        raise StopIteration


MemorySnapshot = collections.namedtuple("MemorySnapshot", "time rss heap")

cdef class ProfileFunctionGuard:
    def __dealloc__(self):
        """When our profile function gets deregistered, drop our cached stack.

        This drops our references to frames that may now be destroyed without
        us finding out. Note that the profile function is automatically
        deregistered when the PyThreadState is destroyed, so we can also use
        this to perform some cleanup when a thread dies.
        """
        NativeTracker.forgetPythonStack()


tracker_creation_lock = threading.Lock()


cdef class Tracker:
    """Context manager for tracking memory allocations in a Python script.

    You can track memory allocations in a Python process by using a Tracker as
    a context manager::

        with memray.Tracker("some_output_file.bin"):

    Any code inside of the ``with`` block will have its allocations tracked.
    Any allocations made by other threads will also be tracked for the duration
    of the ``with`` block. Because of the way tracking works, there can only be
    one tracker active in the entire program at a time. Attempting to activate
    a tracker while one is already active will raise an exception, as will
    attempting to activate the same tracker more than once. If you want to
    re-enable tracking after the ``with`` block ends, you will need to create
    a fresh `Tracker` instance.

    Args:
        file_name (str or pathlib.Path): The name of the file to write the
            captured allocations into. This is the only argument that can be
            passed positionally. If not provided, the *destination* keyword
            argument must be provided.
        destination (FileDestination or SocketDestination): The destination to
            write captured allocations to. If provided, the *file_name*
            argument must not be provided.
        native_traces (bool): Whether or not to capture native stack frames, in
            addition to Python stack frames (see :ref:`Native Tracking`).
            Defaults to False.
        trace_python_allocators (bool): Whether or not to trace Python allocators
            as independent allocations. (see :ref:`Python allocators`).
            Defaults to False.
        follow_fork (bool): Whether or not to continue tracking in a subprocess
            that is forked from the tracked process (see :ref:`Tracking across
            Forks`). Defaults to False.
        memory_interval_ms (int): How many milliseconds to wait between sending
            periodic resident set size updates. By default, every 10
            milliseconds a record is written that contains the current
            timestamp and the total number of bytes of virtual memory allocated
            by the process. These records are used to create the graph of
            memory usage over time that appears at the top of the flame graph,
            for instance. This parameter lets you adjust the frequency between
            updates, though you shouldn't need to change it.
        file_format (FileFormat): The format that should be used when writing
            to the capture file. See the `FileFormat` documentation for a list
            of supported file formats and their limitations.
    """
    cdef bool _native_traces
    cdef unsigned int _memory_interval_ms
    cdef bool _follow_fork
    cdef bool _trace_python_allocators
    cdef object _previous_profile_func
    cdef object _previous_thread_profile_func
    cdef unique_ptr[RecordWriter] _writer

    cdef unique_ptr[Sink] _make_writer(self, destination) except*:
        # Creating a Sink can raise Python exceptions (if is interrupted by signal
        # handlers). If this happens, this method will propagate the appropriate exception.
        if isinstance(destination, FileDestination):
            is_dev_null = False
            with contextlib.suppress(OSError):
                if pathlib.Path("/dev/null").samefile(destination.path):
                    is_dev_null = True

            if is_dev_null:
                return unique_ptr[Sink](new NullSink())
            return unique_ptr[Sink](new FileSink(os.fsencode(destination.path),
                                                 destination.overwrite,
                                                 destination.compress_on_exit))

        elif isinstance(destination, SocketDestination):
            return unique_ptr[Sink](new SocketSink(destination.address, destination.server_port))
        else:
            raise TypeError("destination must be a SocketDestination or FileDestination")

    def __cinit__(self, object file_name=None, *, object destination=None,
                  bool native_traces=False, unsigned int memory_interval_ms = 10,
                  bool follow_fork=False, bool trace_python_allocators=False,
                  FileFormat file_format=FileFormat.ALL_ALLOCATIONS):
        if (file_name, destination).count(None) != 1:
            raise TypeError("Exactly one of 'file_name' or 'destination' argument must be specified")

        cdef cppstring command_line = " ".join(sys.argv)
        self._native_traces = native_traces
        self._memory_interval_ms = memory_interval_ms
        self._follow_fork = follow_fork
        self._trace_python_allocators = trace_python_allocators

        if file_name is not None:
            destination = FileDestination(path=file_name)

        if not isinstance(destination, FileDestination):
            if follow_fork:
                raise RuntimeError("follow_fork requires an output file")

            if file_format != FileFormat.ALL_ALLOCATIONS:
                raise RuntimeError("AGGREGATED_ALLOCATIONS requires an output file")

        self._writer = move(
            createRecordWriter(
                move(self._make_writer(destination)),
                command_line,
                native_traces,
                file_format,
                trace_python_allocators,
            )
        )

    @cython.profile(False)
    def __enter__(self):
        cdef unique_ptr[RecordWriter] writer
        with tracker_creation_lock:
            if NativeTracker.getTracker() != NULL:
                raise RuntimeError("No more than one Tracker instance can be active at the same time")

            if self._writer == NULL:
                raise RuntimeError("Attempting to use stale output handle")
            writer = move(self._writer)

            for attr in ("_name", "_ident"):
                assert not hasattr(threading.Thread, attr)
                setattr(
                    threading.Thread,
                    attr,
                    ThreadNameInterceptor(attr, NativeTracker.registerThreadNameById),
                )

            self._previous_profile_func = sys.getprofile()
            self._previous_thread_profile_func = threading._profile_hook
            threading.setprofile(start_thread_trace)

            if "greenlet" in sys.modules:
                NativeTracker.beginTrackingGreenlets()

            NativeTracker.createTracker(
                move(writer),
                self._native_traces,
                self._memory_interval_ms,
                self._follow_fork,
                self._trace_python_allocators,
            )
            return self

    @cython.profile(False)
    def __exit__(self, exc_type, exc_value, exc_traceback):
        with tracker_creation_lock:
            NativeTracker.destroyTracker()
            sys.setprofile(self._previous_profile_func)
            threading.setprofile(self._previous_thread_profile_func)

            for attr in ("_name", "_ident"):
                delattr(threading.Thread, attr)


def start_thread_trace(frame, event, arg):
    if event in {"call", "c_call"}:
        install_trace_function()
    return start_thread_trace


def greenlet_trace_function(event, args):
    if event in {"switch", "throw"}:
        NativeTracker.handleGreenletSwitch(args[0], args[1])


def print_greenlet_warning():
    pprint(
        ":warning: [bold red]Memray support for Greenlet is experimental[/] :warning:\n"
        "[yellow]Please report any issues at https://github.com/bloomberg/memray/issues[/]\n"
        "\n",
        file=sys.stderr,
    )


cdef millis_to_dt(millis):
    return datetime.fromtimestamp(millis // 1000).replace(
        microsecond=millis % 1000 * 1000).astimezone()


cdef _create_metadata(header, peak_memory):
    stats = header["stats"]
    allocator_id_to_name = {
        PythonAllocatorType.PYTHON_ALLOCATOR_PYMALLOC: "pymalloc",
        PythonAllocatorType.PYTHON_ALLOCATOR_PYMALLOC_DEBUG: "pymalloc debug",
        PythonAllocatorType.PYTHON_ALLOCATOR_MALLOC: "malloc",
        PythonAllocatorType.PYTHON_ALLOCATOR_OTHER: "unknown",
    }
    return Metadata(
        start_time=millis_to_dt(stats["start_time"]),
        end_time=millis_to_dt(stats["end_time"]),
        total_allocations=stats["n_allocations"],
        total_frames=stats["n_frames"],
        peak_memory=peak_memory,
        command_line=header["command_line"],
        pid=header["pid"],
        main_thread_id=header["main_tid"],
        python_allocator=allocator_id_to_name[header["python_allocator"]],
        has_native_traces=header["native_traces"],
        trace_python_allocators=header["trace_python_allocators"],
        file_format=FileFormat(header["file_format"]),
    )


cdef class ProgressIndicator:
    cdef bool _report_progress
    cdef object _indicator
    cdef object _context_manager
    cdef object _task
    cdef object _task_description
    cdef object _total
    cdef size_t _cumulative_num_processed
    cdef size_t _update_interval
    cdef size_t _ns_between_refreshes
    cdef timespec _next_refresh

    def __init__(self,
        str task_description,
        object total,
        bool report_progress=True,
        size_t refresh_per_second=10,
    ):
        self._report_progress = report_progress
        self._total = total
        self._cumulative_num_processed = 0
        # Only check the elapsed time every N records
        self._update_interval = 100_000
        self._ns_between_refreshes = 1_000_000_000 // refresh_per_second
        self._next_refresh.tv_sec = 0
        self._next_refresh.tv_nsec = 0
        self._task_description = task_description
        self._task = None
        self._context_manager = None
        if report_progress:
            self._indicator = Progress(
                SpinnerColumn(),
                *Progress.get_default_columns(),
                auto_refresh=False,
                transient=True,
            )

    def __enter__(self):
        if not self._report_progress:
            return self
        self._context_manager = self._indicator.__enter__()
        self._task = self._context_manager.add_task(
            f"[cyan]{self._task_description}...",
            total=self._total
        )
        return self

    def __exit__(self, type, value, traceback):
        if not self._report_progress:
            return
        self._context_manager.update(self._task, completed=self._cumulative_num_processed)
        return self._context_manager.__exit__(type, value, traceback)

    cdef bool _time_for_refresh(self):
        cdef timespec now
        cdef int rc = clock_gettime(CLOCK_MONOTONIC, &now)

        if 0 != rc:
            return True

        if now.tv_sec > self._next_refresh.tv_sec or (
            now.tv_sec == self._next_refresh.tv_sec
            and now.tv_nsec > self._next_refresh.tv_nsec
        ):
            self._next_refresh = now
            self._next_refresh.tv_nsec += self._ns_between_refreshes
            while self._next_refresh.tv_nsec > 1_000_000_000:
                self._next_refresh.tv_nsec -= 1_000_000_000
                self._next_refresh.tv_sec += 1
            return True

        return False

    cdef update(self, size_t n_processed):
        self._cumulative_num_processed += n_processed
        if not self._report_progress:
            return
        if self._cumulative_num_processed % self._update_interval == 0:
            if self._time_for_refresh():
                assert(self._context_manager is not None)
                self._context_manager.update(
                    self._task, completed=self._cumulative_num_processed
                )
                self._context_manager.refresh()

    @property
    def num_processed(self):
        return self._cumulative_num_processed


cdef class FileReader:
    cdef cppstring _path

    cdef object _file
    cdef vector[_MemorySnapshot] _memory_snapshots
    cdef HighWatermark _high_watermark
    cdef object _header
    cdef bool _report_progress
    cdef size_t _memory_snapshot_stride

    def __cinit__(self, object file_name, *, bool report_progress=False, int max_memory_records=10000):
        try:
            self._file = open(file_name)
        except OSError as exc:
            raise OSError(f"Could not open file {file_name}: {exc.strerror}") from None

        if platform.system() == "Linux":
            self._path = "/proc/self/fd/" + str(self._file.fileno())
        else:
            self._path = str(file_name)
        self._report_progress = report_progress

        # Initial pass to populate _header, _high_watermark, and _memory_snapshots.
        cdef shared_ptr[RecordReader] reader_sp = make_shared[RecordReader](
            unique_ptr[FileSource](new FileSource(self._path)),
            False
        )
        cdef RecordReader* reader = reader_sp.get()

        self._header = reader.getHeader()
        stats = self._header["stats"]

        n_memory_snapshots_approx = 2048
        if 0 < stats["start_time"] < stats["end_time"]:
            n_memory_snapshots_approx = (stats["end_time"] - stats["start_time"]) / 10

        if n_memory_snapshots_approx > max_memory_records:
            n_memory_snapshots_approx = max_memory_records
        self._memory_snapshots.reserve(n_memory_snapshots_approx)

        cdef object total = stats['n_allocations'] or None
        cdef HighWatermarkFinder finder

        cdef ProgressIndicator progress_indicator = ProgressIndicator(
            "Calculating high watermark",
            total=total,
            report_progress=self._report_progress
        )
        self._memory_snapshot_stride = 0
        cdef MemoryRecord memory_record
        with progress_indicator:
            while True:
                PyErr_CheckSignals()
                ret = reader.nextRecord()
                if ret == RecordResult.RecordResultAllocationRecord:
                    finder.processAllocation(reader.getLatestAllocation())
                    progress_indicator.update(1)
                elif ret == RecordResult.RecordResultAggregatedAllocationRecord:
                    finder.processAllocation(
                        reader.getLatestAggregatedAllocation().contributionToHighWaterMark()
                    )
                    progress_indicator.update(1)
                elif ret == RecordResult.RecordResultMemoryRecord:
                    memory_record = reader.getLatestMemoryRecord()
                    self._memory_snapshots.push_back(
                        _MemorySnapshot(
                            memory_record.ms_since_epoch,
                            memory_record.rss,
                            finder.getCurrentWatermark(),
                        )
                    )
                elif ret == RecordResult.RecordResultMemorySnapshot:
                    self._memory_snapshots.push_back(reader.getLatestMemorySnapshot())
                else:
                    break

        if len(self._memory_snapshots) > max_memory_records:
            self._memory_snapshot_stride = int(ceil(<double>len(self._memory_snapshots) / max_memory_records))
            self._memory_snapshots = self._memory_snapshots[::self._memory_snapshot_stride]
        self._high_watermark = finder.getHighWatermark()
        stats["n_allocations"] = progress_indicator.num_processed

    def __dealloc__(self):
        self.close()

    cpdef close(self):
        if self._file is not None:
            file = self._file
            self._file = None
            file.close()

    cdef void _ensure_not_closed(self) except *:
        if self._file is None:
            raise ValueError("Operation on a closed FileReader")

    @property
    def closed(self):
        return self._file is None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.close()

    def _reaggregate_allocations(
        self, size_t records_to_process, bool merge_threads, bool leaks
    ):
        """Aggregate records from an AGGREGATED_ALLOCATIONS capture file.

        An extra aggregation pass is still needed to account for merge_threads,
        as well as (for now at least) different location key formats.
        """
        cdef AggregatedCaptureReaggregator aggregator
        cdef shared_ptr[RecordReader] reader_sp = make_shared[RecordReader](
            unique_ptr[FileSource](new FileSource(self._path))
        )
        cdef RecordReader* reader = reader_sp.get()

        cdef ProgressIndicator progress_indicator = ProgressIndicator(
            "Processing allocation records",
            total=records_to_process,
            report_progress=self._report_progress
        )

        cdef AggregatedAllocation record
        with progress_indicator:
            while True:
                PyErr_CheckSignals()
                ret = reader.nextRecord()
                if ret == RecordResult.RecordResultAggregatedAllocationRecord:
                    record = reader.getLatestAggregatedAllocation()
                    if leaks:
                        aggregator.addAllocation(record.contributionToLeaks())
                    else:
                        aggregator.addAllocation(record.contributionToHighWaterMark())
                    records_to_process -= 1
                    progress_indicator.update(1)
                elif ret == RecordResult.RecordResultMemorySnapshot:
                    pass
                else:
                    assert ret != RecordResult.RecordResultMemoryRecord
                    assert ret != RecordResult.RecordResultAllocationRecord
                    break

        for elem in Py_ListFromSnapshotAllocationRecords(
            aggregator.getSnapshotAllocations(merge_threads)
        ):
            alloc = AllocationRecord(elem)
            (<AllocationRecord> alloc)._reader = reader_sp
            yield alloc

        reader.close()

    def _aggregate_allocations(self, size_t records_to_process, bool merge_threads,
                               size_t temporary_buffer_size=0):
        cdef unique_ptr[AbstractAggregator] the_aggregator
        if temporary_buffer_size:
            the_aggregator.reset(
                new TemporaryAllocationsAggregator(temporary_buffer_size)
            )
        else:
            the_aggregator.reset(new SnapshotAllocationAggregator())
        cdef AbstractAggregator* aggregator = the_aggregator.get()

        cdef shared_ptr[RecordReader] reader_sp = make_shared[RecordReader](
            unique_ptr[FileSource](new FileSource(self._path))
        )
        cdef RecordReader* reader = reader_sp.get()

        cdef ProgressIndicator progress_indicator = ProgressIndicator(
            "Processing allocation records",
            total=records_to_process,
            report_progress=self._report_progress
        )

        with progress_indicator:
            while records_to_process > 0:
                PyErr_CheckSignals()
                ret = reader.nextRecord()
                if ret == RecordResult.RecordResultAllocationRecord:
                    aggregator.addAllocation(reader.getLatestAllocation())
                    records_to_process -= 1
                    progress_indicator.update(1)
                elif ret == RecordResult.RecordResultMemoryRecord:
                    pass
                else:
                    assert ret != RecordResult.RecordResultMemorySnapshot
                    assert ret != RecordResult.RecordResultAggregatedAllocationRecord
                    break

        for elem in Py_ListFromSnapshotAllocationRecords(
            aggregator.getSnapshotAllocations(merge_threads)
        ):
            alloc = AllocationRecord(elem)
            (<AllocationRecord> alloc)._reader = reader_sp
            yield alloc

        reader.close()

    def get_high_watermark_allocation_records(self, merge_threads=True):
        self._ensure_not_closed()
        if self._header["file_format"] == FileFormat.AGGREGATED_ALLOCATIONS:
            yield from self._reaggregate_allocations(
                self._header["stats"]["n_allocations"],
                merge_threads,
                leaks=False,
            )
            return

        # If allocation 0 caused the peak, we need to process 1 record, etc
        cdef size_t max_records = self._high_watermark.index + 1
        yield from self._aggregate_allocations(max_records, merge_threads)

    def get_leaked_allocation_records(self, merge_threads=True):
        self._ensure_not_closed()
        if self._header["file_format"] == FileFormat.AGGREGATED_ALLOCATIONS:
            yield from self._reaggregate_allocations(
                self._header["stats"]["n_allocations"],
                merge_threads,
                leaks=True,
            )
            return

        cdef size_t max_records = self._header["stats"]["n_allocations"]
        yield from self._aggregate_allocations(max_records, merge_threads)

    def get_temporary_allocation_records(self, merge_threads=True, threshold=1):
        self._ensure_not_closed()
        if self._header["file_format"] == FileFormat.AGGREGATED_ALLOCATIONS:
            raise NotImplementedError(
                "Can't find temporary allocations using a pre-aggregated capture file."
            )

        cdef size_t max_records = self._header["stats"]["n_allocations"]
        yield from self._aggregate_allocations(
            max_records,
            merge_threads,
            temporary_buffer_size=threshold + 1,
        )

    def get_temporal_allocation_records(self, merge_threads=True):
        self._ensure_not_closed()
        if self._header["file_format"] == FileFormat.AGGREGATED_ALLOCATIONS:
            raise NotImplementedError(
                "Can't get allocation history using a pre-aggregated capture file."
            )

        cdef shared_ptr[RecordReader] reader_sp = make_shared[RecordReader](
            unique_ptr[FileSource](new FileSource(self._path))
        )
        cdef RecordReader* reader = reader_sp.get()

        cdef size_t records_to_process = self._header["stats"]["n_allocations"]
        cdef ProgressIndicator progress_indicator = ProgressIndicator(
            "Processing allocation records",
            total=records_to_process,
            report_progress=self._report_progress
        )

        cdef AllocationLifetimeAggregator aggregator
        cdef _Allocation allocation
        cdef int memory_records_seen = 0

        with progress_indicator:
            while records_to_process > 0:
                PyErr_CheckSignals()
                ret = reader.nextRecord()
                if ret == RecordResult.RecordResultAllocationRecord:
                    allocation = reader.getLatestAllocation()
                    if merge_threads:
                        allocation.tid = NO_THREAD_INFO
                    aggregator.addAllocation(allocation)
                    records_to_process -= 1
                    progress_indicator.update(1)
                elif ret == RecordResult.RecordResultMemoryRecord:
                    memory_records_seen += 1
                    if self._memory_snapshot_stride and memory_records_seen % self._memory_snapshot_stride != 0:
                        continue
                    aggregator.captureSnapshot()
                else:
                    assert ret != RecordResult.RecordResultMemorySnapshot
                    assert ret != RecordResult.RecordResultAggregatedAllocationRecord
                    break

        cdef TemporalAllocationGenerator gen = TemporalAllocationGenerator()
        gen.setup(move(aggregator.generateIndex()), reader_sp)
        yield from gen

    def get_temporal_high_water_mark_allocation_records(self, merge_threads=True):
        self._ensure_not_closed()
        if self._header["file_format"] == FileFormat.AGGREGATED_ALLOCATIONS:
            raise NotImplementedError(
                "Can't get allocation history using a pre-aggregated capture file."
            )

        cdef shared_ptr[RecordReader] reader_sp = make_shared[RecordReader](
            unique_ptr[FileSource](new FileSource(self._path))
        )
        cdef RecordReader* reader = reader_sp.get()

        cdef size_t records_to_process = self._header["stats"]["n_allocations"]
        cdef ProgressIndicator progress_indicator = ProgressIndicator(
            "Processing allocation records",
            total=records_to_process,
            report_progress=self._report_progress
        )

        cdef HighWaterMarkAggregator aggregator
        cdef _Allocation allocation

        with progress_indicator:
            while records_to_process > 0:
                PyErr_CheckSignals()
                ret = reader.nextRecord()
                if ret == RecordResult.RecordResultAllocationRecord:
                    allocation = reader.getLatestAllocation()
                    if merge_threads:
                        allocation.tid = 0
                    aggregator.addAllocation(allocation)
                    records_to_process -= 1
                    progress_indicator.update(1)
                elif ret == RecordResult.RecordResultMemoryRecord:
                    aggregator.captureSnapshot()
                else:
                    assert ret != RecordResult.RecordResultMemorySnapshot
                    assert ret != RecordResult.RecordResultAggregatedAllocationRecord
                    break

        cdef TemporalAllocationGenerator gen = TemporalAllocationGenerator()
        gen.setup(move(aggregator.generateIndex()), reader_sp)
        hwm_by_snapshot = aggregator.highWaterMarkBytesBySnapshot()
        return gen, hwm_by_snapshot

    def get_allocation_records(self):
        self._ensure_not_closed()
        if self._header["file_format"] == FileFormat.AGGREGATED_ALLOCATIONS:
            raise NotImplementedError(
                "Can't get all allocations from a pre-aggregated capture file."
            )

        cdef shared_ptr[RecordReader] reader_sp = make_shared[RecordReader](
            unique_ptr[FileSource](new FileSource(self._path))
        )
        cdef RecordReader* reader = reader_sp.get()

        while True:
            PyErr_CheckSignals()
            ret = reader.nextRecord()
            if ret == RecordResult.RecordResultAllocationRecord:
                alloc = AllocationRecord(reader.getLatestAllocation().toPythonObject())
                (<AllocationRecord> alloc)._reader = reader_sp
                yield alloc
            elif ret == RecordResult.RecordResultMemoryRecord:
                pass
            elif ret == RecordResult.RecordResultMemorySnapshot:
                pass
            else:
                break

        reader.close()

    def get_memory_snapshots(self):
        for record in self._memory_snapshots:
            yield MemorySnapshot(record.ms_since_epoch, record.rss, record.heap)

    @property
    def metadata(self):
        return _create_metadata(self._header, self._high_watermark.peak_memory)


def compute_statistics(
    file_name,
    *,
    report_progress=False,
    num_largest=5,
):
    cdef shared_ptr[RecordReader] reader_sp = make_shared[RecordReader](
        unique_ptr[FileSource](new FileSource(file_name))
    )
    cdef RecordReader* reader = reader_sp.get()

    cdef header = reader.getHeader()
    total = header["stats"]["n_allocations"] or None

    if header["file_format"] == FileFormat.AGGREGATED_ALLOCATIONS:
        raise NotImplementedError(
            "Can't compute statistics using a pre-aggregated capture file."
        )

    cdef AllocationStatsAggregator aggregator
    cdef ProgressIndicator progress_indicator = ProgressIndicator(
        "Computing statistics",
        total=total,
        report_progress=report_progress,
    )
    with progress_indicator:
        while True:
            PyErr_CheckSignals()
            ret = reader.nextRecord()
            if ret == RecordResult.RecordResultAllocationRecord:
                aggregator.addAllocation(
                    reader.getLatestAllocation(),
                    reader.getLatestPythonFrameId(reader.getLatestAllocation()),
                )
                progress_indicator.update(1)
            elif ret == RecordResult.RecordResultMemoryRecord:
                pass
            elif ret == RecordResult.RecordResultMemorySnapshot:
                pass
            else:
                assert ret != RecordResult.RecordResultMemorySnapshot
                assert ret != RecordResult.RecordResultAggregatedAllocationRecord
                break

    # Ignore the n_allocations in the header, use our observed value.
    header["stats"]["n_allocations"] = progress_indicator.num_processed

    # Convert allocation counts by allocator/by size to Python dicts.
    cdef dict tmp = aggregator.allocationCountByAllocator()
    allocation_count_by_allocator = {AllocatorType(k).name: v for k, v in tmp.items()}
    cdef dict allocation_count_by_size = aggregator.allocationCountBySize();

    # Convert top locations by bytes allocated/by allocation count to dicts
    unknown = ("<unknown>", "<unknown>", 0)

    top_locations_by_size = [
        ((reader.Py_GetFrame(size_and_loc.second) or unknown), size_and_loc.first)
        for size_and_loc in aggregator.topLocationsBySize(num_largest)
    ]

    top_locations_by_count = [
        ((reader.Py_GetFrame(count_and_loc.second) or unknown), count_and_loc.first)
        for count_and_loc in aggregator.topLocationsByCount(num_largest)
    ]

    # And we're done!
    cdef uint64_t peak_memory = aggregator.peakBytesAllocated()
    return Stats(
        metadata=_create_metadata(header, peak_memory),
        total_num_allocations=aggregator.totalAllocations(),
        total_memory_allocated=aggregator.totalBytesAllocated(),
        peak_memory_allocated=peak_memory,
        allocation_count_by_size=allocation_count_by_size,
        allocation_count_by_allocator=allocation_count_by_allocator,
        top_locations_by_size=top_locations_by_size,
        top_locations_by_count=top_locations_by_count,
    )


def dump_all_records(object file_name):
    cdef str path = str(file_name)
    if not pathlib.Path(path).exists():
        raise IOError(f"No such file: {path}")

    cdef shared_ptr[RecordReader] _reader = make_shared[RecordReader](
            unique_ptr[FileSource](new FileSource(path)))
    _reader.get().dumpAllRecords()


cdef class SocketReader:
    cdef BackgroundSocketReader* _impl
    cdef shared_ptr[RecordReader] _reader
    cdef object _header
    cdef object _port

    def __cinit__(self, int port):
        self._impl = NULL

    def __init__(self, port: int):
        self._header = {}
        self._port = port

    cdef _teardown(self):
        with nogil:
            del self._impl
        self._impl = NULL

    cdef unique_ptr[SocketSource] _make_source(self) except*:
        # Creating a SocketSource can raise Python exceptions (if is interrupted by signal
        # handlers). If this happens, this method will propagate the appropriate exception.
        # We cannot use make_unique or C++ exceptions from SocketSource() won't be caught.
        cdef SocketSource* source = new SocketSource(self._port)
        return unique_ptr[SocketSource](source)

    def __enter__(self):
        if self._impl is not NULL:
            raise ValueError(
                "Can not enter the context of a SocketReader object more than "
                "once, at the same time."
            )

        self._reader = make_shared[RecordReader](move(self._make_source()))
        self._header = self._reader.get().getHeader()

        self._impl = new BackgroundSocketReader(self._reader)
        self._impl.start()

        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        assert self._impl is not NULL

        self._teardown()
        self._reader.get().close()

    def __dealloc__(self):
        if self._impl is not NULL:
            self._teardown()

    @property
    def command_line(self):
        if not self._header:
            return None
        return self._header["command_line"]

    @property
    def is_active(self):
        if self._impl == NULL:
            return False
        return self._impl.is_active()

    @property
    def pid(self):
        if not self._header:
            return None
        return self._header["pid"]

    @property
    def has_native_traces(self):
        if not self._header:
            return False
        return self._header["native_traces"]

    def get_current_snapshot(self, *, bool merge_threads):
        if self._impl is NULL:
            return

        snapshot_allocations = self._impl.Py_GetSnapshotAllocationRecords(merge_threads=merge_threads)
        for elem in snapshot_allocations:
            alloc = AllocationRecord(elem)
            (<AllocationRecord> alloc)._reader = self._reader
            yield alloc

cpdef enum SymbolicSupport:
    NONE = 1
    FUNCTION_NAME_ONLY = 2
    TOTAL = 3

def get_symbolic_support():
    locations = unwindHere()
    for location in locations:
        function, file, line = location.split(":")
        if function != "_PyEval_EvalFrameDefault":
            continue
        if not file:
            return SymbolicSupport.FUNCTION_NAME_ONLY
        return SymbolicSupport.TOTAL
    return SymbolicSupport.NONE


cdef extern from "<dlfcn.h>":
    int _RTLD_NOW "RTLD_NOW"
    void* _RTLD_DEFAULT "RTLD_DEFAULT"


RTLD_NOW = _RTLD_NOW
RTLD_DEFAULT = <long long>_RTLD_DEFAULT


cdef extern from "snapshot.h":
    """
    std::vector<memray::tracking_api::AggregatedAllocation>
    collectAllocations(const memray::api::HighWaterMarkAggregator& aggregator)
    {
        std::vector<memray::tracking_api::AggregatedAllocation> ret;
        aggregator.visitAllocations([&](const memray::tracking_api::AggregatedAllocation& agg) {
            if (agg.n_allocations_in_high_water_mark || agg.n_allocations_leaked) {
                ret.push_back(agg);
            }
            return true;
        });
        return ret;
    }
    """
    vector[AggregatedAllocation] collectAllocations(HighWaterMarkAggregator) except+


cdef class HighWaterMarkAggregatorTestHarness:
    cdef HighWaterMarkAggregator aggregator

    def add_allocation(
        self,
        tid,
        address,
        size,
        allocator,
        native_frame_id,
        frame_index,
        native_segment_generation,
    ):
        cdef _Allocation allocation
        allocation.tid = tid
        allocation.address = address
        allocation.size = size
        allocation.allocator = <Allocator><int>allocator
        allocation.native_frame_id = native_frame_id
        allocation.frame_index = frame_index
        allocation.native_segment_generation = native_segment_generation
        allocation.n_allocations = 1
        self.aggregator.addAllocation(allocation)

    def capture_snapshot(self):
        return self.aggregator.captureSnapshot()

    def high_water_mark_bytes_by_snapshot(self):
        return self.aggregator.highWaterMarkBytesBySnapshot()

    def get_current_heap_size(self):
        return self.aggregator.getCurrentHeapSize()

    def get_temporal_allocations(self):
        cdef shared_ptr[RecordReader] reader
        cdef TemporalAllocationGenerator gen = TemporalAllocationGenerator()
        gen.setup(move(self.aggregator.generateIndex()), reader)
        yield from gen

    def get_allocations(self):
        ret = []
        for allocation in collectAllocations(self.aggregator):
            ret.append(
                dict(
                    tid=allocation.tid,
                    allocator=AllocatorType(<int>allocation.allocator),
                    native_frame_id=allocation.native_frame_id,
                    frame_index=allocation.frame_index,
                    native_segment_generation=allocation.native_segment_generation,
                    n_allocations_in_high_water_mark=allocation.n_allocations_in_high_water_mark,
                    n_allocations_leaked=allocation.n_allocations_leaked,
                    bytes_in_high_water_mark=allocation.bytes_in_high_water_mark,
                    bytes_leaked=allocation.bytes_leaked,
                )
            )
        return ret


cdef class AllocationLifetimeAggregatorTestHarness:
    cdef AllocationLifetimeAggregator aggregator

    def add_allocation(
        self,
        tid,
        address,
        size,
        allocator,
        native_frame_id,
        frame_index,
        native_segment_generation,
    ):
        cdef _Allocation allocation
        allocation.tid = tid
        allocation.address = address
        allocation.size = size
        allocation.allocator = <Allocator><int>allocator
        allocation.native_frame_id = native_frame_id
        allocation.frame_index = frame_index
        allocation.native_segment_generation = native_segment_generation
        allocation.n_allocations = 1
        self.aggregator.addAllocation(allocation)

    def capture_snapshot(self):
        return self.aggregator.captureSnapshot()

    def get_allocations(self):
        cdef shared_ptr[RecordReader] reader
        cdef TemporalAllocationGenerator gen = TemporalAllocationGenerator()
        gen.setup(move(self.aggregator.generateIndex()), reader)
        yield from gen
