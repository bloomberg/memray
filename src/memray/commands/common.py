import argparse
import os
import pathlib
import sys
from pathlib import Path
from textwrap import dedent
from typing import Iterable
from typing import List
from typing import Optional
from typing import Tuple

if sys.version_info >= (3, 8):
    from typing import Protocol
else:
    from typing_extensions import Protocol

from rich import print as pprint

from memray import AllocationRecord
from memray import FileReader
from memray import MemorySnapshot
from memray._errors import MemrayCommandError
from memray._memray import FileFormat
from memray._memray import SymbolicSupport
from memray._memray import TemporalAllocationRecord
from memray._memray import get_symbolic_support
from memray.reporters import BaseReporter


class ReporterFactory(Protocol):
    def __call__(
        self,
        allocations: Iterable[AllocationRecord],
        *,
        memory_records: Iterable[MemorySnapshot],
        native_traces: bool,
        inverted: bool,
    ) -> BaseReporter:
        ...


class TemporalReporterFactory(Protocol):
    def __call__(
        self,
        allocations: Iterable[TemporalAllocationRecord],
        *,
        memory_records: Iterable[MemorySnapshot],
        native_traces: bool,
        high_water_mark_by_snapshot: Optional[List[int]],
        inverted: bool,
    ) -> BaseReporter:
        ...


def warn_if_not_enough_symbols() -> None:
    support = get_symbolic_support()
    if support == SymbolicSupport.NONE:
        pprint(
            ":warning: [bold yellow] No symbol information was found for the "
            "Python interpreter [/] :warning:\n\n"
            "Without symbolic information reports showing native traces [b]may not "
            "accurately reflect stack traces[/]. Please use an interpreter built with "
            "debug symbols for best results. Check "
            "https://bloomberg.github.io/memray/native_mode.html for more information "
            "regarding how memray resolves symbols.\n"
        )
    elif support == SymbolicSupport.FUNCTION_NAME_ONLY:
        pprint(
            ":warning: [bold yellow] No debug information was found for the "
            "Python interpreter [/] :warning:\n\n"
            "Without debug information reports showing native traces [b]may not "
            "include file names and line numbers[/]. Please use an interpreter built with "
            "debug symbols for best results. Check "
            "https://bloomberg.github.io/memray/native_mode.html for more information "
            "regarding how memray resolves symbols.\n"
        )
    else:
        return


def warn_if_file_is_not_aggregated_and_is_too_big(
    reader: FileReader, result_path: Path
) -> None:
    FILE_SIZE_LIMIT = 10 * 1000 * 1000
    if (
        reader.metadata.file_format == FileFormat.ALL_ALLOCATIONS
        and result_path.stat().st_size > FILE_SIZE_LIMIT
    ):
        pprint(
            ":warning: [bold yellow] This capture file is large and may take a long"
            " time to process [/] :warning:\n\n"
            "Next time, consider using the `--aggregate` option to `memray run` to"
            " reduce the size of the file.\n"
            "Check https://bloomberg.github.io/memray/run.html#aggregated-capture-files"
            " for more information.\n"
        )


