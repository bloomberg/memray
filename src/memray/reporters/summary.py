import os
from typing import IO
from typing import Iterable
from typing import Optional

from rich import print as rprint
from rich.markup import escape
from rich.table import Column
from rich.table import Table

from memray import AllocationRecord
from memray._memray import size_fmt
from memray.reporters.tui import aggregate_allocations

MAX_MEMORY_RATIO = 0.95
DEFAULT_TERMINAL_LINES = 24


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


class SummaryReporter:
    KEY_TO_COLUMN_NAME = {
        1: "total_memory",
        2: "total_memory",
        3: "own_memory",
        4: "own_memory",
        5: "n_allocations",
    }

    N_COLUMNS = len(KEY_TO_COLUMN_NAME)

    def __init__(self, data: Iterable[AllocationRecord], native: bool):
        snapshot = tuple(data)
        self.current_memory_size = sum(record.size for record in snapshot)
        self.total_allocations = sum(record.n_allocations for record in snapshot)
        self.snapshot_data = aggregate_allocations(
            snapshot,
            MAX_MEMORY_RATIO * self.current_memory_size,
            native,
        )

    @classmethod
    def from_snapshot(
        cls, allocations: Iterable[AllocationRecord], native: bool = False
    ) -> "SummaryReporter":
        return cls(allocations, native=native)

    def render(
        self,
        sort_column: int,
        *,
        max_rows: Optional[int] = None,
        file: Optional[IO[str]] = None,
    ) -> None:
        # If no rows need to be split across 2 lines, using 5 fewer rows in
        # the data table than the number of terminal lines lets us fit entirely
        # on 1 full page regardless of whether the user has a 1 line or 2 line
        # shell prompt. With a 2 line prompt we lose the top dashed line.
        max_rows = max_rows or max(_get_terminal_lines() - 5, 10)
        table = Table(
            Column("Location", ratio=5),
            Column("Total Memory", ratio=1, justify="right"),
            Column("Total Memory %", ratio=1, justify="right"),
            Column("Own Memory", ratio=1, justify="right"),
            Column("Own Memory % ", ratio=1, justify="right"),
            Column("Allocation Count", ratio=1, justify="right"),
            expand=True,
        )
        table.columns[sort_column].header = f"<{table.columns[sort_column].header}>"

        sorted_allocations = sorted(
            self.snapshot_data.items(),
            key=lambda item: getattr(item[1], self.KEY_TO_COLUMN_NAME[sort_column]),
            reverse=True,
        )[:max_rows]
        for location, result in sorted_allocations:
            color_location = (
                f"[bold magenta]{escape(location.function)}[/] at "
                f"[cyan]{escape(location.file)}[/]"
            )
            total_color = _size_to_color(result.total_memory / self.current_memory_size)
            own_color = _size_to_color(result.own_memory / self.current_memory_size)
            allocation_colors = _size_to_color(
                result.n_allocations / self.total_allocations
            )
            percent_total = result.total_memory / self.current_memory_size * 100
            percent_own = result.own_memory / self.current_memory_size * 100
            table.add_row(
                color_location,
                f"[{total_color}]{size_fmt(result.total_memory)}[/{total_color}]",
                f"[{total_color}]{percent_total:.2f}%[/{total_color}]",
                f"[{own_color}]{size_fmt(result.own_memory)}[/{own_color}]",
                f"[{own_color}]{percent_own:.2f}%[/{own_color}]",
                f"[{allocation_colors}]{result.n_allocations}[/{allocation_colors}]",
            )

        rprint(table, file=file)
