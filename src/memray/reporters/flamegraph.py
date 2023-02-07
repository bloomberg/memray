import collections
import html
import linecache
import sys
from itertools import tee
from itertools import zip_longest
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import List
from typing import TextIO
from typing import Tuple
from typing import TypeVar

from memray import AllocationRecord
from memray import MemorySnapshot
from memray import Metadata
from memray.reporters.frame_tools import StackFrame
from memray.reporters.frame_tools import is_cpython_internal
from memray.reporters.frame_tools import is_frame_from_import_system
from memray.reporters.frame_tools import is_frame_interesting
from memray.reporters.templates import render_report

MAX_STACKS = int(sys.getrecursionlimit() // 2.5)

T = TypeVar("T")


def pairwise_longest(iterable: Iterator[T]) -> Iterable[Tuple[T, T]]:
    a, b = tee(iterable)
    next(b, None)
    return zip_longest(a, b)


def create_framegraph_node_from_stack_frame(
    stack_frame: StackFrame, **kwargs: Any
) -> Dict[str, Any]:
    function, filename, lineno = stack_frame

    name = (
        # Use the source file line.
        linecache.getline(filename, lineno)
        # Or just describe where it is from
        or f"{function} at {filename}:{lineno}"
    )
    return {
        "name": name,
        "location": [html.escape(function), html.escape(filename), lineno],
        "value": 0,
        "children": [],
        "n_allocations": 0,
        "interesting": (
            is_frame_interesting(stack_frame)
            and not is_frame_from_import_system(stack_frame)
        ),
        **kwargs,
    }


class StringRegistry:
    def __init__(self) -> None:
        self.strings: List[str] = []
        self._index_by_string: Dict[str, int] = {}

    def register(self, string: str) -> int:
        idx = self._index_by_string.setdefault(string, len(self.strings))
        if idx == len(self.strings):
            self.strings.append(string)
        return idx


class FlameGraphReporter:
    def __init__(
        self,
        data: Dict[str, Any],
        *,
        memory_records: Iterable[MemorySnapshot],
    ) -> None:
        super().__init__()
        self.data = data
        self.memory_records = memory_records

    @classmethod
    def from_snapshot(
        cls,
        allocations: Iterator[AllocationRecord],
        *,
        memory_records: Iterable[MemorySnapshot],
        native_traces: bool,
    ) -> "FlameGraphReporter":
        root: Dict[str, Any] = {
            "name": "<root>",
            "location": [html.escape("<tracker>"), "<b>memray</b>", 0],
            "value": 0,
            "children": [],
            "n_allocations": 0,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
        }

        frames = [root]

        node_index_by_key: Dict[Tuple[int, StackFrame, str], int] = {}

        unique_threads = set()
        for record in allocations:
            size = record.size
            thread_id = record.thread_name

            unique_threads.add(thread_id)

            root["value"] += size
            root["n_allocations"] += record.n_allocations

            current_frame_id = 0
            current_frame = root

            stack = (
                tuple(record.hybrid_stack_trace())
                if native_traces
                else record.stack_trace()
            )
            num_skipped_frames = 0
            is_import_system = False
            for index, (stack_frame, next_frame) in enumerate(
                pairwise_longest(reversed(stack))
            ):
                if is_cpython_internal(stack_frame):
                    num_skipped_frames += 1
                    continue

                # Check if the next frame is from the import system. We check
                # the next frame because the "import ..." code will be the parent
                # of the first frame to enter the import system and we want to hide
                # that one as well.
                if is_frame_from_import_system(stack_frame) or (
                    next_frame and is_frame_from_import_system(next_frame)
                ):
                    is_import_system = True

                node_key = (current_frame_id, stack_frame, thread_id)
                if node_key not in node_index_by_key:
                    new_node_id = len(frames)
                    node_index_by_key[node_key] = new_node_id
                    current_frame["children"].append(new_node_id)
                    frames.append(
                        create_framegraph_node_from_stack_frame(
                            stack_frame,
                            import_system=is_import_system,
                            thread_id=thread_id,
                        )
                    )

                current_frame_id = node_index_by_key[node_key]
                current_frame = frames[current_frame_id]
                current_frame["value"] += size
                current_frame["n_allocations"] += record.n_allocations

                if index - num_skipped_frames > MAX_STACKS:
                    current_frame["name"] = "<STACK TOO DEEP>"
                    current_frame["location"] = ["...", "...", 0]
                    break

        all_strings = StringRegistry()
        nodes = collections.defaultdict(list)
        for frame in frames:
            nodes["name"].append(all_strings.register(frame["name"]))
            nodes["function"].append(all_strings.register(frame["location"][0]))
            nodes["filename"].append(all_strings.register(frame["location"][1]))
            nodes["lineno"].append(frame["location"][2])
            nodes["value"].append(frame["value"])
            nodes["children"].append(frame["children"])
            nodes["n_allocations"].append(frame["n_allocations"])
            nodes["thread_id"].append(all_strings.register(frame["thread_id"]))
            nodes["interesting"].append(int(frame["interesting"]))
            nodes["import_system"].append(int(frame["import_system"]))

        data = {
            "unique_threads": tuple(
                all_strings.register(t) for t in sorted(unique_threads)
            ),
            "nodes": nodes,
            "strings": all_strings.strings,
        }

        return cls(data, memory_records=memory_records)

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
            memory_records=self.memory_records,
            show_memory_leaks=show_memory_leaks,
            merge_threads=merge_threads,
        )
        print(html_code, file=outfile)
