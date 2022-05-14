import heapq
import math
from collections import Counter
from dataclasses import dataclass
from dataclasses import field
from typing import IO
from typing import Dict
from typing import Generator
from typing import Iterable
from typing import List
from typing import Optional
from typing import Tuple

import rich

from memray import AllocationRecord
from memray import AllocatorType
from memray._memray import size_fmt


@dataclass
class _StatsData:
    total_memory_allocated: int = 0
    total_num_allocations: int = 0
    allocation_size_array: List[int] = field(default_factory=list)
    allocation_type_counter: Dict[str, int] = field(default_factory=dict)


def get_stats_data(data: Iterable[AllocationRecord]) -> _StatsData:
    shdata = _StatsData()
    shdata.total_num_allocations = sum(alloc.n_allocations for alloc in data)
    shdata.total_memory_allocated = int(sum(alloc.size for alloc in data))
    shdata.allocation_size_array = [alloc.size for alloc in data if alloc.size]
    shdata.allocation_type_counter = Counter(
        AllocatorType(alloc.allocator).name for alloc in data
    )

    # remove FREE and MUNMAP from allocation_type
    shdata.allocation_type_counter.pop("FREE", None)
    shdata.allocation_type_counter.pop("MUNMAP", None)

    return shdata


def get_top_allocations_by_size(
    data: Iterable[AllocationRecord], num_largest: int
) -> Generator[str, None, None]:
    for record in heapq.nlargest(num_largest, data, key=lambda rec: rec.size):
        stack_trace = record.stack_trace()
        strace_string = ""
        if stack_trace:
            (function, file, line), *_ = stack_trace
            strace_string = f"{function}:{file}:{line}"
        else:
            strace_string = "<stack trace unavailable>"

        yield f"{strace_string} -> {size_fmt(record.size)}"


def get_top_allocations_by_count(
    data: Iterable[AllocationRecord], num_largest: int
) -> Generator[str, None, None]:
    for record in heapq.nlargest(num_largest, data, key=lambda rec: rec.n_allocations):
        stack_trace = record.stack_trace()
        strace_string = ""
        if stack_trace:
            (function, file, line), *_ = stack_trace
            strace_string = f"{function}:{file}:{line}"
        else:
            strace_string = "<stack trace unavailable>"
        yield f"{strace_string} -> {record.n_allocations}"


def get_allocator_type_distribution(
    alloc_type_counter: Dict[str, int]
) -> Generator[str, None, None]:
    for alloc_type, alloc_value in sorted(
        alloc_type_counter.items(), key=lambda item: item[1], reverse=True
    ):
        yield f"{alloc_type}: {alloc_value}"


def get_histogram_databins(data: List[int], bins: int) -> List[Tuple[int, int]]:
    if bins <= 0:
        raise ValueError(f"Invalid input bins={bins}, should be greater than 0")

    low = math.log(min(data))
    high = math.log(max(data))
    it = map(math.log, filter(lambda number: number != 0, data))
    step = ((high - low) / bins) or low

    # Determine the upper bound in bytes for each bin
    steps = [int(math.exp(low + step * (i + 1))) for i in range(bins)]
    dist = Counter(min((x - low) // step, bins - 1) for x in it)
    return [(steps[b], dist[b]) for b in range(bins)]


def draw_histogram(data: List[int], bins: int, *, hist_scale_factor: int = 25) -> str:
    """
    @param data: list of allocation sizes
    @param bins: number of bins in the histogram
    @param hist_scale_factor: length of the largest bar in the histogram (# of chars)
    """
    if len(data) == 0:
        return "<no data for histogram>"
    if bins <= 0:
        raise ValueError(f"Invalid input bins={bins}, should be greater than 0")
    if hist_scale_factor <= 0:
        raise ValueError(
            f"Invalid input hist_scale_factor={hist_scale_factor},"
            " should be greater than 0"
        )

    data_bins = get_histogram_databins(data, bins=bins)
    max_data_bin = max([t[1] for t in data_bins])
    scaled_data_bins = [
        math.ceil((v / max_data_bin) * hist_scale_factor) for _, v in data_bins
    ]

    size_max_width = 9  # ###.###XB
    freq_max_width = max([len(str(f[1])) for f in data_bins])
    hist_width_total = (
        len("<=")
        + size_max_width
        + len(" :")
        + freq_max_width
        + len(" ")
        + hist_scale_factor
    )

    result = []
    result.append(f"min: {size_fmt(min(data))}")
    result.append("\n\t")
    result.append("-" * hist_width_total)
    result.append("\n\t")
    for i in range(len(scaled_data_bins)):
        rel_op = "<=" if i == len(scaled_data_bins) - 1 else "< "
        result.append(f"{rel_op}{size_fmt(data_bins[i][0]):<{size_max_width}}:")
        result.append(f" {data_bins[i][1]:>{freq_max_width}} ")
        result.append("▇" * scaled_data_bins[i])
        result.append("\n\t")
    result.append("-" * hist_width_total)
    result.append(f"\n\tmax: {size_fmt(max(data))}")

    return "".join(result)


class StatsReporter:
    def __init__(self, data: Iterable[AllocationRecord], num_largest: int):
        self.data = list(data)
        if num_largest < 1:
            raise ValueError(f"Invalid input num_largest={num_largest}, should be >=1")
        self.num_largest = num_largest

    @classmethod
    def from_snapshot(
        cls, allocations: Iterable[AllocationRecord], num_largest: int
    ) -> "StatsReporter":
        return cls(allocations, num_largest)

    def render(
        self,
        *,
        file: Optional[IO[str]] = None,
    ) -> None:
        shdata = self._get_stats_data()

        rich.print("📏 [bold]Total allocations:[/]")
        print(f"\t{shdata.total_num_allocations}")

        print()
        rich.print("📦 [bold]Total memory allocated:[/]")
        print(f"\t{size_fmt(shdata.total_memory_allocated)}")

        print()
        num_bins = 10
        histogram_scale_factor = 25
        rich.print("📊 [bold]Histogram of allocation size:[/]")
        histogram = self._draw_histogram(
            shdata.allocation_size_array,
            num_bins,
            hist_scale_factor=histogram_scale_factor,
        )
        print(f"\t{histogram}")

        print()
        rich.print("📂 [bold]Allocator type distribution:[/]")
        for entry in self._get_allocator_type_distribution(
            shdata.allocation_type_counter
        ):
            print(f"\t {entry}")

        print()
        rich.print(
            f"🥇 [bold]Top {self.num_largest} largest allocating locations (by size):[/]"
        )
        for entry in self._get_top_allocations_by_size():
            print(f"\t- {entry}")

        print()
        rich.print(
            f"🥇 [bold]Top {self.num_largest} largest allocating "
            "locations (by number of allocations):[/]"
        )
        for entry in self._get_top_allocations_by_count():
            print(f"\t- {entry}")

    def _get_stats_data(self) -> _StatsData:
        return get_stats_data(self.data)

    def _get_top_allocations_by_size(self) -> Generator[str, None, None]:
        yield from get_top_allocations_by_size(self.data, self.num_largest)

    def _get_top_allocations_by_count(self) -> Generator[str, None, None]:
        yield from get_top_allocations_by_count(self.data, self.num_largest)

    def _get_allocator_type_distribution(
        self, alloc_type_counter: Dict[str, int]
    ) -> Generator[str, None, None]:
        yield from get_allocator_type_distribution(alloc_type_counter)

    def _draw_histogram(
        self, data: List[int], bins: int, *, hist_scale_factor: int = 25
    ) -> str:
        return draw_histogram(data, bins, hist_scale_factor=hist_scale_factor)
