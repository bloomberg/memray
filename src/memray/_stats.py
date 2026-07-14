from dataclasses import dataclass
from dataclasses import field
from typing import List
from typing import Tuple

from ._metadata import Metadata


@dataclass
class Stats:
    metadata: Metadata
    total_num_allocations: int
    total_memory_allocated: int
    peak_memory_allocated: int
    allocation_count_by_size: dict
    allocation_count_by_allocator: dict
    top_locations_by_size: list
    top_locations_by_count: list
    top_modules_by_allocation_size: List[Tuple[str, int, int]] = field(
        default_factory=list
    )
    top_modules_by_allocation_count: List[Tuple[str, int, int]] = field(
        default_factory=list
    )
