import html
import linecache
import sys
from typing import Any
from typing import Dict
from typing import Iterator
from typing import TextIO

from bloomberg.pensieve import Metadata
from bloomberg.pensieve._pensieve import AllocationRecord
from bloomberg.pensieve.reporters.frame_tools import StackFrame
from bloomberg.pensieve.reporters.frame_tools import is_cpython_internal
from bloomberg.pensieve.reporters.frame_tools import is_frame_interesting
from bloomberg.pensieve.reporters.templates import render_report

MAX_STACKS = int(sys.getrecursionlimit() // 2.5)

MAX_STACKS_NODE = {
    "name": "<STACK TOO DEEP>",
    "location": ["...", "...", 0],
    "children": {},
}


def with_converted_children_dict(node: Dict[str, Any]) -> Dict[str, Any]:
    stack = [node]
    while stack:
        the_node = stack.pop()
        the_node["children"] = [child for child in the_node["children"].values()]
        stack.extend(the_node["children"])
    return node


def create_framegraph_node_from_stack_frame(stack_frame: StackFrame) -> Dict[str, Any]:
    function, filename, lineno = stack_frame

    name = (
        # Use the source file line.
        linecache.getline(filename, lineno)
        # Or just describe where it is from
        or f"{function} at {filename}:{lineno}"
    )
    return {
        "name": name,
        "location": [html.escape(str(part)) for part in stack_frame],
        "value": 0,
        "children": {},
        "n_allocations": 0,
        "thread_id": 0,
        "interesting": is_frame_interesting(stack_frame),
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
            "location": [html.escape("<tracker>"), "<b>pensieve</b>", 0],
            "value": 0,
            "children": {},
            "n_allocations": 0,
            "thread_id": "0x0",
            "interesting": True,
        }

        unique_threads = set()
        for record in allocations:
            size = record.size
            thread_id = record.thread_name

            data["value"] += size
            data["n_allocations"] += record.n_allocations

            current_frame = data
            stack = (
                tuple(record.hybrid_stack_trace())
                if native_traces
                else record.stack_trace()
            )
            for index, stack_frame in enumerate(reversed(stack)):
                if is_cpython_internal(stack_frame):
                    continue
                if (stack_frame, thread_id) not in current_frame["children"]:
                    node = create_framegraph_node_from_stack_frame(stack_frame)
                    current_frame["children"][(stack_frame, thread_id)] = node

                current_frame = current_frame["children"][(stack_frame, thread_id)]
                current_frame["value"] += size
                current_frame["n_allocations"] += record.n_allocations
                current_frame["thread_id"] = thread_id
                unique_threads.add(thread_id)

                if index > MAX_STACKS:
                    current_frame.update(MAX_STACKS_NODE)
                    break

        transformed_data = with_converted_children_dict(data)
        transformed_data["unique_threads"] = sorted(unique_threads)
        return cls(transformed_data)

    def render(
        self,
        outfile: TextIO,
        metadata: Metadata,
        show_memory_leaks: bool,
        merge_threads: bool,
    ) -> None:
        html_code = render_report(
            kind="flamegraph",
            data=self.data,
            metadata=metadata,
            show_memory_leaks=show_memory_leaks,
            merge_threads=merge_threads,
        )
        print(html_code, file=outfile)
