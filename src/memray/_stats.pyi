from dataclasses import dataclass

from ._memray import PythonStackElement
from ._metadata import Metadata

@dataclass
class Stats:
    metadata: Metadata
    total_num_allocations: int
    total_memory_allocated: int
    peak_memory_allocated: int
    allocation_count_by_size: dict[int, int]
    allocation_count_by_allocator: dict[str, int]
    top_locations_by_size: list[tuple[PythonStackElement, int]]
    top_locations_by_count: list[tuple[PythonStackElement, int]]
    top_allocations_by_module: list[tuple[str, int, int]]
    top_allocations_by_module_by_count: list[tuple[str, int, int]]
