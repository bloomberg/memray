import html
import linecache
from typing import Any
from typing import Dict
from typing import Iterator
from typing import TextIO
from typing import Tuple

from bloomberg.pensieve import Metadata
from bloomberg.pensieve._pensieve import AllocationRecord
from bloomberg.pensieve.reporters.templates import render_report


def with_converted_children_dict(node: Dict[str, Any]) -> Dict[str, Any]:
    node["children"] = [
        with_converted_children_dict(child) for child in node["children"].values()
    ]
    return node


def create_framegraph_node_from_stack_frame(
    stack_frame: Tuple[str, str, int]
) -> Dict[str, Any]:
    function, filename, lineno = stack_frame

    name = (
        # Use the source file line.
        linecache.getline(filename, lineno)
        # Or just describe where it is from
        or f"{function} at {filename}:{lineno}"
    )
    location = html.escape(f"File {filename}, line {lineno} in {function}")
    return {
        "name": name,
        "location": location,
        "value": 0,
        "children": {},
        "n_allocations": 0,
        "allocations_label": "",
        "thread_id": 0,
    }


class FlameGraphReporter:
    def __init__(self, data: Dict[str, Any]):
        super().__init__()
        self.data = data

    @classmethod
    def from_snapshot(
        cls, allocations: Iterator[AllocationRecord], *, native_traces: bool
    ) -> "FlameGraphReporter":
        data: Dict[str, Any] = {
            "name": "<root>",
            "location": "The overall context that <b>pensieve</b> is run in.",
            "value": 0,
            "children": {},
            "n_allocations": 0,
            "allocations_label": "",
            "thread_id": 0,
        }

        def gen_allocations_label(n_allocations: int) -> str:
            return html.escape(
                f"{n_allocations} allocation{'s' if n_allocations > 1 else ''}"
            )

        for record in allocations:
            size = record.size
            thread_id = record.tid

            data["value"] += size
            data["n_allocations"] += record.n_allocations

            current_frame = data
            stack = (
                record.hybrid_stack_trace() if native_traces else record.stack_trace()
            )
            for stack_frame in reversed(stack):
                if (stack_frame, thread_id) not in current_frame["children"]:
                    node = create_framegraph_node_from_stack_frame(stack_frame)
                    current_frame["children"][(stack_frame, thread_id)] = node

                current_frame = current_frame["children"][(stack_frame, thread_id)]
                current_frame["value"] += size
                current_frame["n_allocations"] += record.n_allocations
                current_frame["allocations_label"] = gen_allocations_label(
                    current_frame["n_allocations"]
                )
                current_frame["thread_id"] = thread_id

        data["allocations_label"] = gen_allocations_label(data["n_allocations"])

        transformed_data = with_converted_children_dict(data)
        return cls(transformed_data)

    def render(
        self,
        outfile: TextIO,
        metadata: Metadata,
        show_memory_leaks: bool,
    ) -> None:
        html_code = render_report(
            kind="flamegraph",
            data=self.data,
            metadata=metadata,
            show_memory_leaks=show_memory_leaks,
        )
        print(html_code, file=outfile)
