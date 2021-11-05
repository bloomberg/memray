import argparse
import sys
import termios
from datetime import datetime
from typing import Iterable
from typing import List
from typing import Set
from typing import Tuple

from rich.layout import Layout
from rich.live import Live
from rich.markup import escape
from rich.progress_bar import ProgressBar
from rich.table import Column
from rich.table import Table

from bloomberg.pensieve import AllocationRecord
from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import SocketReader
from bloomberg.pensieve._errors import PensieveCommandError
from bloomberg.pensieve._pensieve import size_fmt

KEYS = {
    "ESC": "\x1b",
    "CTRL_C": "\x03",
    "LEFT": "\x1b\x5b\x44",
    "RIGHT": "\x1b\x5b\x43",
}


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
    if ord(c1) != 0x1B:  # ESC
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


class TUI:
    def __init__(self, pid: int, cmd_line: str):
        self.pid = 123
        if len(cmd_line) > 50:
            cmd_line = cmd_line[:50] + "..."
        self.command_line = escape(cmd_line)
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

        layout = Layout(name="root")
        layout.split(
            Layout(name="header", size=5),
            Layout(name="heap_size", size=2),
            Layout(name="table", ratio=1),
            Layout(name="message", size=1),
            Layout(name="footer", size=1),
        )
        layout["footer"].update(
            "[bold grey93 on dodger_blue1] Q [/] Quit "
            "[bold grey93 on dodger_blue1] ←  [/] Previous Thread "
            "[bold grey93 on dodger_blue1] →  [/] Next Thread"
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
        metadata.add_row(f"[b]PID[/]: {self.pid}", f"[b]CMD[/]: {self.command_line}")
        metadata.add_row(
            f"[b]TID[/]: {hex(self.current_thread)}",
            f"[b]Thread[/] {self._thread_idx + 1} of {len(self._threads)}",
        )
        metadata.add_row(
            f"[b]Samples[/]: {self.n_samples}",
            f"[b]Duration[/]: {(self._last_update - self.start).total_seconds()} seconds",
        )

        body = Table.grid(expand=True)
        body.add_column(justify="center", ratio=2)
        body.add_column(justify="center", ratio=10)
        body.add_row("\n(∩｀-´)⊃━☆ﾟ.*･｡ﾟ\n", metadata)

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
            Column("Allocator", ratio=1),
            Column("Size", ratio=1),
            Column("Allocation Count", ratio=1),
            expand=True,
        )
        total_allocations = sum(record.n_allocations for record in self._snapshot)
        for record in sorted(self._snapshot, key=lambda r: r.size, reverse=True):
            if record.tid != self.current_thread:
                continue
            stack_trace = list(record.stack_trace(max_stacks=1))
            location = "???"
            if stack_trace:
                function, file, line = stack_trace[0]
                location = (
                    f"[bold magenta]{escape(function)}[/] at "
                    f"[cyan]{escape(file)}[/]:[blue]{line}[/]"
                )
            size_color = _size_to_color(record.size / self._current_memory_size)
            allocation_colors = _size_to_color(record.n_allocations / total_allocations)
            table.add_row(
                location,
                str(AllocatorType(record.allocator).name.lower()),
                f"[{size_color}]{size_fmt(record.size)}[/{size_color}]",
                f"[{allocation_colors}]{record.n_allocations}[/{allocation_colors}]",
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
        self._max_memory_seen = max(self._max_memory_seen, self._current_memory_size)


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
        port = args.port
        if port >= 2 ** 16 or port <= 0:
            raise PensieveCommandError(f"Invalid port: {port}", exit_code=1)
        with SocketReader(port=port) as reader:
            tui = TUI(3, reader.command_line or "???")

            def _get_renderable() -> Layout:
                if not reader.is_active:
                    tui.message = "[red]Remote has disconnected[/]"
                else:
                    snapshot = reader.get_current_snapshot(merge_threads=False)
                    tui.update_snapshot(snapshot)

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
                    elif char == KEYS["CTRL_C"]:
                        raise KeyboardInterrupt()
