import argparse
import os
import sys
import termios
from collections import defaultdict
from collections import deque
from contextlib import suppress
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
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Column
from rich.table import Table

from bloomberg.pensieve import AllocationRecord
from bloomberg.pensieve import SocketReader
from bloomberg.pensieve._errors import PensieveCommandError
from bloomberg.pensieve._pensieve import size_fmt

MAX_MEMORY_RATIO = 0.95

KEYS = {
    "ESC": "\x1b",
    "CTRL_C": "\x03",
    "LEFT": "\x1b\x5b\x44",
    "RIGHT": "\x1b\x5b\x43",
    "O": "o",
    "T": "t",
    "A": "a",
}


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


def _readchar() -> str:  # pragma: no cover
    """Read a single character from standard input without echoing.

    This function configures the current terminal and its standard
    input to:

        * Deactivate character echoing
        * Deactivate canonical mode (see 'termios' man page).

    Then, it reads a single character from standard input.

    After the character has been read, it restores the previous configuration.
    """
    if not sys.stdin.isatty():
        return sys.stdin.read(1)
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    new_settings = termios.tcgetattr(fd)
    new_settings[3] = new_settings[3] & ~termios.ECHO & ~termios.ICANON
    termios.tcsetattr(fd, termios.TCSANOW, new_settings)
    try:
        char = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return char


def readkey() -> str:  # pragma: no cover
    """Read a key press respecting ANSI Escape sequences.

    A key-stroke can have:

        1 character for normal keys: 'a', 'z', '9'...
        2 characters for combinations with ALT: ALT+A, ...
        3 characters for cursors: ->, <-, ...
        4 characters for combinations with CTRL and ALT: CTRL+ALT+SUPR
    """
    c1 = _readchar()
    if not c1 or ord(c1) != 0x1B:  # ESC
        return c1
    c2 = _readchar()
    if ord(c2) != 0x5B:  # [
        return c1 + c2
    c3 = _readchar()
    if ord(c3) != 0x33:  # 3 (one more char is needed)
        return c1 + c2 + c3
    c4 = _readchar()
    return c1 + c2 + c3 + c4


def _size_to_color(proportion_of_total: float) -> str:
    if proportion_of_total > 0.6:
        return "red"
    elif proportion_of_total > 0.2:
        return "yellow"
    elif proportion_of_total > 0.05:
        return "green"
    else:
        return "bright_green"


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


