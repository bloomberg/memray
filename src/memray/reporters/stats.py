import datetime
import json
import math
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional
from typing import Tuple

import rich

from memray._memray import size_fmt
from memray._stats import Stats

PythonStackElement = Tuple[str, str, int]


def get_histogram_databins(data: Dict[int, int], bins: int) -> List[Tuple[int, int]]:
    if bins <= 0:
        raise ValueError(f"Invalid input bins={bins}, should be greater than 0")

    low = math.log(min(filter(None, data)))
    high = math.log(max(data))
    if low == high:
        low = low / 2
    step = (high - low) / bins

    # Determine the upper bound in bytes for each bin
    steps = [int(math.exp(low + step * (i + 1))) for i in range(bins)]
    dist: Dict[int, int] = Counter()
    for size, count in data.items():
        bucket = min(int((math.log(size) - low) // step), bins - 1) if size else 0
        dist[bucket] += count
    return [(steps[b], dist[b]) for b in range(bins)]


def describe_histogram_databins(
    databins: List[Tuple[int, int]]
) -> List[Dict[str, int]]:
    ret: List[Dict[str, int]] = []
    start = 0
    for i, (end, count) in enumerate(databins):
        # The max size for the last bucket is inclusive, not exclusive
        adjustment = 1 if i != len(databins) - 1 else 0
        ret.append({"min_bytes": start, "max_bytes": end - adjustment, "count": count})
        start = end
    return ret


def draw_histogram(
    data: Dict[int, int], bins: int, *, hist_scale_factor: int = 25
) -> str:
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
    def __init__(self, stats: Stats, num_largest: int):
        self._stats = stats
        if num_largest < 1:
            raise ValueError(f"Invalid input num_largest={num_largest}, should be >=1")
        self.num_largest = num_largest

    def render(self, json_output_file: Optional[Path] = None) -> None:
        histogram_params = {
            "num_bins": 10,
            "histogram_scale_factor": 25,
        }
        if json_output_file:
            self._render_to_json(histogram_params, json_output_file)
        else:
            self._render_to_terminal(histogram_params)

    def _render_to_terminal(self, histogram_params: Dict[str, int]) -> None:
        rich.print("📏 [bold]Total allocations:[/]")
        print(f"\t{self._stats.total_num_allocations}")

        print()
        rich.print("📦 [bold]Total memory allocated:[/]")
        print(f"\t{size_fmt(self._stats.total_memory_allocated)}")

        print()

        rich.print("📊 [bold]Histogram of allocation size:[/]")
        histogram = draw_histogram(
            self._stats.allocation_count_by_size,
            histogram_params["num_bins"],
            hist_scale_factor=histogram_params["histogram_scale_factor"],
        )
        print(f"\t{histogram}")

        print()
        rich.print("📂 [bold]Allocator type distribution:[/]")
        for allocator_name, count in self._get_allocator_type_distribution():
            print(f"\t {allocator_name}: {count}")

        print()
        rich.print(
            f"🥇 [bold]Top {self.num_largest} largest allocating locations (by size):[/]"
        )
        for location, size in self._get_top_allocations_by_size():
            print(f"\t- {self._format_location(location)} -> {size_fmt(size)}")

        print()
        rich.print(
            f"🥇 [bold]Top {self.num_largest} largest allocating "
            "locations (by number of allocations):[/]"
        )
        for location, count in self._get_top_allocations_by_count():
            print(f"\t- {self._format_location(location)} -> {count}")

    def _render_to_json(self, histogram_params: Dict[str, int], out_path: Path) -> None:
        alloc_size_hist = describe_histogram_databins(
            get_histogram_databins(
                self._stats.allocation_count_by_size, bins=histogram_params["num_bins"]
            )
        )

        metadata = asdict(self._stats.metadata)
        for name, val in metadata.items():
            if isinstance(val, datetime.datetime):
                metadata[name] = str(val)

        data: Dict[str, Any] = {
            "total_num_allocations": self._stats.total_num_allocations,
            "total_bytes_allocated": self._stats.total_memory_allocated,
            "allocation_size_histogram": alloc_size_hist,
            "allocator_type_distribution": dict(
                self._get_allocator_type_distribution()
            ),
            "top_allocations_by_size": [
                {"location": self._format_location(location), "size": size}
                for location, size in self._get_top_allocations_by_size()
            ],
            "top_allocations_by_count": [
                {"location": self._format_location(location), "count": count}
                for location, count in self._get_top_allocations_by_count()
            ],
            "metadata": metadata,
        }

        with open(out_path, "w") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def _format_location(loc: Tuple[str, str, int]) -> str:
        function, file, line = loc
        if function == "<unknown>":
            return "<stack trace unavailable>"
        return f"{function}:{file}:{line}"

    def _get_top_allocations_by_size(self) -> Iterator[Tuple[PythonStackElement, int]]:
        for location, size in self._stats.top_locations_by_size:
            yield (location, size)

    def _get_top_allocations_by_count(self) -> Iterator[Tuple[PythonStackElement, int]]:
        for location, count in self._stats.top_locations_by_count:
            yield (location, count)

    def _get_allocator_type_distribution(self) -> Iterator[Tuple[str, int]]:
        for allocator_name, count in sorted(
            self._stats.allocation_count_by_allocator.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            yield (allocator_name, count)
