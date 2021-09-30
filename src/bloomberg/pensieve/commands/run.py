import argparse
import os
import runpy
import socket
import sys
import textwrap
from contextlib import closing
from typing import Optional

from bloomberg.pensieve import Destination
from bloomberg.pensieve import FileDestination
from bloomberg.pensieve import SocketDestination
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._errors import PensieveCommandError


def _get_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _run_tracker(
    destination: Destination,
    args: argparse.Namespace,
    post_run_message: Optional[str] = None,
) -> None:
    with Tracker(destination=destination, native_traces=args.native):
        sys.argv[1:] = args.script_args
        try:
            if args.run_as_module:
                runpy.run_module(args.script, run_name="__main__", alter_sys=True)
            else:
                runpy.run_path(args.script, run_name="__main__")
        finally:
            if not args.quiet and post_run_message is not None:
                print(post_run_message)


def _run_with_socket_output(args: argparse.Namespace) -> None:
    port = args.live_port
    if not args.quiet:
        print(f"Run 'pensieve live {port}' in another shell to see live results")
    _run_tracker(destination=SocketDestination(port=port), args=args)


def _run_with_file_output(args: argparse.Namespace) -> None:
    if args.output is None:
        output = f"pensieve-{os.path.basename(args.script)}.{os.getpid()}.bin"
        filename = os.path.join(os.path.dirname(args.script), output)
    else:
        filename = args.output

    if not args.quiet:
        print(f"Writing profile results into {filename}")

    example_report_generation_message = textwrap.dedent(
        f"""
        [pensieve] Successfully generated profile results.

        You can now generate reports from the stored allocation records.
        Some example commands to generate reports:

        {sys.executable} -m bloomberg.pensieve flamegraph {filename}
        """
    ).strip()

    destination = FileDestination(path=filename)
    try:
        _run_tracker(
            destination=destination,
            args=args,
            post_run_message=example_report_generation_message,
        )
    except OSError as error:
        raise PensieveCommandError(str(error), exit_code=1)


class RunCommand:
    """Run the specified application and track memory usage"""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.usage = "%(prog)s [-m module | file] [args]"
        output_group = parser.add_mutually_exclusive_group()
        output_group.add_argument(
            "-o",
            "--output",
            help="Output file name (default: <process_name>.<pid>.bin)",
        )
        output_group.add_argument(
            "--live",
            help="Start live tracking session and wait until a client connects",
            action="store_true",
            dest="live_mode",
            default=False,
        )

        parser.add_argument(
            "--live-port",
            "-p",
            help="Port to use when starting live tracking. (default: random free port)",
            default=_get_free_port(),
            type=int,
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
        if args.live_mode:
            _run_with_socket_output(args)
        else:
            _run_with_file_output(args)
