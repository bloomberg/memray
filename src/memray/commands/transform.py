import argparse
import importlib.util
import os
import shutil
import sys
from pathlib import Path
from typing import Callable
from typing import Optional
from typing import cast

from rich import print as pprint

from memray import FileReader
from memray._errors import MemrayCommandError
from memray._memray import FileFormat

from ..reporters.transform import TransformReporter
from .common import HighWatermarkCommand
from .common import warn_if_file_is_not_aggregated_and_is_too_big
from .common import warn_if_not_enough_symbols


class TransformCommand(HighWatermarkCommand):
    """Generate reports files in different formats"""

    def __init__(self) -> None:
        super().__init__(
            reporter_factory=lambda *args, **kwargs: TransformReporter(
                *args, **kwargs, format=self.reporter_name
            ),
            reporter_name="transform",
        )

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        formats = ", ".join(TransformReporter.SUFFIX_MAP)
        parser.add_argument(
            "format",
            help=f"Format to use for the report. Available formats: {formats}",
        )
        super().prepare_parser(parser)

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        the_format = args.format.lower()
        suffix = TransformReporter.SUFFIX_MAP.get(the_format)
        if not suffix:
            raise MemrayCommandError(
                f"Format not supported: {args.format}", exit_code=1
            )

        self.suffix = suffix
        self.reporter_name = the_format
        super().run(args, parser)

        post_run_callable = getattr(self, f"post_run_{the_format}", None)
        if post_run_callable:
            post_run_callable()

    def post_run_gprof2dot(self) -> None:
        assert self.output_file is not None
        command = ""
        if shutil.which("gprof2dot") is not None:
            command = "gprof2dot"
        elif importlib.util.find_spec("gprof2dot") is not None:
            command = f"{sys.executable} -m gprof2dot"
        else:
            pprint(
                ":exclamation: [red]gprof2dot doesn't seem to be installed. "
                "Please install it to be able to process the transform.[/red]"
                "\n:point_right: Check out https://github.com/jrfonseca/gprof2dot for "
                "installation instructions"
            )

        if not shutil.which("dot"):
            pprint(
                ":exclamation: [red]Graphviz doesn't seem to be installed. "
                "Please install it to be able to process the transform.[/red]"
                "\n:point_right: Check out https://graphviz.org/download/ for "
                "installation instructions"
            )

        print()
        print("To generate a graph from the transform file, run for example:")
        print(f"{command} -f json {self.output_file} | dot -Tpng -o output.png")

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
        no_web: bool = False,
    ) -> None:
        if self.reporter_name != "speedscope":
            return super().write_report(
                result_path=result_path,
                output_file=output_file,
                show_memory_leaks=show_memory_leaks,
                temporary_allocation_threshold=temporary_allocation_threshold,
                merge_threads=merge_threads,
                inverted=inverted,
                temporal=temporal,
                max_memory_records=max_memory_records,
                no_web=no_web,
            )

        try:
            reporter_factory = cast(
                Callable[..., TransformReporter], self.reporter_factory
            )
            if max_memory_records is None:
                reader = FileReader(os.fspath(result_path), report_progress=True)
            else:
                reader = FileReader(
                    os.fspath(result_path),
                    report_progress=True,
                    max_memory_records=max_memory_records,
                )
            merge_threads = True if merge_threads is None else merge_threads
            inverted = False if inverted is None else inverted

            native_traces = reader.metadata.has_native_traces
            if native_traces:
                warn_if_not_enough_symbols()

            if not temporal and temporary_allocation_threshold < 0:
                warn_if_file_is_not_aggregated_and_is_too_big(reader, result_path)

            memory_records = tuple(reader.get_memory_snapshots())

            use_temporal_fallback = (
                reader.metadata.file_format == FileFormat.ALL_ALLOCATIONS
                and not reader.metadata.has_allocation_timestamps
                and temporary_allocation_threshold < 0
            )

            if use_temporal_fallback:
                if show_memory_leaks:
                    temporal_allocations = reader.get_temporal_allocation_records(
                        merge_threads=merge_threads
                    )
                    reporter = reporter_factory(
                        temporal_allocations,
                        memory_records=memory_records,
                        native_traces=native_traces,
                    )
                else:
                    (
                        temporal_allocations,
                        high_water_mark_by_snapshot,
                    ) = reader.get_temporal_high_water_mark_allocation_records(
                        merge_threads=merge_threads
                    )
                    reporter = reporter_factory(
                        temporal_allocations,
                        memory_records=memory_records,
                        native_traces=native_traces,
                        high_water_mark_by_snapshot=high_water_mark_by_snapshot,
                    )
            else:
                if show_memory_leaks:
                    snapshot_allocations = reader.get_leaked_allocation_records(
                        merge_threads=merge_threads
                    )
                elif temporary_allocation_threshold >= 0:
                    snapshot_allocations = reader.get_temporary_allocation_records(
                        threshold=temporary_allocation_threshold,
                        merge_threads=merge_threads,
                    )
                else:
                    snapshot_allocations = reader.get_high_watermark_allocation_records(
                        merge_threads=merge_threads
                    )
                reporter = reporter_factory(
                    snapshot_allocations,
                    memory_records=memory_records,
                    native_traces=native_traces,
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
                no_web=no_web,
            )