class HighWatermarkCommand:
    def __init__(
        self,
        reporter_factory: ReporterFactory,
        reporter_name: str,
        suffix: str = ".html",
        temporal_reporter_factory: Optional[TemporalReporterFactory] = None,
    ) -> None:
        self.reporter_factory = reporter_factory
        self.reporter_name = reporter_name
        self.suffix = suffix
        self.temporal_reporter_factory = temporal_reporter_factory
        self.output_file: Optional[Path] = None

    def determine_output_filename(self, results_file: pathlib.Path) -> pathlib.Path:
        output_name = results_file.with_suffix(self.suffix).name
        if output_name.startswith("memray-"):
            output_name = output_name[len("memray-") :]

        return results_file.parent / f"memray-{self.reporter_name}-{output_name}"

    def validate_filenames(
        self, output: Optional[str], results: str, overwrite: bool = False
    ) -> Tuple[Path, Path]:
        """Ensure that the filenames provided by the user are usable."""
        result_path = Path(results)
        if not result_path.exists() or not result_path.is_file():
            raise MemrayCommandError(f"No such file: {results}", exit_code=1)

        output_file = Path(
            output
            if output is not None
            else self.determine_output_filename(result_path)
        )
        if not overwrite and output_file.exists():
            raise MemrayCommandError(
                f"File already exists, will not overwrite: {output_file}",
                exit_code=1,
            )
        return result_path, output_file

    def write_report(
        self,
        result_path: Path,
        output_file: Path,
        show_memory_leaks: bool,
        temporary_allocation_threshold: int,
        merge_threads: Optional[bool] = None,
        inverted: Optional[bool] = None,
        temporal: bool = False,
        max_memory_records: Optional[int] = None,
    ) -> None:
        try:
            kwargs = {}
            if max_memory_records is not None:
                kwargs["max_memory_records"] = max_memory_records
            reader = FileReader(os.fspath(result_path), report_progress=True, **kwargs)
            merge_threads = True if merge_threads is None else merge_threads
            inverted = False if inverted is None else inverted

            if reader.metadata.has_native_traces:
                warn_if_not_enough_symbols()

            if not temporal and not temporary_allocation_threshold >= 0:
                warn_if_file_is_not_aggregated_and_is_too_big(reader, result_path)

            if temporal:
                assert self.temporal_reporter_factory is not None
                if show_memory_leaks:
                    temporal_snapshot = reader.get_temporal_allocation_records(
                        merge_threads=merge_threads
                    )
                    reporter = self.temporal_reporter_factory(
                        temporal_snapshot,
                        memory_records=tuple(reader.get_memory_snapshots()),
                        native_traces=reader.metadata.has_native_traces,
                        high_water_mark_by_snapshot=None,
                        inverted=inverted,
                    )
                else:
                    recs, hwms = reader.get_temporal_high_water_mark_allocation_records(
                        merge_threads=merge_threads
                    )
                    reporter = self.temporal_reporter_factory(
                        recs,
                        memory_records=tuple(reader.get_memory_snapshots()),
                        native_traces=reader.metadata.has_native_traces,
                        high_water_mark_by_snapshot=hwms,
                        inverted=inverted,
                    )
            else:
                if show_memory_leaks:
                    snapshot = reader.get_leaked_allocation_records(
                        merge_threads=merge_threads
                    )
                elif temporary_allocation_threshold >= 0:
                    snapshot = reader.get_temporary_allocation_records(
                        threshold=temporary_allocation_threshold,
                        merge_threads=merge_threads,
                    )
                else:
                    snapshot = reader.get_high_watermark_allocation_records(
                        merge_threads=merge_threads
                    )
                reporter = self.reporter_factory(
                    snapshot,
                    memory_records=tuple(reader.get_memory_snapshots()),
                    native_traces=reader.metadata.has_native_traces,
                    inverted=inverted,
                )
        except OSError as e:
            raise MemrayCommandError(
                f"Failed to parse allocation records in {result_path}\nReason: {e}",
                exit_code=1,
            )

        with open(os.fspath(output_file.expanduser()), "w") as f:
            reporter.render(
                outfile=f,
                metadata=reader.metadata,
                show_memory_leaks=show_memory_leaks,
                merge_threads=merge_threads,
                inverted=inverted,
            )

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-o",
            "--output",
            help="Output file name",
            default=None,
        )
        parser.add_argument(
            "-f",
            "--force",
            help="If the output file already exists, overwrite it",
            action="store_true",
            default=False,
        )
        if self.temporal_reporter_factory:
            parser.add_argument(
                "--temporal",
                help=(
                    "Generate a dynamic flame graph that can analyze"
                    " allocations in a user-selected time range."
                ),
                action="store_true",
                default=False,
            )

        alloc_type_group = parser.add_mutually_exclusive_group()
        alloc_type_group.add_argument(
            "--leaks",
            help="Show memory leaks, instead of peak memory usage",
            action="store_true",
            dest="show_memory_leaks",
            default=False,
        )
        alloc_type_group.add_argument(
            "--temporary-allocation-threshold",
            metavar="N",
            help=dedent(
                """
                Report temporary allocations, as opposed to leaked allocations
                or high watermark allocations.  An allocation is considered
                temporary if at most N other allocations occur before it is
                deallocated.  With N=0, an allocation is temporary only if it
                is immediately deallocated before any other allocation occurs.
                """
            ),
            action="store",
            dest="temporary_allocation_threshold",
            type=int,
            default=-1,
        )
        alloc_type_group.add_argument(
            "--temporary-allocations",
            help="Equivalent to --temporary-allocation-threshold=1",
            action="store_const",
            dest="temporary_allocation_threshold",
            const=1,
        )
        parser.add_argument("results", help="Results of the tracker run")

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        temporal = getattr(args, "temporal", False)
        if temporal and args.temporary_allocation_threshold >= 0:
            parser.error("Can't create a temporal flame graph of temporary allocations")

        result_path, output_file = self.validate_filenames(
            output=args.output,
            results=args.results,
            overwrite=args.force,
        )
        self.output_file = output_file
        kwargs = {}
        if hasattr(args, "split_threads"):
            kwargs["merge_threads"] = not args.split_threads

        if hasattr(args, "inverted"):
            kwargs["inverted"] = args.inverted

        if hasattr(args, "max_memory_records"):
            kwargs["max_memory_records"] = args.max_memory_records

        self.write_report(
            result_path,
            output_file,
            args.show_memory_leaks,
            args.temporary_allocation_threshold,
            temporal=temporal,
            **kwargs,
        )

        print(f"Wrote {output_file}")
