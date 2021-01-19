import importlib.resources
import json
from typing import Any
from typing import Dict
from typing import Iterator
from typing import TextIO

from bloomberg.pensieve._pensieve import AllocationRecord


def with_converted_children_dict(node: Dict[str, Any]) -> Dict[str, Any]:
    node["children"] = [
        with_converted_children_dict(child) for child in node["children"].values()
    ]
    return node


class FlameGraphReporter:
    def __init__(self, data: Dict[str, Any]):
        super().__init__()
        self.data = data

    @classmethod
    def from_snapshot(
        cls, allocations: Iterator[AllocationRecord]
    ) -> "FlameGraphReporter":
        data: Dict[str, Any] = {
            "name": "root",
            "value": 0,
            "children": {},
            "filename": "<root>",
            "lineno": 0,
        }

        for record in allocations:
            size = record.size

            data["value"] += size

            current_frame = data
            for stack_frame in reversed(record.stack_trace()):
                if stack_frame not in current_frame["children"]:
                    function, filename, lineno = stack_frame
                    current_frame["children"][stack_frame] = {
                        "name": f"{filename}:{lineno}",
                        "value": 0,
                        "children": {},
                        "function": function,
                        "filename": filename,
                        "lineno": lineno,
                    }

                current_frame = current_frame["children"][stack_frame]
                current_frame["value"] += size

        transformed_data = with_converted_children_dict(data)
        return cls(transformed_data)

    def render(self, outfile: TextIO) -> None:
        package = "bloomberg.pensieve.reporters"
        resource = "flamegraph.template.html"
        with importlib.resources.open_text(package, resource) as fp:
            print(
                fp.read().replace("{{ flamegraph_data }}", json.dumps(self.data)),
                file=outfile,
            )
