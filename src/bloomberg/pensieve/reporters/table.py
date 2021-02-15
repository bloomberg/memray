import html
import importlib
import json
from typing import Any
from typing import Dict
from typing import Iterator
from typing import List
from typing import TextIO

from bloomberg.pensieve._pensieve import AllocationRecord
from bloomberg.pensieve._pensieve import AllocatorType


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
                    address=record.address,
                    size=record.size,
                    allocator=allocator.name.lower(),
                    n_allocations=record.n_allocations,
                    stack_trace=html.escape(stack),
                )
            )

        return cls(result)

    def render(self, outfile: TextIO) -> None:
        package = "bloomberg.pensieve.reporters"
        css_code = importlib.resources.read_text(package, "flamegraph.css")
        common_js_code = importlib.resources.read_text(package, "common.js")
        js_code = importlib.resources.read_text(package, "table.js")
        template = importlib.resources.read_text(package, "table.template.html")

        replacements = [
            ("{{ css }}", css_code),
            ("{{ common_js }}", common_js_code),
            ("{{ js }}", js_code),
            ("{{ table_data }}", json.dumps(self.data)),
        ]
        html_code = template
        for original, replacement in replacements:
            html_code = html_code.replace(original, replacement)

        print(html_code, file=outfile)
