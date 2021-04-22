import argparse
import sys
from pathlib import Path
from typing import Callable
from typing import Generator

from bloomberg.pensieve import Tracker
from bloomberg.pensieve._pensieve import AllocationRecord
from bloomberg.pensieve.reporters import BaseReporter


class HighWatermarkCommand:
    def __init__(
        self,
        default_output_file: str,
        reporter_factory: Callable[
            [Generator[AllocationRecord, None, None]], BaseReporter
        ],
    ) -> None:
        self.default_output_file = default_output_file
        self.reporter_factory = reporter_factory

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-o",
            "--output",
            help="Output file name",
            default=self.default_output_file,
        )
        parser.add_argument("results", help="Results of the tracker run")

    def run(
        self,
        args: argparse.Namespace,
    ) -> int:
        if not Path(args.results).exists():
            print(f"No such file: {args.results}", file=sys.stderr)
            return 1

        tracker = Tracker(args.results)
        snapshot = tracker.reader.get_high_watermark_allocation_records()

        try:
            reporter = self.reporter_factory(snapshot)
        except OSError:
            print(
                f"Failed to parse allocation records in {args.results}",
                file=sys.stderr,
            )
            return 1

        with open(args.output, "w") as f:
            reporter.render(f, tracker.reader.metadata)

        print(f"Wrote {args.output}")
        return 0
