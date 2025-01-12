import enum
from pathlib import Path
from types import FrameType
from types import TracebackType
from typing import Any
from typing import Iterable
from typing import Iterator
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Tuple
from typing import Type
from typing import Union
from typing import overload

from memray._destination import FileDestination as FileDestination
from memray._destination import SocketDestination as SocketDestination
from memray._metadata import Metadata
from memray._stats import Stats

from . import Destination

PythonStackElement = Tuple[str, str, int]
NativeStackElement = Tuple[str, str, int]
MemorySnapshot = NamedTuple(
    "MemorySnapshot", [("time", int), ("rss", int), ("heap", int)]
)

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
        max_stacks: Optional[int] = None,
    ) -> List[Union[PythonStackElement, NativeStackElement]]: ...
    def native_stack_trace(
        self, max_stacks: Optional[int] = None
    ) -> List[NativeStackElement]: ...
    def stack_trace(
        self, max_stacks: Optional[int] = None
    ) -> List[PythonStackElement]: ...
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
        max_stacks: Optional[int] = None,
    ) -> List[Union[PythonStackElement, NativeStackElement]]: ...
    def native_stack_trace(
        self, max_stacks: Optional[int] = None
    ) -> List[NativeStackElement]: ...
    def stack_trace(
        self, max_stacks: Optional[int] = None
    ) -> List[PythonStackElement]: ...
    def __eq__(self, other: Any) -> Any: ...
    def __hash__(self) -> Any: ...
    intervals: List[Interval]

class AllocatorType(enum.IntEnum):
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

class FileFormat(enum.IntEnum):
    ALL_ALLOCATIONS = 1
    AGGREGATED_ALLOCATIONS = 2

def start_thread_trace(frame: FrameType, event: str, arg: Any) -> None: ...

class FileReader:
    @property
    def metadata(self) -> Metadata: ...
    def __init__(
        self,
        file_name: Union[str, Path],
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
    ) -> Tuple[List[TemporalAllocationRecord], List[int]]: ...
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
        exctype: Optional[Type[BaseException]],
        excinst: Optional[BaseException],
        exctb: Optional[TracebackType],
    ) -> bool: ...
    @property
    def closed(self) -> bool: ...
    def close(self) -> None: ...

def compute_statistics(
    file_name: Union[str, Path],
    *,
    report_progress: bool = False,
    num_largest: int = 5,
) -> Stats: ...
def dump_all_records(file_name: Union[str, Path]) -> None: ...

class SocketReader:
    def __init__(self, port: int) -> None: ...
    def __enter__(self) -> "SocketReader": ...
    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        exc_traceback: Optional[TracebackType],
    ) -> Any: ...
    def get_current_snapshot(
        self, *, merge_threads: bool
    ) -> Iterator[AllocationRecord]: ...
    @property
    def command_line(self) -> Optional[str]: ...
    @property
    def is_active(self) -> bool: ...
    @property
    def pid(self) -> Optional[int]: ...
    @property
    def has_native_traces(self) -> bool: ...

class Tracker:
    @property
    def reader(self) -> FileReader: ...
    @overload
    def __init__(
        self,
        file_name: Union[Path, str],
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
        exctype: Optional[Type[BaseException]],
        excinst: Optional[BaseException],
        exctb: Optional[TracebackType],
    ) -> bool: ...

def greenlet_trace(event: str, args: Any) -> None: ...

class PymallocDomain(enum.IntEnum):
    PYMALLOC_RAW = 1
    PYMALLOC_MEM = 2
    PYMALLOC_OBJECT = 3

def size_fmt(num: int, suffix: str = "B") -> str: ...

class SymbolicSupport(enum.IntEnum):
    NONE = 1
    FUNCTION_NAME_ONLY = 2
    TOTAL = 3

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
