import argparse

from rich.live import Live

from bloomberg.pensieve import SocketReader
from bloomberg.pensieve.reporters.live import LiveAllocationsReporter


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
        reporter = LiveAllocationsReporter()

        with Live(screen=True, auto_refresh=False, refresh_per_second=30) as live:
            for record in SocketReader(port=args.port).get_allocation_records():
                reporter.update(record)
                live.update(reporter)
            live.console.input()
