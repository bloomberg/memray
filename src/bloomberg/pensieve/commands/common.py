import argparse
import os
import pathlib
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
        reporter_factory: Callable[
            [Generator[AllocationRecord, None, None]], BaseReporter
        ],
    ) -> None:
        self.reporter_factory = reporter_factory

    @property
    def reporter_name(self) -> str:
        raise NotImplementedError

    def determine_output_filename(self, results_file: pathlib.Path) -> pathlib.Path:
        output_name = results_file.with_suffix(".html").name
        if output_name.startswith("pensieve-"):
            output_name = output_name[len("pensieve-") :]

        return results_file.parent / f"pensieve-{self.reporter_name}-{output_name}"

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-o",
            "--output",
            help="Output file name",
            default=None,
        )
        parser.add_argument(
            "--leaks",
            help="Show memory leaks, instead of peak memory usage.",
            action="store_true",
            dest="show_memory_leaks",
            default=False,
        )
        parser.add_argument("results", help="Results of the tracker run")

    def run(self, args: argparse.Namespace) -> int:
        # Check that the input file exists.
        result_path = Path(args.results)
        if not result_path.exists() or not result_path.is_file():
            print(f"No such file: {args.results}", file=sys.stderr)
            return 1

        # Check that the output file does not exist.
        output_file = Path(
            args.output
            if args.output is not None
            else self.determine_output_filename(result_path)
        )
        if output_file.exists():
            print(
                f"File already exists, will not overwrite: {output_file}",
                file=sys.stderr,
            )
            return 1

        tracker = Tracker(args.results)

        try:
            if args.show_memory_leaks:
                snapshot = tracker.reader.get_leaked_allocation_records()
            else:
                snapshot = tracker.reader.get_high_watermark_allocation_records()
            reporter = self.reporter_factory(snapshot)
        except OSError as e:
            print(
                f"Failed to parse allocation records in {args.results}",
                file=sys.stderr,
            )
            print(f"Reason: {e}", file=sys.stderr)
            return 1

        with open(os.fspath(output_file.expanduser()), "w") as f:
            reporter.render(f, tracker.reader.metadata)

        print(f"Wrote {output_file}")
        return 0
