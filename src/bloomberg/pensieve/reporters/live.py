import operator
from dataclasses import dataclass
from dataclasses import field
from typing import List

from rich.console import Console
from rich.console import ConsoleOptions
from rich.console import RenderResult
from rich.table import Column
from rich.table import Table

from bloomberg.pensieve import AllocationRecord
from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve._pensieve import size_fmt

MAX_TABLE_SIZE = 10


@dataclass
class LiveAllocationsReporter:
    allocations: List[AllocationRecord] = field(default_factory=list)

    def update(self, record: AllocationRecord) -> None:
        if record.size == 0:
            return

        if len(self.allocations) < MAX_TABLE_SIZE:
            self.allocations.append(record)
            self.allocations.sort(key=operator.attrgetter("size"))
            return

        for i, item in enumerate(self.allocations):
            if item.size < record.size:
                self.allocations[i] = record
                self.allocations.sort(key=operator.attrgetter("size"))
                break

    def get_current_table(self) -> Table:
        table = Table(
            Column("Location", ratio=5),
            Column("Allocator", ratio=1),
            Column("Thread ID", ratio=1),
            Column("Size", ratio=1),
            Column("Allocation Count", ratio=1),
            expand=True,
        )
        for record in reversed(self.allocations):
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


if __name__ == "__main__":
    import sys
    import time

    from rich.live import Live

    from bloomberg.pensieve import Tracker

    tracker = Tracker(sys.argv[1])
    reporter = LiveAllocationsReporter()

    live = Live(screen=True)
    with live:
        for record in tracker.reader.get_allocation_records():
            time.sleep(0.01)
            reporter.update(record)
            live.update(reporter)
