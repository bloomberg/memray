import html
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import TextIO

from memray import AllocationRecord
from memray import AllocatorType
from memray import MemorySnapshot
from memray import Metadata
from memray.reporters.common import format_thread_name
from memray.reporters.templates import render_report


class TableReporter:
    def __init__(
        self,
        data: List[Dict[str, Any]],
        *,
        memory_records: Iterable[MemorySnapshot],
    ):
        super().__init__()
        self.data = data
        self.memory_records = memory_records

    @classmethod
    def from_snapshot(
        cls,
        allocations: Iterable[AllocationRecord],
        *,
        memory_records: Iterable[MemorySnapshot],
        native_traces: bool,
        **kwargs: Any,
    ) -> "TableReporter":
        result = []
        for record in allocations:
            stack_trace = (
                list(record.hybrid_stack_trace(max_stacks=1))
                if native_traces
                else record.stack_trace(max_stacks=1)
            )
            stack = "???"
            if stack_trace:
                function, file, line = stack_trace[0]
                stack = f"{function} at {file}:{line}"

            allocator = AllocatorType(record.allocator)
            result.append(
                {
                    "tid": format_thread_name(record),
                    "size": record.size,
                    "allocator": allocator.name.lower(),
                    "n_allocations": record.n_allocations,
                    "stack_trace": html.escape(stack),
                }
            )

        return cls(result, memory_records=memory_records)

    def render(
        self,
        outfile: TextIO,
        metadata: Metadata,
        show_memory_leaks: bool,
        merge_threads: bool,
        inverted: bool,
    ) -> None:
        if not merge_threads:
            raise NotImplementedError("TableReporter only supports merged threads.")
        if inverted:
            raise NotImplementedError(
                "TableReporter does not support inverted argument"
            )
        html_code = render_report(
            kind="table",
            data=self.data,
            metadata=metadata,
            memory_records=self.memory_records,
            show_memory_leaks=show_memory_leaks,
            merge_threads=merge_threads,
            inverted=inverted,
        )
        print(html_code, file=outfile)
