import argparse
import os
from pathlib import Path

from memray import FileReader
from memray._errors import MemrayCommandError
from memray.commands.common import warn_if_file_is_not_aggregated_and_is_too_big
from memray.commands.common import warn_if_not_enough_symbols
from memray.reporters.summary import SummaryReporter


class SummaryCommand:
    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        max_cols = SummaryReporter.N_COLUMNS
        if args.sort_column < 1 or args.sort_column > max_cols:
            parser.error(f"The --sort-column argument must be between 1 and {max_cols}")

        result_path = Path(args.results)
        if not result_path.exists() or not result_path.is_file():
            raise MemrayCommandError(f"No such file: {args.results}", exit_code=1)

        try:
            reader = FileReader(os.fspath(args.results), report_progress=True)
            if reader.metadata.has_native_traces:
                warn_if_not_enough_symbols()

            if not args.temporary_allocation_threshold >= 0:
                warn_if_file_is_not_aggregated_and_is_too_big(reader, result_path)

            if args.temporary_allocation_threshold >= 0:
                snapshot = iter(
                    reader.get_temporary_allocation_records(
                        threshold=args.temporary_allocation_threshold,
                        merge_threads=False,
                    )
                )
            else:
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
