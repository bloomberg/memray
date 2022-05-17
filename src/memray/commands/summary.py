import argparse
import os
from pathlib import Path

from memray import FileReader
from memray._errors import MemrayCommandError
from memray.reporters.summary import SummaryReporter


class SummaryCommand:
    """Generate a terminal-based summary report of the functions that allocate most memory"""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("results", help="Results of the tracker run")
        parser.add_argument(
            "-s",
            "--sort-column",
            help="Column number to sort on",
            type=int,
            default=1,
        )
        parser.add_argument(
            "-r",
            "--max-rows",
            help="Maximum number of rows to display",
            type=int,
            default=None,
        )

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        max_cols = SummaryReporter.N_COLUMNS
        if args.sort_column < 1 or args.sort_column > max_cols:
            parser.error(f"The --sort-column argument must be between 1 and {max_cols}")

        result_path = Path(args.results)
        if not result_path.exists() or not result_path.is_file():
            raise MemrayCommandError(f"No such file: {args.results}", exit_code=1)
        reader = FileReader(os.fspath(args.results), report_progress=True)
        try:
            snapshot = iter(
                reader.get_high_watermark_allocation_records(merge_threads=True)
            )
        except OSError as e:
            raise MemrayCommandError(
                f"Failed to parse allocation records in {result_path}\nReason: {e}",
                exit_code=1,
            )

        reporter = SummaryReporter.from_snapshot(
            snapshot,
            native=reader.metadata.has_native_traces,
        )
        reporter.render(sort_column=args.sort_column, max_rows=args.max_rows)
