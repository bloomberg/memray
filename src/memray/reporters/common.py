from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict
from typing import Dict
from typing import Iterable
from typing import Optional
from typing import Set
from typing import Union

from memray._memray import AllocationRecord
from memray._memray import TemporalAllocationRecord


def format_thread_name(
    record: Union[AllocationRecord, TemporalAllocationRecord]
) -> str:
    if record.tid == -1:
        return "merged thread"
    name = record.thread_name
    thread_id = hex(record.tid)
    return f"{thread_id} ({name})" if name else f"{thread_id}"


@dataclass(frozen=True)
class Location:
    function: str
    file: str


@dataclass
class AllocationEntry:
    own_memory: int
    total_memory: int
    n_allocations: int
    thread_ids: Set[int]


def aggregate_allocations(
    allocations: Iterable[AllocationRecord],
    memory_threshold: float = float("inf"),
    native_traces: Optional[bool] = False,
) -> Dict[Location, AllocationEntry]:
    """Take allocation records and for each frame contained, record "own"
    allocations which happened on the frame, and sum up allocations on
    all of the child frames to calculate "total" allocations."""

    processed_allocations: DefaultDict[Location, AllocationEntry] = defaultdict(
        lambda: AllocationEntry(
            own_memory=0, total_memory=0, n_allocations=0, thread_ids=set()
        )
    )

    current_total = 0
    for allocation in allocations:
        if current_total >= memory_threshold:
            break
        current_total += allocation.size

        stack_trace = list(
            allocation.hybrid_stack_trace()
            if native_traces
            else allocation.stack_trace()
        )
        if not stack_trace:
            frame = processed_allocations[Location(function="???", file="???")]
            frame.total_memory += allocation.size
            frame.own_memory += allocation.size
            frame.n_allocations += allocation.n_allocations
            frame.thread_ids.add(allocation.tid)
            continue

        # Walk upwards and sum totals
        visited = set()
        for i, (function, file_name, _) in enumerate(stack_trace):
            location = Location(function=function, file=file_name)
            frame = processed_allocations[location]
            if location in visited:
                continue
            visited.add(location)
            if i == 0:
                frame.own_memory += allocation.size
            frame.total_memory += allocation.size
            frame.n_allocations += allocation.n_allocations
            frame.thread_ids.add(allocation.tid)
    return processed_allocations
