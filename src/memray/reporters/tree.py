import asyncio
import functools
import linecache
import sys
from dataclasses import dataclass
from dataclasses import field
from typing import IO
from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import Optional
from typing import Tuple

from rich.style import Style
from rich.text import Text
from textual import binding
from textual import work
from textual.app import App
from textual.app import ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.color import Gradient
from textual.containers import Grid
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.dom import DOMNode
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer
from textual.widgets import Label
from textual.widgets import TextArea
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from memray import AllocationRecord
from memray._memray import size_fmt
from memray.reporters._textual_hacks import Bindings
from memray.reporters._textual_hacks import redraw_footer
from memray.reporters._textual_hacks import update_key_description
from memray.reporters.common import format_thread_name
from memray.reporters.frame_tools import is_cpython_internal
from memray.reporters.frame_tools import is_frame_from_import_system
from memray.reporters.frame_tools import is_frame_interesting
from memray.reporters.tui import _filename_to_module_name

MAX_STACKS = int(sys.getrecursionlimit() // 2.5)

StackElement = Tuple[str, str, int]

ROOT_NODE = ("<ROOT>", "", 0)


@dataclass
class Frame:
    """A frame in the tree"""

    location: Optional[StackElement]
    value: int
    children: Dict[StackElement, "Frame"] = field(default_factory=dict)
    n_allocations: int = 0
    thread_id: str = ""
    interesting: bool = True
    import_system: bool = False


@dataclass
class ElidedLocations:
    """Information about allocations locations below the configured threshold."""

    cutoff: int = 0
    n_locations: int = 0
    n_allocations: int = 0
    n_bytes: int = 0


class FrameDetailScreen(Widget):
    """A screen that displays information about a frame"""

    frame = reactive(Frame(location=ROOT_NODE, value=0))

    def __init__(
        self, *args: Any, elided_locations: ElidedLocations, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.__elided_locations = elided_locations
        self.__is_mounted = False

    def on_mount(self) -> None:
        self.__is_mounted = True

    @work(exclusive=True)
    async def update_text_area(self) -> None:
        await asyncio.sleep(0.1)

        if not self.__is_mounted or self.frame is None:
            return

        text = self.query_one("#textarea", TextArea)

        if self.frame.location is None or self.frame.location == ROOT_NODE:
            text.clear()
            return

        _, file, line = self.frame.location
        delta = text.size.height // 2
        lines = linecache.getlines(file)[max(line - delta, 0) : line + delta]

        text.text = "\n".join(tuple(line.rstrip() for line in lines))
        text.select_line(line - 1 if delta >= line else delta - 1)
        text.show_line_numbers = False

    def _get_content_by_label_id(self) -> Dict[str, str]:
        common = {
            "allocs": f":floppy_disk: Allocations: {self.frame.n_allocations}",
            "size": f":package: Size: {size_fmt(self.frame.value)}",
        }

        if self.frame.location is None:
            cutoff = self.__elided_locations.cutoff
            return {
                **common,
                "function": "",
                "location": (
                    f"Only the top {cutoff} allocation locations are shown in the tree."
                    " Allocation locations which individually contributed too little"
                    " to meet the threshold are summarized here.\n\n"
                    "You can adjust this threshold to include more allocation locations"
                    " by rerunning this reporter with a larger --biggest-allocs value."
                ),
                "thread": "",
            }

        function, file, lineno = self.frame.location
        if self.frame.location is ROOT_NODE:
            return {
                **common,
                "function": "",
                "location": "",
                "thread": "",
            }
        return {
            **common,
            "function": f":compass: Function: {function}",
            "location": (
                ":compass: Location: "
                + (
                    f"{_filename_to_module_name(file)}:{lineno}"
                    if lineno != 0
                    else file
                )
            ),
            "thread": f":thread: Thread: {self.frame.thread_id}",
        }

    def watch_frame(self) -> None:
        if not self.__is_mounted or self.frame is None:
            return

        self.update_text_area()

        content_by_label_id = self._get_content_by_label_id()
        for label_id, content in content_by_label_id.items():
            label = self.query_one(f"#{label_id}", Label)
            label.update(content)
            label.set_class(not content, "hidden")
            label.styles.display = "block" if content else "none"

    def compose(self) -> ComposeResult:
        if self.frame is None:
            return

        delta = 3

        if self.frame.location is None or self.frame.location == ROOT_NODE:
            lines = []
            selected_line = 0
        else:
            _, file, line = self.frame.location
            lines = linecache.getlines(file)[max(line - delta, 0) : line + delta]
            selected_line = line - 1 if delta >= line else delta - 1

        text = TextArea(
            "\n".join(lines), language="python", theme="dracula", id="textarea"
        )
        text.select_line(selected_line)
        text.show_line_numbers = False
        text.can_focus = False
        text.cursor_blink = False
        text.soft_wrap = False

        labels: list[Label] = []
        content_by_label_id = self._get_content_by_label_id()
        for label_id in ("function", "location", "allocs", "size", "thread"):
            content = content_by_label_id[label_id]
            label = Label(content, id=label_id)
            label.styles.display = "block" if content else "none"
            labels.append(label)

        node_metadata = Vertical(*labels)
        yield Grid(
            text,
            node_metadata,
            id="frame-detail-grid",
        )


class FrameTree(Tree[Frame]):
    def on_tree_node_selected(self, node: Tree.NodeSelected[Frame]) -> None:
        if node.node.data is not None:
            self.app.query_one(FrameDetailScreen).frame = node.node.data

    def on_tree_node_highlighted(self, node: Tree.NodeHighlighted[Frame]) -> None:
        if node.node.data is not None:
            self.app.query_one(FrameDetailScreen).frame = node.node.data


def node_is_interesting(node: Frame) -> bool:
    return node.interesting


def node_is_not_import_system(node: Frame) -> bool:
    return not node.import_system


class TreeScreen(Screen[None]):
    BINDINGS = [
        Binding("ctrl+z", "app.suspend_process"),
        Binding(key="q", action="app.quit", description="Quit the app"),
        Binding(
            key="i", action="toggle_import_system", description="Hide import system"
        ),
        Binding(
            key="u", action="toggle_uninteresting", description="Hide uninteresting"
        ),
        Binding(
            key="e", action="expand_linear_group", description="Expand linear group"
        ),
    ]

    CSS_PATH = "tree.css"

    def __init__(
        self,
        data: Frame,
        elided_locations: ElidedLocations,
    ):
        super().__init__()
        self.data = data
        self.elided_locations = elided_locations
        self.import_system_filter: Optional[Callable[[Frame], bool]] = None
        self.uninteresting_filter: Optional[
            Callable[[Frame], bool]
        ] = node_is_interesting

    def expand_first_child(self, node: TreeNode[Frame]) -> None:
        while node.children:
            node = node.children[0]
            node.toggle()

    def compose(self) -> ComposeResult:
        tree = FrameTree(self.frame_text(self.data, allow_expand=True), self.data)
        self.repopulate_tree(tree)
        yield Horizontal(
            Vertical(tree),
            Vertical(
                FrameDetailScreen(elided_locations=self.elided_locations),
                id="detailcol",
            ),
        )
        yield Footer()

    def repopulate_tree(self, tree: FrameTree) -> None:
        tree.clear()
        self.add_children(tree.root, self.data.children.values())
        self.add_elided_locations_node(tree.root)
        tree.root.expand()
        # From Textual 0.73 on, Tree.select_node toggles the node's expanded
        # state. The new Tree.move_cursor method selects without expanding.
        getattr(tree, "move_cursor", tree.select_node)(tree.root)
        self.expand_first_child(tree.root)

    def action_expand_linear_group(self) -> None:
        tree = self.query_one(FrameTree)
        current_node = tree.cursor_node
        while current_node:
            current_node.toggle()
            if len(current_node.children) != 1:
                break
            current_node = current_node.children[0]

    def frame_text(self, node: Frame, *, allow_expand: bool) -> Text:
        if node.value == 0:
            return Text("<No allocations>")

        value = node.value
        root_data = self.data
        size_str = f"{size_fmt(value)} ({100 * value / root_data.value:.2f} %)"
        size_color = _info_color(node, root_data)

        ret = Text.from_markup(
            ":open_file_folder:" if allow_expand else ":page_facing_up:"
        )
        ret.append_text(Text(f" {size_str} ", style=Style(color=size_color.rich_color)))

        if node.location is not None:
            function, file, lineno = node.location
            code_position = (
                f"{_filename_to_module_name(file)}:{lineno}" if lineno != 0 else file
            )
            ret.append_text(Text.from_markup(f"[bold]{function}[/]"))
            if code_position:
                ret.append_text(Text.from_markup(f"  [dim cyan]{code_position}[/]"))
        else:
            ret.append_text(Text("hidden"))
        return ret

    def add_children(self, tree: TreeNode[Frame], children: Iterable[Frame]) -> None:
        # Add children to the tree from largest to smallest
        children = sorted(children, key=lambda child: child.value, reverse=True)

        if self.import_system_filter is not None:
            children = tuple(filter(self.import_system_filter, children))

        for child in children:
            if self.uninteresting_filter is None or self.uninteresting_filter(child):
                if not tree.allow_expand:
                    assert tree.data is not None
                    tree.label = self.frame_text(tree.data, allow_expand=True)
                    tree.allow_expand = True
                new_tree = tree.add(
                    self.frame_text(child, allow_expand=False),
                    data=child,
                    allow_expand=False,
                )
            else:
                new_tree = tree

            self.add_children(new_tree, child.children.values())

    def add_elided_locations_node(self, tree: TreeNode[Frame]) -> None:
        if not self.elided_locations.n_locations:
            return

        count = self.elided_locations.n_locations
        value = self.elided_locations.n_bytes
        number = self.elided_locations.n_allocations

        root_data = self.data
        percentage = 100 * value / root_data.value
        size_str = f"{size_fmt(value)} ({percentage:.2f} %)"
        size_color = _percentage_to_color(int(percentage))
        ret = Text.from_markup("\N{black question mark ornament}")
        ret.append_text(Text(f" {size_str} ", style=Style(color=size_color.rich_color)))
        ret.append_text(
            Text.from_markup(
                f"{number} allocations from {count} locations"
                f" below the configured threshold"
            )
        )

        tree.add_leaf(ret, data=Frame(location=None, value=value, n_allocations=number))

    def action_toggle_import_system(self) -> None:
        if self.import_system_filter is None:
            self.import_system_filter = node_is_not_import_system
        else:
            self.import_system_filter = None

        redraw_footer(self.app)
        self.repopulate_tree(self.query_one(FrameTree))

    def action_toggle_uninteresting(self) -> None:
        if self.uninteresting_filter is None:
            self.uninteresting_filter = node_is_interesting
        else:
            self.uninteresting_filter = None

        redraw_footer(self.app)
        self.repopulate_tree(self.query_one(FrameTree))

    def rewrite_bindings(self, bindings: Bindings) -> None:
        if self.import_system_filter is not None:
            update_key_description(bindings, "i", "Show import system")
        if self.uninteresting_filter is not None:
            update_key_description(bindings, "u", "Show uninteresting")

    @property
    def active_bindings(self) -> Dict[str, "binding.ActiveBinding"]:
        bindings = super().active_bindings.copy()
        self.rewrite_bindings(bindings)
        return bindings


class TreeApp(App[None]):
    def __init__(
        self,
        data: Frame,
        elided_locations: ElidedLocations,
    ):
        super().__init__()
        self.tree_screen = TreeScreen(data, elided_locations)

    def on_mount(self) -> None:
        self.push_screen(self.tree_screen)

    if hasattr(App, "namespace_bindings"):
        # Removed in Textual 0.61
        @property
        def namespace_bindings(self) -> Dict[str, Tuple[DOMNode, Binding]]:
            bindings = super().namespace_bindings.copy()  # type: ignore[misc]
            self.tree_screen.rewrite_bindings(bindings)
            return bindings  # type: ignore[no-any-return]


@functools.lru_cache(maxsize=None)
def _percentage_to_color(percentage: int) -> Color:
    gradient = Gradient(
        (0, Color(97, 193, 44)),
        (0.4, Color(236, 152, 16)),
        (0.6, Color.parse("darkorange")),
        (1, Color.parse("indianred")),
    )
    return gradient.get_color(percentage / 100)


def _info_color(node: Frame, root_node: Frame) -> Color:
    proportion_of_total = node.value / root_node.value
    return _percentage_to_color(int(proportion_of_total * 100))


class TreeReporter:
    def __init__(self, data: Frame, elided_locations: ElidedLocations) -> None:
        super().__init__()
        self.data = data
        self.elided_locations = elided_locations

    @classmethod
    def from_snapshot(
        cls,
        allocations: Iterator[AllocationRecord],
        *,
        biggest_allocs: int = 200,
        native_traces: bool,
    ) -> "TreeReporter":
        data = Frame(location=ROOT_NODE, value=0, import_system=False, interesting=True)
        sorted_records = sorted(allocations, key=lambda alloc: alloc.size, reverse=True)
        for record in sorted_records[:biggest_allocs]:
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
                is_import_system = is_frame_from_import_system(stack_frame)
                is_interesting = not is_import_system and is_frame_interesting(
                    stack_frame
                )
                if stack_frame not in current_frame.children:
                    node = Frame(
                        value=0,
                        location=stack_frame,
                        import_system=is_import_system,
                        interesting=is_interesting,
                    )
                    current_frame.children[stack_frame] = node

                current_frame = current_frame.children[stack_frame]
                current_frame.value += size
                current_frame.n_allocations += record.n_allocations
                current_frame.thread_id = format_thread_name(record)

                if index > MAX_STACKS:
                    break

        elided_locations = ElidedLocations()
        elided_locations.cutoff = biggest_allocs

        for record in sorted_records[biggest_allocs:]:
            data.value += record.size
            data.n_allocations += record.n_allocations
            elided_locations.n_locations += 1
            elided_locations.n_bytes += record.size
            elided_locations.n_allocations += record.n_allocations

        return cls(data, elided_locations)

    def get_app(self) -> TreeApp:
        return TreeApp(self.data, self.elided_locations)

    def render(
        self,
        *,
        file: Optional[IO[str]] = None,
    ) -> None:
        self.get_app().run()
