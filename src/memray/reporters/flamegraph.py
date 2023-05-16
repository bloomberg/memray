import collections
import html
import linecache
import sys
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import TextIO
from typing import Tuple
from typing import TypeVar
from typing import Union

from memray import AllocationRecord
from memray import MemorySnapshot
from memray import Metadata
from memray._memray import TemporalAllocationRecord
from memray.reporters.frame_tools import StackFrame
from memray.reporters.frame_tools import is_cpython_internal
from memray.reporters.frame_tools import is_frame_from_import_system
from memray.reporters.frame_tools import is_frame_interesting
from memray.reporters.templates import render_report

MAX_STACKS = int(sys.getrecursionlimit() // 2.5)

T = TypeVar("T")


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
    def _from_any_snapshot(
        cls,
        allocations: Iterable[Union[AllocationRecord, TemporalAllocationRecord]],
        *,
        memory_records: Iterable[MemorySnapshot],
        native_traces: bool,
        temporal: bool,
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
        interval_list: List[Tuple[int, Optional[int], int, int, int]] = []

        node_index_by_key: Dict[Tuple[int, StackFrame, str], int] = {}

        unique_threads = set()
        for record in allocations:
            thread_id = record.thread_name

            unique_threads.add(thread_id)

            if temporal:
                assert isinstance(record, TemporalAllocationRecord)
                intervals = record.intervals
                size = None
                n_allocations = None
            else:
                assert not isinstance(record, TemporalAllocationRecord)
                intervals = None
                size = record.size
                n_allocations = record.n_allocations

            if size is not None:
                root["value"] += size
            if n_allocations is not None:
                root["n_allocations"] += n_allocations

            current_frame_id = 0
            current_frame = root

            stack = (
                tuple(record.hybrid_stack_trace())
                if native_traces
                else record.stack_trace()
            )
            num_skipped_frames = 0
            is_import_system = False
            for index, stack_frame in enumerate(reversed(stack)):
                node_key = (current_frame_id, stack_frame, thread_id)
                if node_key not in node_index_by_key:
                    if is_cpython_internal(stack_frame):
                        num_skipped_frames += 1
                        continue

                    if not is_import_system:
                        is_import_system = is_frame_from_import_system(stack_frame)

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
                is_import_system = current_frame["import_system"]
                if size is not None:
                    current_frame["value"] += size
                if n_allocations is not None:
                    current_frame["n_allocations"] += n_allocations

                if index - num_skipped_frames > MAX_STACKS:
                    current_frame["name"] = "<STACK TOO DEEP>"
                    current_frame["location"] = ["...", "...", 0]
                    break

            if intervals is not None:
                interval_list.extend(
                    (
                        interval.allocated_before_snapshot,
                        interval.deallocated_before_snapshot,
                        current_frame_id,
                        interval.n_allocations,
                        interval.n_bytes,
                    )
                    for interval in intervals
                )

        all_strings = StringRegistry()
        nodes = collections.defaultdict(list)
        for frame in frames:
            nodes["name"].append(all_strings.register(frame["name"]))
            nodes["function"].append(all_strings.register(frame["location"][0]))
            nodes["filename"].append(all_strings.register(frame["location"][1]))
            nodes["lineno"].append(frame["location"][2])
            nodes["children"].append(frame["children"])
            if not interval_list:
                nodes["value"].append(frame["value"])
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

        if interval_list:
            data["intervals"] = interval_list

        return cls(data, memory_records=memory_records)

    @classmethod
    def from_snapshot(
        cls,
        allocations: Iterable[AllocationRecord],
        *,
        memory_records: Iterable[MemorySnapshot],
        native_traces: bool,
    ) -> "FlameGraphReporter":
        return cls._from_any_snapshot(
            allocations,
            memory_records=memory_records,
            native_traces=native_traces,
            temporal=False,
        )

    @classmethod
    def from_temporal_snapshot(
        cls,
        allocations: Iterable[TemporalAllocationRecord],
        *,
        memory_records: Iterable[MemorySnapshot],
        native_traces: bool,
        high_water_mark_by_snapshot: Optional[List[int]],
    ) -> "FlameGraphReporter":
        ret = cls._from_any_snapshot(
            allocations,
            memory_records=memory_records,
            native_traces=native_traces,
            temporal=True,
        )
        ret.data["high_water_mark_by_snapshot"] = high_water_mark_by_snapshot
        return ret

    def render(
        self,
        outfile: TextIO,
        metadata: Metadata,
        show_memory_leaks: bool,
        merge_threads: bool,
    ) -> None:
        kind = "temporal_flamegraph" if "intervals" in self.data else "flamegraph"
        html_code = render_report(
            kind=kind,
            data=self.data,
            metadata=metadata,
            memory_records=self.memory_records,
            show_memory_leaks=show_memory_leaks,
            merge_threads=merge_threads,
        )
        print(html_code, file=outfile)
