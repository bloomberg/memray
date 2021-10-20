import argparse
import time

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
        reader = SocketReader(port=args.port)
        reporter = LiveAllocationsReporter(reader)

        with reader:
            with Live() as live:
                live.update(reporter)
                while True:
                    time.sleep(1)
