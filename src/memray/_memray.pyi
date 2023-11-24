import enum
from pathlib import Path
from types import FrameType
from types import TracebackType
from typing import Any
from typing import Iterable
from typing import Iterator
from typing import NamedTuple
from typing import overload

from memray._destination import FileDestination as FileDestination
from memray._destination import SocketDestination as SocketDestination
from memray._metadata import Metadata
from memray._stats import Stats

from . import Destination

PythonStackElement = tuple[str, str, int]
NativeStackElement = tuple[str, str, int]

class MemorySnapshot(NamedTuple):
    time: int
    rss: int
    heap: int

def set_log_level(level: int) -> None: ...

class AllocationRecord:
    @property
    def address(self) -> int: ...
    @property
    def allocator(self) -> int: ...
    @property
    def n_allocations(self) -> int: ...
    @property
    def size(self) -> int: ...
    @property
    def stack_id(self) -> int: ...
    @property
    def tid(self) -> int: ...
    @property
    def native_stack_id(self) -> int: ...
    @property
    def native_segment_generation(self) -> int: ...
    @property
    def thread_name(self) -> str: ...
    def hybrid_stack_trace(
        self,
        max_stacks: int | None = None,
    ) -> list[PythonStackElement | NativeStackElement]: ...
    def native_stack_trace(
        self, max_stacks: int | None = None
    ) -> list[NativeStackElement]: ...
    def stack_trace(
        self, max_stacks: int | None = None
    ) -> list[PythonStackElement]: ...
    def __eq__(self, other: Any) -> Any: ...
    def __ge__(self, other: Any) -> Any: ...
    def __gt__(self, other: Any) -> Any: ...
    def __hash__(self) -> Any: ...
    def __le__(self, other: Any) -> Any: ...
    def __lt__(self, other: Any) -> Any: ...
    def __ne__(self, other: Any) -> Any: ...

class Interval:
    def __init__(
        self,
        allocated_before_snapshot: int,
        deallocated_before_snapshot: int | None,
        n_allocations: int,
        n_bytes: int,
    ) -> None: ...
    def __eq__(self, other: Any) -> Any: ...
    allocated_before_snapshot: int
    deallocated_before_snapshot: int | None
    n_allocations: int
    n_bytes: int

class TemporalAllocationRecord:
    @property
    def allocator(self) -> int: ...
    @property
    def stack_id(self) -> int: ...
    @property
    def tid(self) -> int: ...
    @property
    def native_stack_id(self) -> int: ...
    @property
    def native_segment_generation(self) -> int: ...
    @property
    def thread_name(self) -> str: ...
    def hybrid_stack_trace(
        self,
        max_stacks: int | None = None,
    ) -> list[PythonStackElement | NativeStackElement]: ...
    def native_stack_trace(
        self, max_stacks: int | None = None
    ) -> list[NativeStackElement]: ...
    def stack_trace(
        self, max_stacks: int | None = None
    ) -> list[PythonStackElement]: ...
    def __eq__(self, other: Any) -> Any: ...
    def __hash__(self) -> Any: ...
    intervals: list[Interval]

class AllocatorType(enum.IntEnum):
    MALLOC: int
    FREE: int
    CALLOC: int
    REALLOC: int
    POSIX_MEMALIGN: int
    ALIGNED_ALLOC: int
    MEMALIGN: int
    VALLOC: int
    PVALLOC: int
    MMAP: int
    MUNMAP: int
    PYMALLOC_MALLOC: int
    PYMALLOC_CALLOC: int
    PYMALLOC_REALLOC: int
    PYMALLOC_FREE: int

class FileFormat(enum.IntEnum):
    ALL_ALLOCATIONS: int
    AGGREGATED_ALLOCATIONS: int

def start_thread_trace(frame: FrameType, event: str, arg: Any) -> None: ...

