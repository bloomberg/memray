import argparse
import os
import runpy
import sys
from typing import NoReturn

from bloomberg.pensieve import Tracker


class RunCommand:
    """"Run the specified application and track memory usage"""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        def custom_error(message: str) -> NoReturn:
            parser.print_usage(sys.stderr)
            parser.exit(1)

        setattr(parser, "error", custom_error)
        parser.usage = "%(prog)s [-m module | file] [args]"
        parser.add_argument(
            "-o",
            "--output",
            help="Output file name (default: <process_name>.<pid>.out)",
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

    def main(self, args: argparse.Namespace) -> int:
        results_file = (
            args.output
            if args.output is not None
            else f"{args.script}.{os.getpid()}.out"
        )

        print(f"Writing profile results into {results_file}")
        with Tracker(results_file):
            sys.argv[1:] = args.script_args
            if args.run_as_module:
                runpy.run_module(args.script, run_name="__main__", alter_sys=True)
            else:
                runpy.run_path(args.script, run_name="__main__")

        return 0
