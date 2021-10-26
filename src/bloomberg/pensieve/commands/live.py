import argparse
import time
from typing import Iterable

from rich.console import Group
from rich.live import Live
from rich.markup import escape
from rich.table import Column
from rich.table import Table

from bloomberg.pensieve import AllocationRecord
from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import SocketReader
from bloomberg.pensieve._pensieve import size_fmt


def construct_allocation_table(snapshot: Iterable[AllocationRecord]) -> Table:
    table = Table(
        Column("Location", ratio=5),
        Column("Allocator", ratio=1),
        Column("Thread ID", ratio=1),
        Column("Size", ratio=1),
        Column("Allocation Count", ratio=1),
        expand=True,
    )
    for record in sorted(snapshot, key=lambda r: r.size, reverse=True):
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
        reader = SocketReader(port=args.port)

        with reader, Live(screen=True, auto_refresh=False) as live:
            header = f"[bold]Command line:[/] {escape(reader.command_line or '???')}"
            while True:
                snapshot = reader.get_current_snapshot(merge_threads=False)
                table = construct_allocation_table(snapshot)
                live.update(Group(header, table), refresh=True)
                time.sleep(0.25)
