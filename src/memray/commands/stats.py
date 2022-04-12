import argparse
import os
from pathlib import Path

from memray import FileReader
from memray._errors import MemrayCommandError
from memray.reporters.stats import StatsReporter


class StatsCommand:
    """Generate high level stats of the memory usage in the terminal"""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("results", help="Results of the tracker run")
        parser.add_argument(
            "-a",
            "--include-all-allocations",
            help="Include all allocations in the results, instead of "
            "peak-memory snapshot (Warning: could be much slower)",
            action="store_true",
        )

        def valid_positive_int(value: str) -> int:
            try:
                ivalue = int(value)
                if ivalue <= 0:
                    raise ValueError
            except ValueError:
                raise argparse.ArgumentTypeError(
                    f"{value} is an invalid positive int value"
                )

            return ivalue

        parser.add_argument(
            "-n",
            "--num-largest",
            help="Displays the top 'n' largest allocating functions. Default is 5",
            type=valid_positive_int,
            default=5,
        )

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        result_path = Path(args.results)
        if not result_path.exists() or not result_path.is_file():
            raise MemrayCommandError(f"No such file: {args.results}", exit_code=1)
        reader = FileReader(os.fspath(args.results))
        try:
            if args.include_all_allocations:
                snapshot = iter(reader.get_allocation_records())
            else:
                snapshot = iter(
                    reader.get_high_watermark_allocation_records(merge_threads=True)
                )
        except OSError as e:
            raise MemrayCommandError(
                f"Failed to parse allocation records in {result_path}\nReason: {e}",
                exit_code=1,
            )

        reporter = StatsReporter.from_snapshot(snapshot, args.num_largest)
        reporter.render()
