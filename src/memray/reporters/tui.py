import contextlib
import os
import pathlib
import sys
import threading
from collections import defaultdict
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from functools import total_ordering
from math import ceil
from typing import Any
from typing import DefaultDict
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple
from typing import cast

from rich.markup import escape
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual import log
from textual.app import App
from textual.app import ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.color import Gradient
from textual.containers import Container
from textual.containers import HorizontalScroll
from textual.dom import DOMNode
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import DataTable
from textual.widgets import Footer
from textual.widgets import Label
from textual.widgets import Static
from textual.widgets.data_table import RowKey

from memray import AllocationRecord
from memray import SocketReader
from memray._memray import size_fmt
from memray.reporters._textual_hacks import Bindings
from memray.reporters._textual_hacks import redraw_footer
from memray.reporters._textual_hacks import update_key_description

MAX_MEMORY_RATIO = 0.95


@dataclass(frozen=True)
class Location:
    function: str
    file: str


@dataclass
class AllocationEntry:
    own_memory: int
    total_memory: int
    n_allocations: int
    thread_ids: Set[int]


@dataclass(frozen=True, eq=False)
class Snapshot:
    heap_size: int
    records: List[AllocationRecord]
    records_by_location: Dict[Location, AllocationEntry]


_EMPTY_SNAPSHOT = Snapshot(heap_size=0, records=[], records_by_location={})


class SnapshotFetched(Message):
    def __init__(self, snapshot: Snapshot, disconnected: bool) -> None:
        self.snapshot = snapshot
        self.disconnected = disconnected
        super().__init__()