class TUI:
    KEY_TO_COLUMN_NAME = {
        "t": "total_memory",
        "o": "own_memory",
        "a": "n_allocations",
    }
    KEY_TO_COLUMN_ID = {
        "t": 1,
        "o": 2,
        "a": 3,
    }

    def __init__(self, pid: Optional[int], cmd_line: Optional[str], native: bool):
        self.pid = pid or "???"
        if not cmd_line:
            cmd_line = "???"
        if len(cmd_line) > 50:
            cmd_line = cmd_line[:50] + "..."
        self.command_line = escape(cmd_line)
        self._native = native
        self._thread_idx = 0
        self._seen_threads: Set[int] = set()
        self._threads: List[int] = []
        self.n_samples = 0
        self.start = datetime.now()
        self._last_update = datetime.now()
        self._snapshot: Tuple[AllocationRecord, ...] = tuple()
        self._current_memory_size = 0
        self._max_memory_seen = 0
        self._message = ""
        self.active = True
        self._sort_field_name = "total_memory"
        self._sort_column_id = 1
        self._terminal_size = _get_terminal_lines()
        self.stream = MemoryGraph(50, 4, 0.0, 1024.0)

        layout = Layout(name="root")
        layout.split(
            Layout(name="header", size=7),
            Layout(name="heap_size", size=2),
            Layout(name="table", ratio=1),
            Layout(name="message", size=1),
            Layout(name="footer", size=1),
        )
        layout["footer"].update(
            "[bold grey93 on dodger_blue1] Q [/] Quit "
            "[bold grey93 on dodger_blue1] ←  [/] Previous Thread "
            "[bold grey93 on dodger_blue1] →  [/] Next Thread "
            "[bold grey93 on dodger_blue1] T [/] Sort By Total "
            "[bold grey93 on dodger_blue1] O [/] Sort By Own "
            "[bold grey93 on dodger_blue1] A [/] Sort By Allocations "
        )
        self.layout = layout

    def get_header(self) -> Table:
        header = Table.grid(expand=True)
        head = Table.grid(expand=True)
        head.add_column(justify="left", ratio=3)
        head.add_column(justify="right", ratio=7)
        head.add_row(
            "[b]Bloomberg pensieve[/b] live tracking",
            datetime.now().ctime().replace(":", "[blink]:[/]"),
        )

        metadata = Table.grid(expand=False, padding=(0, 0, 0, 4))
        metadata.add_column(justify="left", ratio=5)
        metadata.add_column(justify="left", ratio=5)
        metadata.add_row("")
        metadata.add_row(f"[b]PID[/]: {self.pid}", f"[b]CMD[/]: {self.command_line}")
        metadata.add_row(
            f"[b]TID[/]: {hex(self.current_thread)}",
            f"[b]Thread[/] {self._thread_idx + 1} of {len(self._threads)}",
        )
        metadata.add_row(
            f"[b]Samples[/]: {self.n_samples}",
            f"[b]Duration[/]: {(self._last_update - self.start).total_seconds()} seconds",
        )

        graph = "\n".join(self.stream.graph)
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
            f"[bold]Current heap size[/]: {size_fmt(self._current_memory_size)}",
            f"[bold]Max heap size seen[/]: {size_fmt(self._max_memory_seen)}",
        )
        heap_grid.add_row(metadata)
        bar = ProgressBar(
            completed=self._current_memory_size,
            total=self._max_memory_seen + 1,
            complete_style="blue",
        )
        heap_grid.add_row(bar)
        return heap_grid

    def get_body(self) -> Table:
        table = Table(
            Column("Location", ratio=5),
            Column("Total Memory", ratio=1),
            Column("Own Memory", ratio=1),
            Column("Allocation Count", ratio=1),
            expand=True,
        )
        sort_column = table.columns[self._sort_column_id]
        sort_column.header = f"<{sort_column.header}>"

        total_allocations = sum(record.n_allocations for record in self._snapshot)
        allocation_entries = aggregate_allocations(
            self._snapshot, MAX_MEMORY_RATIO * self._current_memory_size, self._native
        )

        sorted_allocations = sorted(
            allocation_entries.items(),
            key=lambda item: getattr(  # type: ignore[no-any-return]
                item[1], self._sort_field_name
            ),
            reverse=True,
        )[: self._terminal_size]
        for location, result in sorted_allocations:
            if self.current_thread not in result.thread_ids:
                continue
            color_location = (
                f"[bold magenta]{escape(location.function)}[/] at "
                f"[cyan]{escape(location.file)}[/]"
            )
            total_color = _size_to_color(
                result.total_memory / self._current_memory_size
            )
            own_color = _size_to_color(result.own_memory / self._current_memory_size)
            allocation_colors = _size_to_color(result.n_allocations / total_allocations)
            table.add_row(
                color_location,
                f"[{total_color}]{size_fmt(result.total_memory)}[/{total_color}]",
                f"[{own_color}]{size_fmt(result.own_memory)}[/{own_color}]",
                f"[{allocation_colors}]{result.n_allocations}[/{allocation_colors}]",
            )
        return table

    @property
    def message(self) -> str:
        return self._message

    @message.setter
    def message(self, message: str) -> None:
        self._message = message

    @property
    def current_thread(self) -> int:
        if not self._threads:
            return 0
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
        return self.layout

    def update_snapshot(self, snapshot: Iterable[AllocationRecord]) -> None:
        self._snapshot = tuple(snapshot)
        for record in self._snapshot:
            if record.tid in self._seen_threads:
                continue
            self._threads.append(record.tid)
            self._seen_threads.add(record.tid)
        self.n_samples += 1
        self._last_update = datetime.now()
        self._current_memory_size = sum(record.size for record in self._snapshot)
        if self._current_memory_size > self._max_memory_seen:
            self._max_memory_seen = self._current_memory_size
            self.stream.reset_max(self._max_memory_seen)
        self.stream.add_value(self._current_memory_size)

    def update_sort_key(self, key: str) -> None:
        self._sort_field_name = self.KEY_TO_COLUMN_NAME[key]
        self._sort_column_id = self.KEY_TO_COLUMN_ID[key]


class LiveCommand:
    """Remotely monitor allocations in a text-based interface."""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "port",
            help="Remote port to connect to",
            default=None,
            type=int,
        )

    def run(self, args: argparse.Namespace) -> None:
        with suppress(KeyboardInterrupt):
            self._run(args)

    def _run(self, args: argparse.Namespace) -> None:
        port = args.port
        if port >= 2 ** 16 or port <= 0:
            raise PensieveCommandError(f"Invalid port: {port}", exit_code=1)
        with SocketReader(port=port) as reader:
            tui = TUI(reader.pid, reader.command_line, reader.has_native_traces)

            def _get_renderable() -> Layout:
                if tui.active:
                    snapshot = list(reader.get_current_snapshot(merge_threads=False))
                    tui.update_snapshot(snapshot)

                if not reader.is_active:
                    tui.active = False
                    tui.message = "[red]Remote has disconnected[/]"

                return tui.generate_layout()

            with Live(get_renderable=_get_renderable, screen=True):
                while True:
                    char = readkey()
                    if char == KEYS["LEFT"]:
                        tui.previous_thread()
                    if char == KEYS["RIGHT"]:
                        tui.next_thread()
                    elif char in {"q", KEYS["ESC"]}:
                        break
                    elif char.lower() in TUI.KEY_TO_COLUMN_ID.keys():
                        tui.update_sort_key(char.lower())
                    elif char == KEYS["CTRL_C"]:
                        raise KeyboardInterrupt()
