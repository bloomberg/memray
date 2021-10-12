from rich.console import Console
from rich.console import ConsoleOptions
from rich.console import RenderResult
from rich.table import Column
from rich.table import Table

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import SocketReader
from bloomberg.pensieve._pensieve import size_fmt


class LiveAllocationsReporter:
    def __init__(self, reader: SocketReader) -> None:
        self.reader = reader

    def get_current_table(self) -> Table:
        table = Table(
            Column("Location", ratio=5),
            Column("Allocator", ratio=1),
            Column("Thread ID", ratio=1),
            Column("Size", ratio=1),
            Column("Allocation Count", ratio=1),
            expand=True,
        )
        snapshot = list(self.reader.get_current_snapshot(merge_threads=False))
        for record in reversed(snapshot):
            stack_trace = list(record.stack_trace(max_stacks=1))

            location = "???"
            if stack_trace:
                function, file, line = stack_trace[0]
                location = f"{function} at {file}:{line}"

            table.add_row(
                location,
                str(AllocatorType(record.allocator).name.lower()),
                str(record.tid),
                size_fmt(record.size),
                str(record.n_allocations),
            )

        return table

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        yield self.get_current_table()
