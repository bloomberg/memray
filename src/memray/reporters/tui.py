import os
from collections import defaultdict
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import DefaultDict
from typing import Deque
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple

from rich.layout import Layout
from rich.markup import escape
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Column
from rich.table import Table

from memray import AllocationRecord
from memray._memray import size_fmt

MAX_MEMORY_RATIO = 0.95

DEFAULT_TERMINAL_LINES = 24


class MemoryGraph:
    def __init__(
        self,
        width: int,
        height: int,
        minval: float,
        maxval: float,
    ):
        self._graph: List[Deque[str]] = [deque(maxlen=width) for _ in range(height)]
        self.width = width
        self.height = height
        self.minval = minval
        self.maxval = maxval
        self._previous_blocks = [0] * height
        values = [minval] * (2 * self.width + 1)
        self._values = deque(values, maxlen=2 * self.width + 1)
        self.lookup = [
            [" ", "⢀", "⢠", "⢰", "⢸"],
            ["⡀", "⣀", "⣠", "⣰", "⣸"],
            ["⡄", "⣄", "⣤", "⣴", "⣼"],
            ["⡆", "⣆", "⣦", "⣶", "⣾"],
            ["⡇", "⣇", "⣧", "⣷", "⣿"],
        ]

    def _value_to_blocks(self, value: float) -> List[int]:
        dots_per_block = 4
        if value < self.minval:
            n_dots = 0
        elif value > self.maxval:
            n_dots = dots_per_block * self.height
        else:
            n_dots = ceil(
                (value - self.minval)
                / (self.maxval - self.minval)
                * dots_per_block
                * self.height
            )
        blocks = [dots_per_block] * (n_dots // dots_per_block)
        if n_dots % dots_per_block > 0:
            blocks += [n_dots % dots_per_block]
        blocks += [0] * (self.height - len(blocks))
        return blocks

    def add_value(self, value: float) -> None:
        blocks = self._value_to_blocks(value)

        chars = reversed(
            tuple(self.lookup[i0][i1] for i0, i1 in zip(self._previous_blocks, blocks))
        )

        for row, char in enumerate(chars):
            self._graph[row].append(char)

        self._values.append(value)
        self._previous_blocks = blocks

    def reset_max(self, value: float) -> None:
        self._graph = [deque(maxlen=self.width) for _ in range(self.height)]
        self.maxval = value
        for value in self._values.copy():
            self.add_value(value)

    @property
    def graph(self) -> Tuple[str, ...]:
        return tuple("".join(chars) for chars in self._graph)


def _get_terminal_lines() -> int:
    try:
        return os.get_terminal_size().lines
    except OSError:
        return DEFAULT_TERMINAL_LINES


def _size_to_color(proportion_of_total: float) -> str:
    if proportion_of_total > 0.6:
        return "red"
    elif proportion_of_total > 0.2:
        return "yellow"
    elif proportion_of_total > 0.05:
        return "green"
    else:
        return "bright_green"


@dataclass(frozen=True, eq=True)
class Location:
    function: str
    file: str


@dataclass
class AllocationEntry:
    own_memory: int
    total_memory: int
    n_allocations: int
    thread_ids: Set[int]


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
        (function, file_name, _), *caller_frames = stack_trace
        location = Location(function=function, file=file_name)
        processed_allocations[location] = AllocationEntry(
            own_memory=allocation.size,
            total_memory=allocation.size,
            n_allocations=allocation.n_allocations,
            thread_ids={allocation.tid},
        )

        # Walk upwards and sum totals
        visited = set()
        for function, file_name, _ in caller_frames:
            location = Location(function=function, file=file_name)
            frame = processed_allocations[location]
            if location in visited:
                continue
            visited.add(location)
            frame.total_memory += allocation.size
            frame.n_allocations += allocation.n_allocations
            frame.thread_ids.add(allocation.tid)
    return processed_allocations


class TUIData:
    def __init__(self, pid: Optional[int], cmd_line: Optional[str], native: bool):
        self.pid = pid or "???"
        if not cmd_line:
            cmd_line = "???"
        if len(cmd_line) > 50:
            cmd_line = cmd_line[:50] + "..."
        self.command_line = escape(cmd_line)
        self.native = native
        self.n_samples = 0
        self.start = datetime.now()
        self.last_update = datetime.now()
        self.snapshot_data: Dict[Location, AllocationEntry] = {}
        self.current_memory_size = 0
        self.max_memory_seen = 0
        self.message = ""
        self.stream = MemoryGraph(50, 4, 0.0, 1024.0)
        self.total_allocations = 0


class TUI:
    KEY_TO_COLUMN_NAME = {
        1: "total_memory",
        2: "total_memory",
        3: "own_memory",
        4: "own_memory",
        5: "n_allocations",
    }
    KEY_TO_COLUMN_ID = {
        "t": 1,
        "o": 3,
        "a": 5,
    }

    # Start with a non-empty list of threads so that we always have something
    # to display. This avoids "Thread 1 of 0" and fixes a DivideByZeroError
    # when switching threads before the first allocation is seen.
    _DUMMY_THREAD_LIST = [0]

    def __init__(self, pid: Optional[int], cmd_line: Optional[str], native: bool):
        self.live_data = TUIData(pid, cmd_line, native)
        self.paused_data: Optional[TUIData] = None
        self.display_data = self.live_data

        self.is_paused = False
        self.active = True
        self._thread_idx = 0
        self._seen_threads: Set[int] = set()
        self._sort_field_name = "total_memory"
        self._sort_column_id = 1
        self._terminal_size = _get_terminal_lines()
        self._threads: List[int] = self._DUMMY_THREAD_LIST

        layout = Layout(name="root")
        layout.split(
            Layout(name="header", size=7),
            Layout(name="heap_size", size=2),
            Layout(name="table", ratio=1),
            Layout(name="message", size=1),
            Layout(name="footer", size=1),
        )
        self.layout = layout

        self.footer_paused_str = "[bold grey93 on dodger_blue1] U [/] Unpause View "
        self.footer_running_str = "[bold grey93 on dodger_blue1] P [/] Pause View "

        self.footer_dict = {
            "quit": "[bold grey93 on dodger_blue1] Q [/] Quit ",
            "prev_thread": "[bold grey93 on dodger_blue1] ←  [/] Previous Thread ",
            "next_thread": "[bold grey93 on dodger_blue1] →  [/] Next Thread ",
            "sort_tot": "[bold grey93 on dodger_blue1] T [/] Sort By Total ",
            "sort_own": "[bold grey93 on dodger_blue1] O [/] Sort By Own ",
            "sort_alloc": "[bold grey93 on dodger_blue1] A [/] Sort By Allocations ",
            "pause": self.footer_running_str,
        }

    def footer(self) -> str:
        return "".join(self.footer_dict.values())

    def pause(self) -> None:
        if not self.is_paused:
            self.paused_data = deepcopy(self.live_data)
            self.display_data = self.paused_data
            self.footer_dict["pause"] = self.footer_paused_str
            self.is_paused = True

    def unpause(self) -> None:
        if self.is_paused:
            self.display_data = self.live_data
            self.footer_dict["pause"] = self.footer_running_str
            self.is_paused = False

    def get_header(self) -> Table:
        header = Table.grid(expand=True)
        head = Table.grid(expand=True)
        head.add_column(justify="left", ratio=3)
        head.add_column(justify="right", ratio=7)
        head.add_row(
            "[b]Memray[/b] live tracking",
            datetime.now().ctime().replace(":", "[blink]:[/]"),
        )

        metadata = Table.grid(expand=False, padding=(0, 0, 0, 4))
        metadata.add_column(justify="left", ratio=5)
        metadata.add_column(justify="left", ratio=5)
        metadata.add_row("")
        metadata.add_row(
            f"[b]PID[/]: {self.display_data.pid}",
            f"[b]CMD[/]: {self.display_data.command_line}",
        )
        metadata.add_row(
            f"[b]TID[/]: {hex(self.current_thread)}",
            f"[b]Thread[/] {self._thread_idx + 1} of {len(self._threads)}",
        )
        metadata.add_row(
            f"[b]Samples[/]: {self.display_data.n_samples}",
            f"[b]Duration[/]: "
            f"{(self.display_data.last_update - self.display_data.start).total_seconds()}"
            f" seconds",
        )

        graph = "\n".join(self.display_data.stream.graph)
        plot = Panel(
            f"[color({2})]{graph}[/]",
            title="Memory",
            title_align="left",
            border_style="green",
            expand=False,
        )

        body = Table.grid(expand=True)
        body.add_column(justify="center", ratio=2)
        body.add_column(justify="center", ratio=5)
        body.add_column(justify="left", ratio=5)
        body.add_row("\n(∩｀-´)⊃━☆ﾟ.*･｡ﾟ\n", metadata, plot)

        header.add_row(head)
        header.add_row(body)
        return header

    def get_heap_size(self) -> Table:
        heap_grid = Table.grid(expand=True)
        metadata = Table.grid(expand=True)
        metadata.add_column(justify="left", ratio=5)
        metadata.add_column(justify="right", ratio=5)
        metadata.add_row(
            f"[bold]Current heap size[/]: {size_fmt(self.display_data.current_memory_size)}",
            f"[bold]Max heap size seen[/]: {size_fmt(self.display_data.max_memory_seen)}",
        )
        heap_grid.add_row(metadata)
        bar = ProgressBar(
            completed=self.display_data.current_memory_size,
            total=self.display_data.max_memory_seen + 1,
            complete_style="blue",
        )
        heap_grid.add_row(bar)
        return heap_grid

    def get_body(self, *, max_rows: Optional[int] = None) -> Table:
        max_rows = max_rows or self._terminal_size
        table = Table(
            Column("Location", ratio=5),
            Column("Total Memory", ratio=1, justify="right"),
            Column("Total Memory %", ratio=1, justify="right"),
            Column("Own Memory", ratio=1, justify="right"),
            Column("Own Memory % ", ratio=1, justify="right"),
            Column("Allocation Count", ratio=1, justify="right"),
            expand=True,
        )
        sort_column = table.columns[self._sort_column_id]
        sort_column.header = f"<{sort_column.header}>"

        sorted_allocations = sorted(
            self.display_data.snapshot_data.items(),
            key=lambda item: getattr(item[1], self._sort_field_name),
            reverse=True,
        )[:max_rows]
        for location, result in sorted_allocations:
            if self.current_thread not in result.thread_ids:
                continue
            color_location = (
                f"[bold magenta]{escape(location.function)}[/] at "
                f"[cyan]{escape(location.file)}[/]"
            )
            total_color = _size_to_color(
                result.total_memory / self.display_data.current_memory_size
            )
            own_color = _size_to_color(
                result.own_memory / self.display_data.current_memory_size
            )
            allocation_colors = _size_to_color(
                result.n_allocations / self.display_data.total_allocations
            )
            percent_total = (
                result.total_memory / self.display_data.current_memory_size * 100
            )
            percent_own = (
                result.own_memory / self.display_data.current_memory_size * 100
            )
            table.add_row(
                color_location,
                f"[{total_color}]{size_fmt(result.total_memory)}[/{total_color}]",
                f"[{total_color}]{percent_total:.2f}%[/{total_color}]",
                f"[{own_color}]{size_fmt(result.own_memory)}[/{own_color}]",
                f"[{own_color}]{percent_own:.2f}%[/{own_color}]",
                f"[{allocation_colors}]{result.n_allocations}[/{allocation_colors}]",
            )
        return table

    @property
    def message(self) -> str:
        return self.display_data.message

    @message.setter
    def message(self, message: str) -> None:
        self.display_data.message = message

    @property
    def current_thread(self) -> int:
        return self._threads[self._thread_idx]

    def next_thread(self) -> None:
        self._thread_idx = (self._thread_idx + 1) % len(self._threads)

    def previous_thread(self) -> None:
        self._thread_idx = (self._thread_idx - 1) % len(self._threads)

    def generate_layout(self) -> Layout:
        self.layout["header"].update(self.get_header())
        self.layout["heap_size"].update(self.get_heap_size())
        self.layout["table"].update(self.get_body())
        self.layout["message"].update(self.message)
        self.layout["footer"].update(self.footer())
        return self.layout

    def update_snapshot(self, snapshot: Iterable[AllocationRecord]) -> None:
        for record in snapshot:
            if record.tid in self._seen_threads:
                continue
            if self._threads is self._DUMMY_THREAD_LIST:
                self._threads = []
            self._threads.append(record.tid)
            self._seen_threads.add(record.tid)

        self.live_data.n_samples += 1
        self.live_data.last_update = datetime.now()
        self.live_data.current_memory_size = sum(record.size for record in snapshot)

        if self.live_data.current_memory_size > self.live_data.max_memory_seen:
            self.live_data.max_memory_seen = self.live_data.current_memory_size
            self.live_data.stream.reset_max(self.live_data.max_memory_seen)
        self.live_data.stream.add_value(self.live_data.current_memory_size)

        self.live_data.total_allocations = sum(
            record.n_allocations for record in snapshot
        )
        allocation_entries = aggregate_allocations(
            snapshot,
            MAX_MEMORY_RATIO * self.live_data.current_memory_size,
            self.live_data.native,
        )
        self.live_data.snapshot_data = allocation_entries

    def update_sort_key(self, col_number: int) -> None:
        self._sort_column_id = col_number
        self._sort_field_name = self.KEY_TO_COLUMN_NAME[col_number]
