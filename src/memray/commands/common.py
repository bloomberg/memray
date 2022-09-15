import argparse
import os
import pathlib
from pathlib import Path
from typing import Any
from typing import Iterable
from typing import Optional
from typing import Tuple

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore

from rich import print as pprint

from memray import AllocationRecord
from memray import FileReader
from memray import MemorySnapshot
from memray._errors import MemrayCommandError
from memray._memray import SymbolicSupport
from memray._memray import get_symbolic_support
from memray.reporters import BaseReporter


class ReporterFactory(Protocol):
    def __call__(
        self,
        allocations: Iterable[AllocationRecord],
        *,
        memory_records: Iterable[MemorySnapshot],
        native_traces: bool,
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


class HighWatermarkCommand:
    def __init__(
        self,
        reporter_factory: ReporterFactory,
        reporter_name: str,
        suffix: str = ".html",
    ) -> None:
        self.reporter_factory = reporter_factory
        self.reporter_name = reporter_name
        self.suffix = suffix
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
        **kwargs: Any,
    ) -> None:
        try:
            reader = FileReader(os.fspath(result_path), report_progress=True)
            if reader.metadata.has_native_traces:
                warn_if_not_enough_symbols()

            if show_memory_leaks:
                snapshot = reader.get_leaked_allocation_records(
                    merge_threads=merge_threads if merge_threads is not None else True
                )
            elif temporary_allocation_threshold >= 0:
                snapshot = reader.get_temporary_allocation_records(
                    threshold=temporary_allocation_threshold,
                    merge_threads=merge_threads if merge_threads is not None else True,
                )
            else:
                snapshot = reader.get_high_watermark_allocation_records(
                    merge_threads=merge_threads if merge_threads is not None else True
                )
            memory_records = tuple(reader.get_memory_snapshots())
            reporter = self.reporter_factory(
                snapshot,
                memory_records=memory_records,
                native_traces=reader.metadata.has_native_traces,
                **kwargs,
            )
        except OSError as e:
            raise MemrayCommandError(
                f"Failed to parse allocation records in {result_path}\nReason: {e}",
                exit_code=1,
            )

        with open(os.fspath(output_file.expanduser()), "w") as f:
            kwargs = {}
            if merge_threads is not None:
                kwargs["merge_threads"] = merge_threads
            reporter.render(
                outfile=f,
                metadata=reader.metadata,
                show_memory_leaks=show_memory_leaks,
                **kwargs,
            )

    def run(
        self, args: argparse.Namespace, parser: argparse.ArgumentParser, **kwargs: Any
    ) -> None:
        result_path, output_file = self.validate_filenames(
            output=args.output,
            results=args.results,
            overwrite=args.force,
        )
        self.output_file = output_file
        if hasattr(args, "split_threads"):
            kwargs["merge_threads"] = not args.split_threads

        self.write_report(
            result_path,
            output_file,
            args.show_memory_leaks,
            args.temporary_allocation_threshold,
            **kwargs,
        )

        print(f"Wrote {output_file}")