class FileReader:
    @property
    def metadata(self) -> Metadata: ...
    def __init__(
        self,
        file_name: str | Path,
        *,
        report_progress: bool = False,
        max_memory_records: int = 10000,
    ) -> None: ...
    def get_allocation_records(self) -> Iterable[AllocationRecord]: ...
    def get_temporal_allocation_records(
        self,
        merge_threads: bool,
    ) -> Iterable[TemporalAllocationRecord]: ...
    def get_temporal_high_water_mark_allocation_records(
        self,
        merge_threads: bool,
    ) -> tuple[list[TemporalAllocationRecord], list[int]]: ...
    def get_high_watermark_allocation_records(
        self,
        merge_threads: bool = ...,
    ) -> Iterable[AllocationRecord]: ...
    def get_leaked_allocation_records(
        self, merge_threads: bool = ...
    ) -> Iterable[AllocationRecord]: ...
    def get_temporary_allocation_records(
        self, merge_threads: bool = ..., threshold: int = ...
    ) -> Iterable[AllocationRecord]: ...
    def get_memory_snapshots(self) -> Iterable[MemorySnapshot]: ...
    def __enter__(self) -> Any: ...
    def __exit__(
        self,
        exctype: type[BaseException] | None,
        excinst: BaseException | None,
        exctb: TracebackType | None,
    ) -> bool: ...
    @property
    def closed(self) -> bool: ...
    def close(self) -> None: ...

def compute_statistics(
    file_name: str | Path,
    *,
    report_progress: bool = False,
    num_largest: int = 5,
) -> Stats: ...
def dump_all_records(file_name: str | Path) -> None: ...

class SocketReader:
    def __init__(self, port: int) -> None: ...
    def __enter__(self) -> SocketReader: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> Any: ...
    def get_current_snapshot(
        self, *, merge_threads: bool
    ) -> Iterator[AllocationRecord]: ...
    @property
    def command_line(self) -> str | None: ...
    @property
    def is_active(self) -> bool: ...
    @property
    def pid(self) -> int | None: ...
    @property
    def has_native_traces(self) -> bool: ...

class Tracker:
    @property
    def reader(self) -> FileReader: ...
    @overload
    def __init__(
        self,
        file_name: Path | str,
        *,
        native_traces: bool = ...,
        memory_interval_ms: int = ...,
        follow_fork: bool = ...,
        trace_python_allocators: bool = ...,
        file_format: FileFormat = ...,
    ) -> None: ...
    @overload
    def __init__(
        self,
        *,
        destination: Destination,
        native_traces: bool = ...,
        memory_interval_ms: int = ...,
        follow_fork: bool = ...,
        trace_python_allocators: bool = ...,
        file_format: FileFormat = ...,
    ) -> None: ...
    def __enter__(self) -> Any: ...
    def __exit__(
        self,
        exctype: type[BaseException] | None,
        excinst: BaseException | None,
        exctb: TracebackType | None,
    ) -> bool: ...

def greenlet_trace(event: str, args: Any) -> None: ...

class PymallocDomain(enum.IntEnum):
    PYMALLOC_RAW: int
    PYMALLOC_MEM: int
    PYMALLOC_OBJECT: int

def size_fmt(num: int, suffix: str = "B") -> str: ...

class SymbolicSupport(enum.IntEnum):
    NONE: int
    FUNCTION_NAME_ONLY: int
    TOTAL: int

def get_symbolic_support() -> SymbolicSupport: ...

RTLD_NOW: int
RTLD_DEFAULT: int

class HighWaterMarkAggregatorTestHarness:
    def add_allocation(
        self,
        tid: int,
        address: int,
        size: int,
        allocator: int,
        native_frame_id: int,
        frame_index: int,
        native_segment_generation: int,
    ) -> None: ...
    def capture_snapshot(self) -> None: ...
    def high_water_mark_bytes_by_snapshot(self) -> list[int]: ...
    def get_current_heap_size(self) -> int: ...
    def get_temporal_allocations(self) -> list[TemporalAllocationRecord]: ...
    def get_allocations(self) -> list[dict[str, int]]: ...

class AllocationLifetimeAggregatorTestHarness:
    def add_allocation(
        self,
        tid: int,
        address: int,
        size: int,
        allocator: int,
        native_frame_id: int,
        frame_index: int,
        native_segment_generation: int,
    ) -> None: ...
    def capture_snapshot(self) -> None: ...
    def get_allocations(self) -> list[TemporalAllocationRecord]: ...
