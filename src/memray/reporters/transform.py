import csv
import json
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import TextIO
from typing import Tuple

from memray import AllocationRecord
from memray import AllocatorType
from memray import MemorySnapshot
from memray import Metadata
from memray.reporters.common import format_thread_name

Location = Tuple[str, str]


class TransformReporter:
    SUFFIX_MAP = {
        "gprof2dot": ".json",
        "csv": ".csv",
    }

    def __init__(
        self,
        allocations: Iterable[AllocationRecord],
        *,
        format: str,
        native_traces: bool,
        memory_records: Iterable[MemorySnapshot],
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.allocations = allocations
        self.format = format
        self.native_traces = native_traces
        self.memory_records = memory_records

    def render_as_gprof2dot(
        self,
        outfile: TextIO,
        **kwargs: Any,
    ) -> None:
        location_to_index: Dict[Location, int] = {}
        all_locations: List[Dict[str, str]] = []
        events = []
        for record in self.allocations:
            stack_trace = (
                tuple(record.hybrid_stack_trace())
                if self.native_traces
                else record.stack_trace()
            )
            call_chain = []
            for func, mod, _ in stack_trace:
                location = (func, mod)
                index = location_to_index.get(location)
                if index is None:
                    index = len(all_locations)
                    all_locations.append({"name": func, "module": mod})
                    location_to_index[location] = index
                call_chain.append(index)

            if not call_chain:
                continue
            events.append({"callchain": call_chain, "cost": [record.size]})

        result = {
            "version": 0,
            "costs": [{"description": "Memory", "unit": "bytes"}],
            "events": events,
            "functions": all_locations,
        }
        json.dump(result, outfile)

    def render(
        self,
        outfile: TextIO,
        metadata: Metadata,
        show_memory_leaks: bool,
        merge_threads: bool,
        inverted: bool,
    ) -> None:
        if not merge_threads:
            raise NotImplementedError("TransformReporter only supports merged threads.")
        if inverted:
            raise NotImplementedError(
                "TransformReporter does not support inverted argument."
            )
        renderer = getattr(self, f"render_as_{self.format}")
        renderer(outfile, metadata=metadata, show_memory_leaks=show_memory_leaks)

    def render_as_csv(
        self,
        outfile: TextIO,
        **kwargs: Any,
    ) -> None:
        writer = csv.writer(outfile)
        writer.writerow(
            [
                "allocator",
                "num_allocations",
                "size",
                "tid",
                "thread_name",
                "stack_trace",
            ]
        )
        for record in self.allocations:
            stack_trace = (
                tuple(record.hybrid_stack_trace())
                if self.native_traces
                else record.stack_trace()
            )
            writer.writerow(
                [
                    AllocatorType(record.allocator).name,
                    record.n_allocations,
                    record.size,
                    record.tid,
                    format_thread_name(record),
                    "|".join(f"{func};{mod};{line}" for func, mod, line in stack_trace),
                ]
            )
