import asyncio
import functools
import linecache
import sys
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
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
from textual.widget import Widget
from textual.widgets import Footer
from textual.widgets import Label
from textual.widgets import TextArea
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from memray import AllocationRecord
from memray._memray import size_fmt
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

    location: StackElement
    value: int
    children: Dict[StackElement, "Frame"] = field(default_factory=dict)
    n_allocations: int = 0
    thread_id: str = ""
    interesting: bool = True
    import_system: bool = False


class FrameDetailScreen(Widget):
    """A screen that displays information about a frame"""

    frame = reactive(Frame(location=ROOT_NODE, value=0))

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.__is_mounted = False

    def on_mount(self) -> None:
        self.__is_mounted = True

    @work(exclusive=True)
    async def update_text_area(self) -> None:
        await asyncio.sleep(0.1)

        if not self.__is_mounted or self.frame is None:
            return

        _, file, line = self.frame.location
        text = self.query_one("#textarea", TextArea)
        delta = text.size.height // 2
        lines = linecache.getlines(file)[line - delta : line + delta]

        text.text = "\n".join(tuple(line.rstrip() for line in lines))
        text.select_line((delta - 1))
        text.show_line_numbers = False

    def watch_frame(self) -> None:
        if not self.__is_mounted or self.frame is None:
            return

        self.update_text_area()
        function, file, line = self.frame.location
        self.query_one("#function", Label).update(f":compass: Function: {function}")
        self.query_one("#location", Label).update(
            f":compass: Location: {_filename_to_module_name(file)}:{line}"
        )
        self.query_one("#allocs", Label).update(
            f":floppy_disk: Allocations: {self.frame.n_allocations}"
        )
        self.query_one("#size", Label).update(
            f":package: Size: {size_fmt(self.frame.value)}"
        )
        self.query_one("#thread", Label).update(
            f":thread: Thread: {self.frame.thread_id}"
        )

    def compose(self) -> ComposeResult:
        if self.frame is None:
            return
        function, file, line = self.frame.location
        delta = 3
        lines = linecache.getlines(file)[line - delta : line + delta]
        text = TextArea(
            "\n".join(lines), language="python", theme="dracula", id="textarea"
        )
        text.select_line(delta + 1)
        text.show_line_numbers = False
        text.can_focus = False
        text.cursor_blink = False

        node_metadata = Vertical(
            Label(f":compass: Function: {function}", id="function"),
            Label(f":compass: Location: {file}:{line}", id="location"),
            Label(
                f":floppy_disk: Allocations: {self.frame.n_allocations}",
                id="allocs",
            ),
            Label(f":package: Size: {size_fmt(self.frame.value)}", id="size"),
            Label(f":thread: Thread: {self.frame.thread_id}", id="thread"),
        )

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


class TreeApp(App[None]):
    BINDINGS = [
        Binding(key="q", action="quit", description="Quit the app"),
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

    DEFAULT_CSS = """
        Label {
            padding: 1 3;
        }

        #frame-detail-grid Label {
            color: $text;
            height: auto;
            width: 100%;
            background: $panel-lighten-1;
        }

        #frame-detail-grid {
            grid-size: 1 2;
            grid-gutter: 1 2;
            padding: 0 1;
            border: thick $background 80%;
            background: $surface;
        }

        #detailcol {
            width: 40%;
            max-width: 100;
        }

        TextArea {
            scrollbar-size-vertical: 0;
        }
    """

    def __init__(
        self,
        data: Frame,
    ):
        super().__init__()
        self.data = data
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
            Vertical(FrameDetailScreen(), id="detailcol"),
        )
        yield Footer()

    def repopulate_tree(self, tree: FrameTree) -> None:
        tree.clear()
        self.add_children(tree.root, self.data.children.values())
        tree.root.expand()
        tree.select_node(tree.root)
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
        function, file, lineno = node.location
        size_color = _info_color(node, root_data)
        code_position = (
            f"{_filename_to_module_name(file)}:{lineno}" if lineno != 0 else file
        )

        ret = Text.from_markup(
            ":open_file_folder:" if allow_expand else ":page_facing_up:"
        )
        ret.append_text(Text(f" {size_str} ", style=Style(color=size_color.rich_color)))
        ret.append_text(
            Text.from_markup(
                f"[bold]{function}[/bold]  [dim cyan]{code_position}[/dim cyan]"
            )
        )
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

    def action_toggle_import_system(self) -> None:
        if self.import_system_filter is None:
            self.import_system_filter = node_is_not_import_system
        else:
            self.import_system_filter = None

        self.redraw_footer()
        self.repopulate_tree(self.query_one(FrameTree))

    def action_toggle_uninteresting(self) -> None:
        if self.uninteresting_filter is None:
            self.uninteresting_filter = node_is_interesting
        else:
            self.uninteresting_filter = None

        self.redraw_footer()
        self.repopulate_tree(self.query_one(FrameTree))

    def redraw_footer(self) -> None:
        # Hack: trick the Footer into redrawing itself
        self.app.query_one(Footer).highlight_key = "q"
        self.app.query_one(Footer).highlight_key = None

    @property
    def namespace_bindings(self) -> Dict[str, Tuple[DOMNode, Binding]]:
        bindings = super().namespace_bindings.copy()
        if self.import_system_filter is not None:
            node, binding = bindings["i"]
            bindings["i"] = (
                node,
                replace(binding, description="Show import system"),
            )
        if self.uninteresting_filter is not None:
            node, binding = bindings["u"]
            bindings["u"] = (
                node,
                replace(binding, description="Show uninteresting"),
            )

        return bindings


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
    def __init__(self, data: Frame):
        super().__init__()
        self.data = data

    @classmethod
    def from_snapshot(
        cls,
        allocations: Iterator[AllocationRecord],
        *,
        biggest_allocs: int = 200,
        native_traces: bool,
    ) -> "TreeReporter":
        data = Frame(location=ROOT_NODE, value=0, import_system=False, interesting=True)
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
                current_frame.thread_id = record.thread_name

                if index > MAX_STACKS:
                    break

        return cls(data)

    def get_app(self) -> TreeApp:
        return TreeApp(self.data)

    def render(
        self,
        *,
        file: Optional[IO[str]] = None,
    ) -> None:
        self.get_app().run()
