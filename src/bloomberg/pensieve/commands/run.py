import argparse
import os
import runpy
import sys

from bloomberg.pensieve import Tracker


class RunCommand:
    """"Run the specified application and track memory usage"""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-o",
            "--output",
            help="Output file name (default: <process_name>.<pid>.out)",
        )
        parser.add_argument("command", help="Command to run", nargs=argparse.REMAINDER)

    def main(self, args: argparse.Namespace) -> int:
        results_file = (
            args.output
            if args.output is not None
            else f"{args.command[0]}.{os.getpid()}.out"
        )
        print(f"Writing profile results into {results_file}")
        with Tracker(results_file):
            sys.argv = args.command
            runpy.run_module(args.command[0], run_name="__main__")

        return 0
