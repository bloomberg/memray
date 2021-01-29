import html
import importlib.resources
import json
import linecache
from typing import Any
from typing import Dict
from typing import Iterator
from typing import TextIO
from typing import Tuple

from bloomberg.pensieve._pensieve import AllocationRecord


def with_converted_children_dict(node: Dict[str, Any]) -> Dict[str, Any]:
    node["children"] = [
        with_converted_children_dict(child) for child in node["children"].values()
    ]
    return node


def create_framegraph_node_from_stack_flame(
    stack_frame: Tuple[str, str, int]
) -> Dict[str, Any]:
    function, filename, lineno = stack_frame

    name = linecache.getline(filename, lineno) or f"{filename}:{lineno}"
    tooltip = html.escape(f"File {filename}, line {lineno} in {function}")
    return {
        "name": name,
        "tooltip": tooltip,
        "value": 0,
        "children": {},
    }


class FlameGraphReporter:
    def __init__(self, data: Dict[str, Any]):
        super().__init__()
        self.data = data

    @classmethod
    def from_snapshot(
        cls, allocations: Iterator[AllocationRecord]
    ) -> "FlameGraphReporter":
        data: Dict[str, Any] = {
            "name": "<root>",
            "tooltip": "The overall context that <b>pensieve</b> is run in.",
            "value": 0,
            "children": {},
        }

        for record in allocations:
            size = record.size

            data["value"] += size

            current_frame = data
            for stack_frame in reversed(record.stack_trace()):
                if stack_frame not in current_frame["children"]:
                    node = create_framegraph_node_from_stack_flame(stack_frame)
                    current_frame["children"][stack_frame] = node

                current_frame = current_frame["children"][stack_frame]
                current_frame["value"] += size

        transformed_data = with_converted_children_dict(data)
        return cls(transformed_data)

    def render(self, outfile: TextIO) -> None:
        package = "bloomberg.pensieve.reporters"
        css_code = importlib.resources.read_text(package, "flamegraph.css")
        js_code = importlib.resources.read_text(package, "flamegraph.js")
        template = importlib.resources.read_text(package, "flamegraph.template.html")

        # Make the replacements to generate the final HTML output
        replacements = [
            ("{{ css }}", css_code),
            ("{{ js }}", js_code),
            ("{{ flamegraph_data }}", json.dumps(self.data)),
        ]
        html_code = template
        for original, replacement in replacements:
            html_code = html_code.replace(original, replacement)

        print(html_code, file=outfile)
