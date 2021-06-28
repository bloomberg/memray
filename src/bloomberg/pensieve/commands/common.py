import argparse
import os
import pathlib
import sys
from pathlib import Path
from typing import Callable
from typing import Generator
from typing import Optional
from typing import Tuple

from bloomberg.pensieve import Tracker
from bloomberg.pensieve._pensieve import AllocationRecord
from bloomberg.pensieve.reporters import BaseReporter


class HighWatermarkCommand:
    def __init__(
        self,
        reporter_factory: Callable[
            [Generator[AllocationRecord, None, None]], BaseReporter
        ],
        reporter_name: str,
    ) -> None:
        self.reporter_factory = reporter_factory
        self.reporter_name = reporter_name

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
            help="Show memory leaks, instead of peak memory usage",
            action="store_true",
            dest="show_memory_leaks",
            default=False,
        )
        parser.add_argument(
            "--split-threads",
            help="Do not merge allocations across threads",
            action="store_true",
            default=False,
        )
        parser.add_argument("results", help="Results of the tracker run")

    def validate_filenames(
        self, output: Optional[str], results: str
    ) -> Tuple[Path, Path]:
        """Ensure that the filenames provided by the user are usable."""
        result_path = Path(results)
        if not result_path.exists() or not result_path.is_file():
            raise OSError(f"No such file: {results}")

        output_file = Path(
            output
            if output is not None
            else self.determine_output_filename(result_path)
        )
        if output_file.exists():
            raise OSError(
                f"File already exists, will not overwrite: {output_file}",
            )
        return result_path, output_file

    def write_report(
        self,
        result_path: Path,
        output_file: Path,
        show_memory_leaks: bool,
        merge_threads: bool,
    ) -> None:
        tracker = Tracker(os.fspath(result_path))
        try:
            if show_memory_leaks:
                snapshot = tracker.reader.get_leaked_allocation_records(
                    merge_threads=merge_threads
                )
            else:
                snapshot = tracker.reader.get_high_watermark_allocation_records(
                    merge_threads=merge_threads
                )
            reporter = self.reporter_factory(snapshot)
        except OSError:
            print(
                f"Failed to parse allocation records in {result_path}",
                file=sys.stderr,
            )
            raise

        with open(os.fspath(output_file.expanduser()), "w") as f:
            reporter.render(
                outfile=f,
                metadata=tracker.reader.metadata,
                show_memory_leaks=show_memory_leaks,
            )

    def run(self, args: argparse.Namespace) -> int:
        try:
            result_path, output_file = self.validate_filenames(
                output=args.output,
                results=args.results,
            )
        except OSError as e:
            print(e, file=sys.stderr)
            return 1

        try:
            self.write_report(
                result_path,
                output_file,
                args.show_memory_leaks,
                merge_threads=not args.split_threads,
            )
        except OSError as e:
            print(f"Aborting due to {e}", file=sys.stderr)
            return 1

        print(f"Wrote {output_file}")
        return 0
