import argparse
import importlib.util
import shutil
import sys

from rich import print as pprint

from memray._errors import MemrayCommandError

from ..reporters.transform import TransformReporter
from .common import HighWatermarkCommand


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
