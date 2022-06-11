import argparse
import os
import pathlib
from pathlib import Path
from typing import Iterable
from typing import Optional
from typing import Tuple

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore

from memray import AllocationRecord
from memray import FileReader
from memray import MemorySnapshot
from memray._errors import MemrayCommandError
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


class HighWatermarkCommand:
    def __init__(
        self,
        reporter_factory: ReporterFactory,
        reporter_name: str,
    ) -> None:
        self.reporter_factory = reporter_factory
        self.reporter_name = reporter_name

    def determine_output_filename(self, results_file: pathlib.Path) -> pathlib.Path:
        output_name = results_file.with_suffix(".html").name
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
        merge_threads: Optional[bool] = None,
    ) -> None:
        try:
            reader = FileReader(os.fspath(result_path), report_progress=True)
            if show_memory_leaks:
                snapshot = reader.get_leaked_allocation_records(
                    merge_threads=merge_threads if merge_threads is not None else True
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

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        result_path, output_file = self.validate_filenames(
            output=args.output,
            results=args.results,
            overwrite=args.force,
        )
        kwargs = {}
        if hasattr(args, "split_threads"):
            kwargs["merge_threads"] = not args.split_threads
        self.write_report(result_path, output_file, args.show_memory_leaks, **kwargs)

        print(f"Wrote {output_file}")
