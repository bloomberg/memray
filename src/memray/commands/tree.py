import argparse
import os
from pathlib import Path

from rich import print as rprint

from memray import FileReader
from memray._errors import MemrayCommandError
from memray._memray import size_fmt
from memray.reporters.tree import TreeReporter


class TreeCommand:
    """Generate a tree view in the terminal for peak memory usage"""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("results", help="Results of the tracker run")
        parser.add_argument(
            "-b",
            "--biggest-allocs",
            help="Show n biggest allocations (defaults to 10)",
            type=int,
            default=10,
        )

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        result_path = Path(args.results)
        if not result_path.exists() or not result_path.is_file():
            raise MemrayCommandError(f"No such file: {args.results}", exit_code=1)
        reader = FileReader(os.fspath(args.results), report_progress=True)
        try:
            snapshot = iter(
                reader.get_high_watermark_allocation_records(merge_threads=False)
            )
            reporter = TreeReporter.from_snapshot(
                snapshot,
                biggest_allocs=args.biggest_allocs,
                native_traces=reader.metadata.has_native_traces,
            )
        except OSError as e:
            raise MemrayCommandError(
                f"Failed to parse allocation records in {result_path}\nReason: {e}",
                exit_code=1,
            )
        print()
        header = "Allocation metadata"
        rprint(f"{header}\n{'-'*len(header)}")
        rprint(f"Command line arguments: '{reader.metadata.command_line}'")
        rprint(f"Peak memory size: {size_fmt(reader.metadata.peak_memory)}")
        rprint(f"Number of allocations: {reader.metadata.total_allocations}")
        print()
        header = f"Biggest {args.biggest_allocs} allocations:"
        rprint(header)
        rprint("-" * len(header))
        reporter.render()
