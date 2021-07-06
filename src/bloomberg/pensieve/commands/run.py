import argparse
import os
import runpy
import sys
import textwrap
from typing import NoReturn

from bloomberg.pensieve import Tracker


class RunCommand:
    """Run the specified application and track memory usage"""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        def custom_error(message: str) -> NoReturn:
            parser.print_usage(sys.stderr)
            parser.exit(1)

        setattr(parser, "error", custom_error)
        parser.usage = "%(prog)s [-m module | file] [args]"
        parser.add_argument(
            "-o",
            "--output",
            help="Output file name (default: <process_name>.<pid>.bin)",
        )
        parser.add_argument(
            "--native",
            help="Track native (C/C++) stack frames as well",
            action="store_true",
            dest="native",
            default=False,
        )
        parser.add_argument(
            "-q",
            "--quiet",
            help="Don't show any tracking-specific output while running",
            action="store_true",
        )
        parser.add_argument(
            "-m",
            help="Run library module as a script (terminates option list)",
            action="store_true",
            dest="run_as_module",
        )
        parser.add_argument("script", help=argparse.SUPPRESS, metavar="file")
        parser.add_argument(
            "script_args",
            help=argparse.SUPPRESS,
            nargs=argparse.REMAINDER,
            metavar="module",
        )

    def run(self, args: argparse.Namespace) -> None:
        if args.output is None:
            filename = f"pensieve-{os.path.basename(args.script)}.{os.getpid()}.bin"
            results_file = os.path.join(os.path.dirname(args.script), filename)
        else:
            results_file = args.output

        if not args.quiet:
            print(f"Writing profile results into {results_file}")

        with Tracker(results_file, native_traces=args.native):
            sys.argv[1:] = args.script_args
            try:
                if args.run_as_module:
                    runpy.run_module(args.script, run_name="__main__", alter_sys=True)
                else:
                    runpy.run_path(args.script, run_name="__main__")
            finally:
                example_report_generation_message = textwrap.dedent(
                    f"""
                    [pensieve] Successfully generated profile results.

                    You can now generate reports from the stored allocation records.
                    Some example commands to generate reports:

                    {sys.executable} -m bloomberg.pensieve flamegraph {results_file}
                    """
                ).strip()
                if not args.quiet:
                    print(example_report_generation_message)
