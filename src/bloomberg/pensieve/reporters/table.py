import html
from typing import Any
from typing import Dict
from typing import Iterator
from typing import List
from typing import TextIO

from bloomberg.pensieve._pensieve import AllocationRecord
from bloomberg.pensieve._pensieve import AllocatorType
from bloomberg.pensieve.reporters.templates import render_report


class TableReporter:
    def __init__(self, data: List[Dict[str, Any]]):
        super().__init__()
        self.data = data

    @classmethod
    def from_snapshot(cls, allocations: Iterator[AllocationRecord]) -> "TableReporter":

        result = []
        for record in allocations:
            stack_trace = record.stack_trace(max_stacks=1)
            stack = "???"
            if stack_trace:
                function, file, line = stack_trace[0]
                stack = f"{function} at {file}:{line}"

            allocator = AllocatorType(record.allocator)
            result.append(
                dict(
                    tid=record.tid,
                    size=record.size,
                    allocator=allocator.name.lower(),
                    n_allocations=record.n_allocations,
                    stack_trace=html.escape(stack),
                )
            )

        return cls(result)

    def render(self, outfile: TextIO) -> None:
        html_code = render_report(kind="table", data=self.data)
        print(html_code, file=outfile)
