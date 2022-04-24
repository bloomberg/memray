import collections
import contextlib
import os
import pathlib
import sys

cimport cython

import threading
from datetime import datetime

from _memray.logging cimport setLogThreshold
from _memray.record_reader cimport RecordReader
from _memray.record_reader cimport RecordResult
from _memray.record_writer cimport RecordWriter
from _memray.records cimport Allocation as _Allocation
from _memray.records cimport MemoryRecord as _MemoryRecord
from _memray.sink cimport FileSink
from _memray.sink cimport NullSink
from _memray.sink cimport Sink
from _memray.sink cimport SocketSink
from _memray.snapshot cimport HighWatermark
from _memray.snapshot cimport HighWatermarkFinder
from _memray.snapshot cimport Py_GetSnapshotAllocationRecords
from _memray.socket_reader_thread cimport BackgroundSocketReader
from _memray.source cimport FileSource
from _memray.source cimport SocketSource
from _memray.tracking_api cimport Tracker as NativeTracker
from _memray.tracking_api cimport install_trace_function
from libcpp cimport bool
from libcpp.memory cimport make_shared
from libcpp.memory cimport make_unique
from libcpp.memory cimport shared_ptr
from libcpp.memory cimport unique_ptr
from libcpp.string cimport string as cppstring
from libcpp.utility cimport move
from libcpp.vector cimport vector

from ._destination import FileDestination
from ._destination import SocketDestination
from ._metadata import Metadata

include "_memray_test_utils.pyx"


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
    MEMALIGN = 6
    VALLOC = 7
    PVALLOC = 8
    MMAP = 9
    MUNMAP = 10

cpdef enum PythonAllocatorType:
    PYTHON_ALLOCATOR_PYMALLOC = 1
    PYTHON_ALLOCATOR_PYMALLOC_DEBUG = 2
    PYTHON_ALLOCATOR_MALLOC = 3
    PYTHON_ALLOCATOR_OTHER = 4

def size_fmt(num, suffix='B'):
    for unit in ['','K','M','G','T','P','E','Z']:
        if abs(num) < 1024.0:
            return f"{num:5.3f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Y{suffix}"

# Memray core

PYTHON_VERSION = (sys.version_info.major, sys.version_info.minor)

@cython.freelist(1024)
cdef class AllocationRecord:
    cdef object _tuple
    cdef object _stack_trace
    cdef object _native_stack_trace
    cdef shared_ptr[RecordReader] _reader

    def __init__(self, record):
        self._tuple = record
        self._stack_trace = None

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
    def thread_name(self):
        if self.tid == -1:
            return "merged thread"
        assert self._reader.get() != NULL, "Cannot get thread name without reader."
        cdef object name = self._reader.get().getThreadName(self.tid)
        thread_id = hex(self.tid)
        return f"{thread_id} ({name})" if name else f"{thread_id}"

    def stack_trace(self, max_stacks=None):
        assert self._reader.get() != NULL, "Cannot get stack trace without reader."
        if self._stack_trace is None:
            if max_stacks is None:
                self._stack_trace = self._reader.get().Py_GetStackFrame(self._tuple[4])
            else:
                self._stack_trace = self._reader.get().Py_GetStackFrame(self._tuple[4], max_stacks)
        return self._stack_trace

    def native_stack_trace(self, max_stacks=None):
        assert self._reader.get() != NULL, "Cannot get stack trace without reader."
        if self._native_stack_trace is None:
            if max_stacks is None:
                self._native_stack_trace = self._reader.get().Py_GetNativeStackFrame(
                        self._tuple[6], self._tuple[7])
            else:
                self._native_stack_trace = self._reader.get().Py_GetNativeStackFrame(
                        self._tuple[6], self._tuple[7], max_stacks)
        return self._native_stack_trace

    cdef _is_eval_frame(self, object symbol):
        return "_PyEval_EvalFrameDefault" in symbol

    def _pure_python_stack_trace(self, max_stacks):
        for frame in self.stack_trace(max_stacks):
            _, file, _ = frame
            if file.endswith(".pyx"):
                continue
            yield frame

    def hybrid_stack_trace(self, max_stacks=None):
        python_stack = tuple(self._pure_python_stack_trace(max_stacks))
        n_python_frames_left = len(python_stack) if python_stack else None
        python_stack = iter(python_stack)
        for native_frame in self.native_stack_trace(max_stacks):
            if n_python_frames_left == 0:
                break
            symbol, *_ = native_frame
            if self._is_eval_frame(symbol):
                python_frame =  next(python_stack)
                n_python_frames_left -= 1
                yield python_frame
            else:
                yield native_frame

    def __repr__(self):
        return (f"AllocationRecord<tid={hex(self.tid)}, address={hex(self.address)}, "
                f"size={'N/A' if not self.size else size_fmt(self.size)}, allocator={self.allocator!r}, "
                f"allocations={self.n_allocations}>")


