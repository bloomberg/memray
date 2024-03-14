import collections
import html
import itertools
import linecache
import sys
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence
from typing import Set
from typing import TextIO
from typing import Tuple
from typing import TypeVar
from typing import Union
from typing import cast

if sys.version_info >= (3, 8):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict

from memray import AllocationRecord
from memray import MemorySnapshot
from memray import Metadata
from memray._memray import Interval
from memray._memray import TemporalAllocationRecord
from memray.reporters.common import format_thread_name
from memray.reporters.frame_tools import StackFrame
from memray.reporters.frame_tools import is_cpython_internal
from memray.reporters.frame_tools import is_frame_from_import_system
from memray.reporters.frame_tools import is_frame_interesting
from memray.reporters.templates import render_report

PythonStackElement = Tuple[str, str, int]
MAX_STACKS = int(sys.getrecursionlimit() // 2.5)

T = TypeVar("T")


class RecordData(TypedDict):
    thread_name: str
    size: Optional[int]
    n_allocations: Optional[int]
    intervals: Optional[List[Interval]]


class FrameNodeDict(TypedDict):
    name: str
    location: Tuple[str, str, int]
    value: int
    children: List[int]
    n_allocations: int
    interesting: bool
    thread_id: str
    import_system: bool


class FlameGraphNodeDict(TypedDict):
    name: List[int]
    function: List[int]
    filename: List[int]
    lineno: List[int]
    children: List[List[int]]
    value: List[int]
    n_allocations: List[int]
    thread_id: List[int]
    interesting: List[int]
    import_system: List[int]


def create_framegraph_node_from_stack_frame(
    stack_frame: StackFrame,
    thread_id: str,
    import_system: bool = False,
) -> FrameNodeDict:
    function, filename, lineno = stack_frame

    name = (
        # Use the source file line.
        linecache.getline(filename, lineno)
        # Or just describe where it is from
        or f"{function} at {filename}:{lineno}"
    )
    return {
        "name": name,
        "location": (html.escape(function), html.escape(filename), lineno),
        "value": 0,
        "children": [],
        "n_allocations": 0,
        "interesting": (
            is_frame_interesting(stack_frame)
            and not is_frame_from_import_system(stack_frame)
        ),
        "thread_id": thread_id,
        "import_system": import_system,
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
    def generate_nodes(
        cls,
        frames: List[FrameNodeDict],
        all_strings: StringRegistry,
        temporal: bool,
    ) -> FlameGraphNodeDict:
        nodes = cast(FlameGraphNodeDict, collections.defaultdict(list))
        for frame in frames:
            nodes["name"].append(all_strings.register(frame["name"]))
            nodes["function"].append(all_strings.register(frame["location"][0]))
            nodes["filename"].append(all_strings.register(frame["location"][1]))
            nodes["lineno"].append(frame["location"][2])
            nodes["children"].append(frame["children"])
            if not temporal:
                nodes["value"].append(frame["value"])
                nodes["n_allocations"].append(frame["n_allocations"])
            nodes["thread_id"].append(all_strings.register(frame["thread_id"]))
            nodes["interesting"].append(int(frame["interesting"]))
            nodes["import_system"].append(int(frame["import_system"]))
        return nodes

    @classmethod
    def generate_frames(
        cls,
        stack_it: Iterable[Tuple[int, PythonStackElement]],
        frames: List[FrameNodeDict],
        node_index_by_key: Dict[Tuple[int, StackFrame, str], int],
        record: RecordData,
        inverted: bool,
        interval_list: List[Tuple[int, Optional[int], int, int, int]],
    ) -> None:
        current_frame_id = 0
        current_frame = frames[0]

        if record["size"] is not None:
            current_frame["value"] += record["size"]
        if record["n_allocations"] is not None:
            current_frame["n_allocations"] += record["n_allocations"]

        num_skipped_frames = 0
        is_import_system = False

        for index, stack_frame in stack_it:
            node_key = (current_frame_id, stack_frame, record["thread_name"])
            if node_key not in node_index_by_key:
                if is_cpython_internal(stack_frame):
                    num_skipped_frames += 1
                    continue
                # update import_system only if we're generting normal flamegraph
                if not inverted and not is_import_system:
                    is_import_system = is_frame_from_import_system(stack_frame)

                new_node_id = len(frames)
                node_index_by_key[node_key] = new_node_id
                current_frame["children"].append(new_node_id)
                frames.append(
                    create_framegraph_node_from_stack_frame(
                        stack_frame,
                        import_system=is_import_system,
                        thread_id=record["thread_name"],
                    )
                )
            current_frame_id = node_index_by_key[node_key]
            current_frame = frames[current_frame_id]
            is_import_system = current_frame["import_system"]

            if record["size"] is not None:
                current_frame["value"] += record["size"]
            if record["n_allocations"] is not None:
                current_frame["n_allocations"] += record["n_allocations"]

            if index - num_skipped_frames > MAX_STACKS:
                current_frame["name"] = "<STACK TOO DEEP>"
                current_frame["location"] = ("...", "...", 0)
                break

        if record["intervals"] is not None:
            interval_list.extend(
                (
                    interval.allocated_before_snapshot,
                    interval.deallocated_before_snapshot,
                    current_frame_id,
                    interval.n_allocations,
                    interval.n_bytes,
                )
                for interval in record["intervals"]
            )

    @classmethod
    def _create_root_node(cls) -> FrameNodeDict:
        return {
            "name": "<root>",
            "location": (html.escape("<tracker>"), "<b>memray</b>", 0),
            "value": 0,
            "children": [],
            "n_allocations": 0,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
        }

    @classmethod
    def _drop_import_system_frames(
        cls,
        stack: Sequence[PythonStackElement],
    ) -> Iterable[PythonStackElement]:
        return reversed(
            list(
                itertools.takewhile(
                    lambda e: not is_frame_from_import_system(e),
                    reversed(stack),
                )
            )
        )

    @classmethod
    def _from_any_snapshot(
        cls,
        allocations: Iterable[Union[AllocationRecord, TemporalAllocationRecord]],
        *,
        memory_records: Iterable[MemorySnapshot],
        native_traces: bool,
        temporal: bool,
        inverted: Optional[bool] = None,
    ) -> "FlameGraphReporter":
        inverted = False if inverted is None else inverted

        frames: List[FrameNodeDict] = [cls._create_root_node()]
        inverted_no_imports_frames: List[FrameNodeDict] = []

        if inverted:
            inverted_no_imports_frames = [cls._create_root_node()]

        interval_list: List[Tuple[int, Optional[int], int, int, int]] = []
        no_imports_interval_list: List[Tuple[int, Optional[int], int, int, int]] = []

        NodeKey = Tuple[int, StackFrame, str]
        node_index_by_key: Dict[NodeKey, int] = {}
        inverted_no_imports_node_index_by_key: Dict[NodeKey, int] = {}

        unique_threads: Set[str] = set()
        for record in allocations:
            unique_threads.add(format_thread_name(record))

            record_data: RecordData
            if temporal:
                assert isinstance(record, TemporalAllocationRecord)
                record_data = {
                    "thread_name": format_thread_name(record),
                    "intervals": record.intervals,
                    "size": None,
                    "n_allocations": None,
                }
            else:
                assert not isinstance(record, TemporalAllocationRecord)
                record_data = {
                    "thread_name": format_thread_name(record),
                    "intervals": None,
                    "size": record.size,
                    "n_allocations": record.n_allocations,
                }

            stack = (
                tuple(record.hybrid_stack_trace())
                if native_traces
                else record.stack_trace()
            )

            if not inverted:
                # normal flamegraph
                cls.generate_frames(
                    stack_it=enumerate(reversed(stack)),
                    frames=frames,
                    node_index_by_key=node_index_by_key,
                    record=record_data,
                    inverted=inverted,
                    interval_list=interval_list,
                )
            else:
                # inverted flamegraph tree with all nodes
                cls.generate_frames(
                    stack_it=enumerate(stack),
                    frames=frames,
                    node_index_by_key=node_index_by_key,
                    record=record_data,
                    inverted=inverted,
                    interval_list=interval_list,
                )

                # inverted flamegraph tree without import system nodes
                cls.generate_frames(
                    stack_it=enumerate(cls._drop_import_system_frames(stack)),
                    frames=inverted_no_imports_frames,
                    node_index_by_key=inverted_no_imports_node_index_by_key,
                    record=record_data,
                    inverted=inverted,
                    interval_list=no_imports_interval_list,
                )

        all_strings = StringRegistry()
        nodes = cls.generate_nodes(
            frames=frames, all_strings=all_strings, temporal=temporal
        )
        inverted_no_imports_nodes = cls.generate_nodes(
            frames=inverted_no_imports_frames,
            all_strings=all_strings,
            temporal=temporal,
        )

        data = {
            "unique_threads": tuple(
                all_strings.register(t) for t in sorted(unique_threads)
            ),
            "nodes": nodes,
            "inverted_no_imports_nodes": inverted_no_imports_nodes,
            "strings": all_strings.strings,
        }

        if interval_list:
            data["intervals"] = interval_list
        if no_imports_interval_list:
            data["no_imports_interval_list"] = no_imports_interval_list

        return cls(data, memory_records=memory_records)

    @classmethod
    def from_snapshot(
        cls,
        allocations: Iterable[AllocationRecord],
        *,
        memory_records: Iterable[MemorySnapshot],
        native_traces: bool,
        inverted: Optional[bool] = None,
    ) -> "FlameGraphReporter":
        return cls._from_any_snapshot(
            allocations,
            memory_records=memory_records,
            native_traces=native_traces,
            temporal=False,
            inverted=inverted,
        )

    @classmethod
    def from_temporal_snapshot(
        cls,
        allocations: Iterable[TemporalAllocationRecord],
        *,
        memory_records: Iterable[MemorySnapshot],
        native_traces: bool,
        high_water_mark_by_snapshot: Optional[List[int]],
        inverted: Optional[bool] = None,
    ) -> "FlameGraphReporter":
        ret = cls._from_any_snapshot(
            allocations,
            memory_records=memory_records,
            native_traces=native_traces,
            temporal=True,
            inverted=inverted,
        )
        ret.data["high_water_mark_by_snapshot"] = high_water_mark_by_snapshot
        return ret

    def render(
        self,
        outfile: TextIO,
        metadata: Metadata,
        show_memory_leaks: bool,
        merge_threads: bool,
        inverted: bool,
    ) -> None:
        kind = "temporal_flamegraph" if "intervals" in self.data else "flamegraph"
        html_code = render_report(
            kind=kind,
            data=self.data,
            metadata=metadata,
            memory_records=self.memory_records,
            show_memory_leaks=show_memory_leaks,
            merge_threads=merge_threads,
            inverted=inverted,
        )
        print(html_code, file=outfile)
