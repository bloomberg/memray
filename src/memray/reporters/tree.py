import sys
from dataclasses import dataclass
from dataclasses import field
from typing import IO
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional
from typing import Tuple

import rich
import rich.tree

from memray import AllocationRecord
from memray._memray import size_fmt
from memray.reporters.frame_tools import is_cpython_internal

MAX_STACKS = int(sys.getrecursionlimit() // 2.5)

StackElement = Tuple[str, str, int]

ROOT_NODE = ("<ROOT>", "", 0)


@dataclass
class Frame:
    location: StackElement
    value: int
    children: Dict[StackElement, "Frame"] = field(default_factory=dict)
    n_allocations: int = 0
    thread_id: str = ""
    interesting: bool = True
    group: List["Frame"] = field(default_factory=list)

    def collapse_tree(self) -> "Frame":
        if len(self.children) == 0:
            return self
        elif len(self.children) == 1 and ROOT_NODE != self.location:
            [[key, child]] = self.children.items()
            self.children.pop(key)
            new_node = child.collapse_tree()
            new_node.group.append(self)
            return new_node
        else:
            self.children = {
                location: child.collapse_tree()
                for location, child in self.children.items()
            }
            return self


class TreeReporter:
    def __init__(self, data: Frame):
        super().__init__()
        self.data = data

    @classmethod
    def from_snapshot(
        cls,
        allocations: Iterator[AllocationRecord],
        *,
        biggest_allocs: int = 10,
        native_traces: bool,
    ) -> "TreeReporter":
        data = Frame(location=ROOT_NODE, value=0)
        for record in sorted(allocations, key=lambda alloc: alloc.size, reverse=True)[
            :biggest_allocs
        ]:
            size = record.size
            data.value += size
            data.n_allocations += record.n_allocations

            current_frame = data
            stack = (
                tuple(record.hybrid_stack_trace())
                if native_traces
                else record.stack_trace()
            )
            for index, stack_frame in enumerate(reversed(stack)):
                if is_cpython_internal(stack_frame):
                    continue
                if stack_frame not in current_frame.children:
                    node = Frame(value=0, location=stack_frame)
                    current_frame.children[stack_frame] = node

                current_frame = current_frame.children[stack_frame]
                current_frame.value += size
                current_frame.n_allocations += record.n_allocations
                current_frame.thread_id = record.thread_name

                if index > MAX_STACKS:
                    break

        return cls(data.collapse_tree())

    def render(
        self,
        *,
        file: Optional[IO[str]] = None,
    ) -> None:
        tree = self.make_rich_node(node=self.data)
        rich.print(tree, file=file)

    def make_rich_node(
        self,
        node: Frame,
        parent_tree: Optional[rich.tree.Tree] = None,
        root_node: Optional[Frame] = None,
        depth: int = 0,
    ) -> rich.tree.Tree:
        if node.value == 0:
            return rich.tree.Tree("<No allocations>")
        if root_node is None:
            root_node = node

        if node.group:
            libs = {frame.location[1] for frame in node.group}
            text = f"[blue][[{len(node.group)} frames hidden in {len(libs)} file(s)]][/blue]"
            parent_tree = (
                rich.tree.Tree(text) if parent_tree is None else parent_tree.add(text)
            )
        value = node.value
        size_str = f"{size_fmt(value)} ({100 * value / root_node.value:.2f} %)"
        function, file, lineno = node.location
        icon = ":page_facing_up:" if len(node.children) == 0 else ":open_file_folder:"
        frame_text = (
            "{icon}[{info_color}] {size} "
            "[bold]{function}[/bold][/{info_color}]  "
            "[dim cyan]{code_position}[/dim cyan]".format(
                icon=icon,
                size=size_str,
                info_color=self._info_color(node, root_node),
                function=function,
                code_position=f"{file}:{lineno}" if lineno != 0 else file,
            )
        )
        if parent_tree is None:
            parent_tree = new_tree = rich.tree.Tree(frame_text)
        else:
            new_tree = parent_tree.add(frame_text)
        for child in node.children.values():
            self.make_rich_node(child, new_tree, depth=depth + 1, root_node=root_node)
        return parent_tree

    def _info_color(self, node: Frame, root_node: Frame) -> str:
        proportion_of_total = node.value / root_node.value
        if proportion_of_total > 0.6:
            return "red"
        elif proportion_of_total > 0.2:
            return "yellow"
        elif proportion_of_total > 0.05:
            return "green"
        else:
            return "bright_green"