MemoryRecord = collections.namedtuple("MemoryRecord", "time rss")

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
            argument must not be.
        native_traces (bool): Whether or not to capture native stack frames, in
            addition to Python stack frames (see :ref:`Native Tracking`).
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
    """
    cdef bool _native_traces
    cdef unsigned int _memory_interval_ms
    cdef bool _follow_fork
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
            return unique_ptr[Sink](new FileSink(os.fsencode(destination.path), destination.overwrite))

        elif isinstance(destination, SocketDestination):
            return unique_ptr[Sink](new SocketSink(destination.address, destination.server_port))
        else:
            raise TypeError("destination must be a SocketDestination or FileDestination")


    def __cinit__(self, object file_name=None, *, object destination=None,
                  bool native_traces=False, unsigned int memory_interval_ms = 10,
                  bool follow_fork=False):
        if (file_name, destination).count(None) != 1:
            raise TypeError("Exactly one of 'file_name' or 'destination' argument must be specified")

        cdef cppstring command_line = " ".join(sys.argv)
        self._native_traces = native_traces
        self._memory_interval_ms = memory_interval_ms
        self._follow_fork = follow_fork

        if file_name is not None:
            destination = FileDestination(path=file_name)

        if follow_fork and not isinstance(destination, FileDestination):
            raise RuntimeError("follow_fork requires an output file")

        self._writer = make_unique[RecordWriter](
                move(self._make_writer(destination)), command_line, native_traces
            )

    @cython.profile(False)
    def __enter__(self):

        if NativeTracker.getTracker() != NULL:
            raise RuntimeError("No more than one Tracker instance can be active at the same time")

        cdef unique_ptr[RecordWriter] writer
        if self._writer == NULL:
            raise RuntimeError("Attempting to use stale output handle")
        writer = move(self._writer)

        self._previous_profile_func = sys.getprofile()
        self._previous_thread_profile_func = threading._profile_hook
        threading.setprofile(start_thread_trace)

        NativeTracker.createTracker(
            move(writer),
            self._native_traces,
            self._memory_interval_ms,
            self._follow_fork,
        )
        return self

    @cython.profile(False)
    def __exit__(self, exc_type, exc_value, exc_traceback):
        NativeTracker.destroyTracker()
        sys.setprofile(self._previous_profile_func)
        threading.setprofile(self._previous_thread_profile_func)


def start_thread_trace(frame, event, arg):
    if event in {"call", "c_call"}:
        install_trace_function()
    return start_thread_trace


cdef class FileReader:
    cdef cppstring _path

    cdef shared_ptr[RecordReader] _reader
    cdef vector[_Allocation] _allocations
    cdef vector[_MemoryRecord] _memory_records
    cdef unique_ptr[HighWatermark] _high_watermark
    cdef bool _closed
    cdef object _header

    def __init__(self, object file_name):
        self._path = str(file_name)
        if not pathlib.Path(self._path).exists():
            raise IOError(f"No such file: {self._path}")
        self._reader = make_shared[RecordReader](unique_ptr[FileSource](new FileSource(self._path)))
        self._header: dict = self._reader.get().getHeader()
        self._populate_allocations()

    cdef void _populate_allocations(self):
        cdef RecordReader* reader = self._get_reader()

        stats = self._header["stats"]
        self._allocations.reserve(stats["n_allocations"])
        n_memory_records_approx = 2048
        if 0 < stats["start_time"] < stats["end_time"]:
            n_memory_records_approx = (stats["end_time"] - stats["start_time"]) / 10
        self._memory_records.reserve(n_memory_records_approx)

        while True:
            ret = reader.nextRecord()
            if ret == RecordResult.RecordResultAllocationRecord:
                self._allocations.push_back(reader.getLatestAllocation())
            elif ret == RecordResult.RecordResultMemoryRecord:
                self._memory_records.push_back(reader.getLatestMemoryRecord())
            else:
                break

    cdef RecordReader* _get_reader(self) except *:
        if self._reader.get() == NULL:
            raise ValueError("Operation on a closed FileReader")
        return self._reader.get()

    def close(self):
        cdef RecordReader* reader = self._get_reader()
        reader.close()

    cdef void _ensure_reader_is_open(self) except *:
        if not self._get_reader().isOpen():
            raise ValueError("Operation on a closed FileReader")

    @property
    def closed(self):
        return not self._get_reader().isOpen()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.close()

    def __dealloc__(self):
        self._reader.reset()
    
    def _yield_allocations(self, size_t index, merge_threads):
        for elem in Py_GetSnapshotAllocationRecords(
            self._allocations, index, merge_threads):
            alloc = AllocationRecord(elem)
            (<AllocationRecord> alloc)._reader = self._reader
            yield alloc
            self._ensure_reader_is_open()

    cdef inline HighWatermark* _get_high_watermark(self) except*:
        cdef HighWatermarkFinder finder
        if self._high_watermark == NULL:
            for record in self._allocations:
                finder.processAllocation(record)
            self._high_watermark = make_unique[HighWatermark](finder.getHighWatermark())
        return self._high_watermark.get()

    def get_high_watermark_allocation_records(self, merge_threads=True):
        self._ensure_reader_is_open()
        cdef HighWatermark* watermark = self._get_high_watermark()
        yield from self._yield_allocations(watermark.index, merge_threads)

    def get_leaked_allocation_records(self, merge_threads=True):
        self._ensure_reader_is_open()
        cdef size_t snapshot_index = self._allocations.size() - 1
        yield from self._yield_allocations(snapshot_index, merge_threads)

    def get_allocation_records(self):
        for record in self._allocations:
            alloc = AllocationRecord(record.toPythonObject())
            (<AllocationRecord> alloc)._reader = self._reader
            yield alloc

    def get_memory_records(self):
        for record in self._memory_records:
            yield MemoryRecord(record.ms_since_epoch, record.rss)

    @property
    def metadata(self):
        def millis_to_dt(millis) -> datetime:
            return datetime.fromtimestamp(millis // 1000).replace(
                microsecond=millis % 1000 * 1000)

        stats = self._header["stats"]
        allocator_id_to_name = {
            PythonAllocatorType.PYTHON_ALLOCATOR_PYMALLOC: "pymalloc",
            PythonAllocatorType.PYTHON_ALLOCATOR_PYMALLOC_DEBUG: "pymalloc debug",
            PythonAllocatorType.PYTHON_ALLOCATOR_MALLOC: "malloc",
            PythonAllocatorType.PYTHON_ALLOCATOR_OTHER: "unknown",
        }
        python_allocator = allocator_id_to_name[self._header["python_allocator"]]
        return Metadata(start_time=millis_to_dt(stats["start_time"]),
                        end_time=millis_to_dt(stats["end_time"]),
                        total_allocations=stats["n_allocations"],
                        total_frames=stats["n_frames"],
                        peak_memory=self._get_high_watermark().peak_memory,
                        command_line=self._header["command_line"],
                        pid=self._header["pid"],
                        python_allocator=python_allocator)

    @property
    def has_native_traces(self):
        return self._header["native_traces"]


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