class MemoryGraph(Widget):
    def __init__(
        self,
        *args: Any,
        max_data_points: int,
        height: int = 4,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        maxval: float = 1.0
        minval: float = 0.0
        self._width = max_data_points
        self._height = height
        self._minval = minval
        self._maxval = maxval
        values = [minval] * (2 * self._width + 1)
        self._values = deque(values, maxlen=2 * self._width)

        self._lookup = [
            [" ", "▗", "▐"],
            ["▖", "▄", "▟"],
            ["▌", "▙", "█"],
        ]

        self.border_title = "Heap Usage"

    def _value_to_blocks(self, value: float) -> List[int]:
        dots_per_block = 2
        if value < self._minval:
            n_dots = 0
        elif value > self._maxval:
            n_dots = dots_per_block * self._height
        else:
            n_dots = ceil(
                (value - self._minval)
                / (self._maxval - self._minval)
                * dots_per_block
                * self._height
            )
        blocks = [dots_per_block] * (n_dots // dots_per_block)
        if n_dots % dots_per_block > 0:
            blocks += [n_dots % dots_per_block]
        blocks += [0] * (self._height - len(blocks))
        return blocks

    def add_value(self, value: float) -> None:
        if value > self._maxval:
            self._maxval = value
        self._values.append(value)
        if self._maxval > 1:
            self.border_subtitle = (
                f"{size_fmt(int(value))}"
                f" ({int(round(value * 100/self._maxval, 0))}%"
                f" of {size_fmt(int(self._maxval))} max)"
            )
        self.refresh()

    def render_line(self, y: int) -> Strip:
        graph: list[list[str]] = [[] for _ in range(self._height)]
        blocks_by_index = [self._value_to_blocks(value) for value in self._values]

        for left, right in zip(blocks_by_index[::2], blocks_by_index[1::2]):
            for row, char in enumerate(
                reversed(tuple(self._lookup[li][ri] for li, ri in zip(left, right)))
            ):
                graph[row].append(char)

        if y > len(graph):
            return Strip.blank(self.size.width)
        data = " " * self.size.width
        data += "".join(graph[y])
        data = data[-self.size.width :]
        return Strip([Segment(data, self.rich_style)])


@total_ordering
class SortableText(Text):
    __slots__ = ("value",)

    def __init__(
        self,
        value: Any,
        text: str,
        color: Color,
        justify: Any = "right",  # "Any" is a hack: justify should be Literal
    ) -> None:
        self.value = value
        super().__init__(
            str(text),
            Style(color=color.rich_color),
            justify=justify,
        )

    def __lt__(self, other: Any) -> bool:
        if type(other) != SortableText:
            return NotImplemented
        return cast(bool, self.value < other.value)

    def __gt__(self, other: Any) -> bool:
        if type(other) != SortableText:
            return NotImplemented
        return cast(bool, self.value > other.value)

    def __eq__(self, other: Any) -> bool:
        if type(other) != SortableText:
            return NotImplemented
        return cast(bool, self.value == other.value)


def aggregate_allocations(
    allocations: Iterable[AllocationRecord],
    memory_threshold: float = float("inf"),
    native_traces: Optional[bool] = False,
) -> Dict[Location, AllocationEntry]:
    """Take allocation records and for each frame contained, record "own"
    allocations which happened on the frame, and sum up allocations on
    all of the child frames to calculate "total" allocations."""

    processed_allocations: DefaultDict[Location, AllocationEntry] = defaultdict(
        lambda: AllocationEntry(
            own_memory=0, total_memory=0, n_allocations=0, thread_ids=set()
        )
    )

    current_total = 0
    for allocation in allocations:
        if current_total >= memory_threshold:
            break
        current_total += allocation.size

        stack_trace = list(
            allocation.hybrid_stack_trace()
            if native_traces
            else allocation.stack_trace()
        )
        if not stack_trace:
            frame = processed_allocations[Location(function="???", file="???")]
            frame.total_memory += allocation.size
            frame.own_memory += allocation.size
            frame.n_allocations += allocation.n_allocations
            frame.thread_ids.add(allocation.tid)
            continue

        # Walk upwards and sum totals
        visited = set()
        for i, (function, file_name, _) in enumerate(stack_trace):
            location = Location(function=function, file=file_name)
            frame = processed_allocations[location]
            if location in visited:
                continue
            visited.add(location)
            if i == 0:
                frame.own_memory += allocation.size
            frame.total_memory += allocation.size
            frame.n_allocations += allocation.n_allocations
            frame.thread_ids.add(allocation.tid)
    return processed_allocations


class TimeDisplay(Static):
    """TUI widget to display the current time."""

    def on_mount(self) -> None:
        """Event handler called when the widget is added to the app."""
        self.set_interval(0.1, lambda: self.update(datetime.now().ctime()))


def _filename_to_module_name(file: str) -> str:
    if file.endswith(".py"):
        for path in sys.path:
            if not os.path.isdir(path):
                continue
            with contextlib.suppress(ValueError):
                relative_path = pathlib.Path(file).relative_to(path)
                ret = str(relative_path.with_suffix(""))
                ret = ret.replace(os.sep, ".").replace(".__init__", "")
                return ret
    return file


class AllocationTable(Widget):
    """Widget to display the TUI table."""

    COMPONENT_CLASSES = {
        "allocationtable--sorted-column-heading",
        "allocationtable--function-name",
    }

    DEFAULT_CSS = """
    AllocationTable .allocationtable--sorted-column-heading {
        text-style: bold underline;
    }

    AllocationTable .allocationtable--function-name {
    }
    """

    default_sort_column_id = 1
    sort_column_id = reactive(default_sort_column_id)
    snapshot = reactive(_EMPTY_SNAPSHOT)
    current_thread = reactive(0)
    merge_threads = reactive(False, init=False)

    columns = [
        "Location",
        "Total Bytes",
        "% Total",
        "Own Bytes",
        "% Own",
        "Allocations",
        "File/Module",
    ]

    KEY_TO_COLUMN_NAME = {
        1: "total_memory",
        3: "own_memory",
        5: "n_allocations",
    }

    HIGHLIGHTED_COLUMNS_BY_SORT_COLUMN = {
        1: (1, 2),
        3: (3, 4),
        5: (5,),
    }

    SORT_COLUMN_BY_CLICKED_COLUMN = {
        clicked_col: sort_col
        for sort_col, clicked_cols in HIGHLIGHTED_COLUMNS_BY_SORT_COLUMN.items()
        for clicked_col in clicked_cols
    }

    def __init__(self) -> None:
        super().__init__()
        self._composed = False

        gradient = Gradient(
            (0, Color(97, 193, 44)),
            (0.4, Color(236, 152, 16)),
            (0.6, Color.parse("darkorange")),
            (1, Color.parse("indianred")),
        )
        self._color_by_percentage = {i: gradient.get_color(i / 100) for i in range(101)}

    def _get_color(self, value: float, max: float) -> Color:
        return self._color_by_percentage[int(value * 100 / max)]

    def get_heading(self, column_idx: int) -> Text:
        sort_column = (
            self.sort_column_id if self._composed else self.default_sort_column_id
        )
        sort_column_style = self.get_component_rich_style(
            "allocationtable--sorted-column-heading",
            partial=True,
        )
        log(
            f"self._composed={self._composed} sort_column={sort_column}"
            f" highlighted_cols={self.HIGHLIGHTED_COLUMNS_BY_SORT_COLUMN[sort_column]}"
        )
        if column_idx in (0, len(self.columns) - 1):
            return Text(self.columns[column_idx], justify="center")
        elif column_idx in self.HIGHLIGHTED_COLUMNS_BY_SORT_COLUMN[sort_column]:
            return Text(
                self.columns[column_idx], justify="right", style=sort_column_style
            )
        else:
            return Text(self.columns[column_idx], justify="right").on(
                click=f"screen.sort({self.SORT_COLUMN_BY_CLICKED_COLUMN[column_idx]})"
            )

    def compose(self) -> ComposeResult:
        table: DataTable[Text] = DataTable(
            id="body_table", header_height=1, show_cursor=False, zebra_stripes=True
        )
        table.focus()
        for column_idx in range(len(self.columns)):
            table.add_column(self.get_heading(column_idx), key=str(column_idx))

        # Set an initial size for the Location column to avoid too many resizes
        table.ordered_columns[0].content_width = 50

        self._composed = True
        yield table

    def watch_current_thread(self) -> None:
        """Called when the current_thread attribute changes."""
        self.populate_table()

    def watch_merge_threads(self) -> None:
        """Called when the merge_threads attribute changes."""
        self.populate_table()

    def watch_snapshot(self) -> None:
        """Called when the snapshot attribute changes."""
        self.populate_table()

    def watch_sort_column_id(self, sort_column_id: int) -> None:
        """Called when the sort_column_id attribute changes."""
        table = self.query_one("#body_table", DataTable)

        for i in range(1, len(self.columns)):
            table.ordered_columns[i].label = self.get_heading(i)

        table.sort(table.ordered_columns[sort_column_id].key, reverse=True)

    def populate_table(self) -> None:
        """Method to render the TUI table."""
        table = self.query_one("#body_table", DataTable)

        if not table.columns:
            return

        allocation_entries = self.snapshot.records_by_location
        total_allocations = self.snapshot.heap_size
        num_allocations = sum(
            entry.n_allocations for entry in allocation_entries.values()
        )
        sorted_allocations = sorted(
            allocation_entries.items(),
            key=lambda item: getattr(
                item[1], self.KEY_TO_COLUMN_NAME[self.sort_column_id]
            ),
            reverse=True,
        )

        function_column_style = self.get_component_rich_style(
            "allocationtable--function-name", partial=True
        )

        # Clear previous table rows
        old_locations = set(table.rows)
        new_locations = set()

        for location, result in sorted_allocations:
            if not self.merge_threads and (
                self.current_thread not in result.thread_ids
            ):
                continue

            total_color = self._get_color(result.total_memory, total_allocations)
            own_color = self._get_color(result.own_memory, total_allocations)
            allocation_color = self._get_color(result.n_allocations, num_allocations)

            percent_total = result.total_memory / total_allocations * 100
            percent_own = result.own_memory / total_allocations * 100

            cells = [
                SortableText(
                    result.total_memory, size_fmt(result.total_memory), total_color
                ),
                SortableText(result.total_memory, f"{percent_total:.2f}%", total_color),
                SortableText(result.own_memory, size_fmt(result.own_memory), own_color),
                SortableText(result.own_memory, f"{percent_own:.2f}%", own_color),
                SortableText(
                    result.n_allocations, str(result.n_allocations), allocation_color
                ),
            ]

            row_key = str((location.function, location.file))
            new_locations.add(RowKey(row_key))

            if row_key not in table.rows:
                table.add_row(
                    Text(location.function, style=function_column_style),
                    *cells,
                    Text(_filename_to_module_name(location.file)),
                    key=row_key,
                )
            else:
                for col_idx, val in enumerate(cells, 1):
                    col_key = str(col_idx)
                    table.update_cell(row_key, col_key, val)

        for old_row_key in old_locations - new_locations:
            table.remove_row(old_row_key)

        table.sort(str(self.sort_column_id), reverse=True)


class Header(Widget):
    """Widget to display TUI header information."""

    pid = reactive("")
    command_line = reactive("")
    n_samples = reactive(0)
    start = datetime.now()
    last_update = reactive(start)

    def __init__(self, pid: Optional[int], cmd_line: Optional[str]):
        super().__init__()
        self.pid = str(pid) if pid is not None else "???"
        if not cmd_line:
            cmd_line = "???"
        self.command_line = escape(cmd_line)

    def compose(self) -> ComposeResult:
        header_metadata = HorizontalScroll(
            Container(
                Label(f"[b]PID[/]: {self.pid}", id="pid"),
                Label(f"[b]CMD[/]: {self.command_line}", shrink=False, id="cmd"),
                Label(id="tid"),
                Label(id="thread"),
                Label(id="samples"),
                Label(id="duration"),
                id="header_metadata_grid",
            ),
            Label(id="status_message"),
            id="header_metadata",
        )
        header_metadata.border_title = "(∩｀-´)⊃━☆ﾟ.*･｡ﾟ"
        yield Container(
            header_metadata,
            Container(MemoryGraph(max_data_points=50), id="memory_graph_container"),
            id="header_container",
        )

    def watch_n_samples(self, n_samples: int) -> None:
        """Called when the n_samples attribute changes."""
        self.query_one("#samples", Label).update(f"[b]Samples[/]: {n_samples}")

    def watch_last_update(self, last_update: datetime) -> None:
        """Called when the last_update attribute changes."""
        self.query_one("#duration", Label).update(
            f"[b]Duration[/]: {(last_update - self.start).total_seconds():.1f} seconds"
        )


class TUI(Screen[None]):
    """TUI main application class."""

    CSS_PATH = "tui.css"

    BINDINGS = [
        Binding("ctrl+z", "app.suspend_process"),
        Binding("q,esc", "app.quit", "Quit"),
        Binding("m", "toggle_merge_threads", "Merge Threads"),
        Binding("<,left", "previous_thread", "Previous Thread"),
        Binding(">,right", "next_thread", "Next Thread"),
        Binding("t", "sort(1)", "Sort by Total"),
        Binding("o", "sort(3)", "Sort by Own"),
        Binding("a", "sort(5)", "Sort by Allocations"),
        Binding("space", "toggle_pause", "Pause"),
        Binding("up", "scroll_grid('up')"),
        Binding("down", "scroll_grid('down')"),
    ]

    # Start with a non-empty list of threads so that we always have something
    # to display. This avoids "Thread 1 of 0" and fixes a DivideByZeroError
    # when switching threads before the first allocation is seen.
    _DUMMY_THREAD_LIST = [0]

    thread_idx = reactive(0)
    threads = reactive(_DUMMY_THREAD_LIST, always_update=True)
    snapshot = reactive(_EMPTY_SNAPSHOT)
    paused = reactive(False, init=False)
    disconnected = reactive(False, init=False)

    def __init__(self, pid: Optional[int], cmd_line: Optional[str], native: bool):
        self.pid = pid
        self.cmd_line = cmd_line
        self.native = native
        self._name_by_tid: Dict[int, str] = {}
        self._max_memory_seen = 0
        self._merge_threads = True
        super().__init__()

    @property
    def current_thread(self) -> int:
        return self.threads[self.thread_idx]

    def action_previous_thread(self) -> None:
        """An action to switch to previous thread."""
        if not self._merge_threads:
            self.thread_idx = (self.thread_idx - 1) % len(self.threads)

    def action_next_thread(self) -> None:
        """An action to switch to next thread."""
        if not self._merge_threads:
            self.thread_idx = (self.thread_idx + 1) % len(self.threads)

    def action_sort(self, col_number: int) -> None:
        """An action to sort the table rows based on a given column attribute."""
        self.update_sort_key(col_number)

    def _populate_header_thread_labels(self, thread_idx: int) -> None:
        if self._merge_threads:
            tid_label = "[b]TID[/]: *"
            thread_label = "[b]All threads[/]"
        else:
            tid_label = f"[b]TID[/]: {hex(self.current_thread)}"
            thread_label = f"[b]Thread[/] {thread_idx + 1} of {len(self.threads)}"
            thread_name = self._name_by_tid.get(self.current_thread)
            if thread_name:
                thread_label += f" ({thread_name})"

        self.query_one("#tid", Label).update(tid_label)
        self.query_one("#thread", Label).update(thread_label)

    def action_toggle_merge_threads(self) -> None:
        """An action to toggle showing allocations from all threads together."""
        self._merge_threads = not self._merge_threads
        redraw_footer(self.app)
        self.app.query_one(AllocationTable).merge_threads = self._merge_threads
        self._populate_header_thread_labels(self.thread_idx)

    def action_toggle_pause(self) -> None:
        """Toggle pause on keypress"""
        if self.paused or not self.disconnected:
            self.paused = not self.paused
            redraw_footer(self.app)
            if not self.paused:
                self.display_snapshot()

    def action_scroll_grid(self, direction: str) -> None:
        """Toggle pause on keypress"""
        grid = self.query_one(DataTable)
        getattr(grid, f"action_scroll_{direction}")()

    def watch_thread_idx(self, thread_idx: int) -> None:
        """Called when the thread_idx attribute changes."""
        self._populate_header_thread_labels(thread_idx)
        self.query_one(AllocationTable).current_thread = self.current_thread

    def watch_threads(self) -> None:
        """Called when the threads attribute changes."""
        self._populate_header_thread_labels(self.thread_idx)

    def watch_disconnected(self) -> None:
        self.update_label()
        redraw_footer(self.app)

    def watch_paused(self) -> None:
        self.update_label()

    def watch_snapshot(self, snapshot: Snapshot) -> None:
        """Called automatically when the snapshot attribute is updated"""
        self._latest_snapshot = snapshot
        self.display_snapshot()

    def update_label(self) -> None:
        status_message = []
        if self.paused:
            status_message.append("[yellow]Table updates paused[/]")
        if self.disconnected:
            status_message.append("[red]Remote has disconnected[/]")
        if status_message:
            status_message.insert(0, "[b]Status[/]:")

        log(f"updating status message to {' '.join(status_message)}")
        self.query_one("#status_message", Label).update(" ".join(status_message))

    def compose(self) -> ComposeResult:
        yield Container(
            Label("[b]Memray[/b] live tracking", id="head_title"),
            TimeDisplay(id="head_time_display"),
            id="head",
        )
        yield Header(pid=self.pid, cmd_line=escape(self.cmd_line or ""))
        yield AllocationTable()
        yield Footer()

    def display_snapshot(self) -> None:
        snapshot = self._latest_snapshot

        if snapshot is _EMPTY_SNAPSHOT:
            return

        header = self.query_one(Header)
        body = self.query_one(AllocationTable)
        graph = self.query_one(MemoryGraph)

        # We want to update many header fields even when paused
        header.n_samples += 1
        header.last_update = datetime.now()

        graph.add_value(snapshot.heap_size)

        # Other fields should only be updated when not paused.
        if self.paused:
            return

        name_by_tid = {record.tid: record.thread_name for record in snapshot.records}
        new_tids = name_by_tid.keys() - self._name_by_tid.keys()
        self._name_by_tid.update(name_by_tid)

        if new_tids:
            threads = self.threads
            if threads is self._DUMMY_THREAD_LIST:
                threads = []
            for tid in sorted(new_tids):
                threads.append(tid)
            self.threads = threads

        body.current_thread = self.current_thread
        if not self.paused:
            body.snapshot = snapshot

    def update_sort_key(self, col_number: int) -> None:
        """Method called to update the table sort key attribute."""
        body = self.query_one(AllocationTable)
        body.sort_column_id = col_number

    def rewrite_bindings(self, bindings: Bindings) -> None:
        if "space" in bindings and bindings["space"][1].description == "Pause":
            if self.paused:
                update_key_description(bindings, "space", "Unpause")
            elif self.disconnected:
                del bindings["space"]

        if self._merge_threads:
            bindings.pop("less_than_sign")
            bindings.pop("greater_than_sign")
            update_key_description(bindings, "m", "Unmerge Threads")

    @property
    def active_bindings(self) -> Dict[str, Any]:
        bindings = super().active_bindings.copy()
        self.rewrite_bindings(bindings)
        return bindings


class UpdateThread(threading.Thread):
    def __init__(self, app: "TUIApp", reader: SocketReader) -> None:
        self._app = app
        self._reader = reader
        self._update_requested = threading.Event()
        self._update_requested.set()
        self._canceled = threading.Event()
        super().__init__()

    def run(self) -> None:
        while self._update_requested.wait():
            if self._canceled.is_set():
                return
            self._update_requested.clear()

            records = list(self._reader.get_current_snapshot(merge_threads=False))
            heap_size = sum(record.size for record in records)
            records_by_location = aggregate_allocations(
                records, MAX_MEMORY_RATIO * heap_size, self._reader.has_native_traces
            )
            snapshot = Snapshot(
                heap_size=heap_size,
                records=records,
                records_by_location=records_by_location,
            )

            self._app.post_message(
                SnapshotFetched(
                    snapshot,
                    not self._reader.is_active,
                )
            )

            if not self._reader.is_active:
                return

    def cancel(self) -> None:
        self._canceled.set()
        self._update_requested.set()

    def schedule_update(self) -> None:
        self._update_requested.set()


class TUIApp(App[None]):
    """TUI main application class."""

    CSS_PATH = "tui.css"

    def __init__(
        self,
        reader: SocketReader,
        cmdline_override: Optional[str] = None,
        poll_interval: float = 1.0,
    ) -> None:
        self._reader = reader
        self._poll_interval = poll_interval
        self._cmdline_override = cmdline_override
        self._update_thread = UpdateThread(self, self._reader)
        self.tui: Optional[TUI] = None
        super().__init__()

    def on_mount(self) -> None:
        self._update_thread.start()

        self.set_interval(self._poll_interval, self._update_thread.schedule_update)
        cmd_line = (
            self._cmdline_override
            if self._cmdline_override is not None
            else self._reader.command_line
        )

        if cmd_line is not None and "/memray" in cmd_line:
            cmd_args = cmd_line.split()
            if any(cmd_args[0].endswith(p) for p in ("/memray", "/memray/__main__.py")):
                cmd_args[0] = "memray"
                cmd_line = " ".join(cmd_args)

        self.tui = TUI(
            pid=self._reader.pid,
            cmd_line=cmd_line,
            native=self._reader.has_native_traces,
        )
        self.push_screen(self.tui)

    def on_unmount(self) -> None:
        self._update_thread.cancel()
        if self._update_thread.is_alive():
            self._update_thread.join()

    def on_snapshot_fetched(self, message: SnapshotFetched) -> None:
        """Method called to process each fetched snapshot."""
        assert self.tui is not None
        with self.batch_update():
            self.tui.snapshot = message.snapshot
        if message.disconnected:
            self.tui.disconnected = True

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(0 <= event.size.width < 81, "narrow")

    if hasattr(App, "namespace_bindings"):
        # Removed in Textual 0.61
        @property
        def namespace_bindings(self) -> Dict[str, Tuple[DOMNode, Binding]]:
            bindings = super().namespace_bindings.copy()  # type: ignore[misc]
            if self.tui:
                self.tui.rewrite_bindings(bindings)
            return bindings  # type: ignore[no-any-return]
