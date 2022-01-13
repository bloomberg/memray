import argparse
import contextlib
import os
import runpy
import socket
import subprocess
import sys
import textwrap
from contextlib import closing
from contextlib import suppress
from typing import List
from typing import Optional

from bloomberg.pensieve import Destination
from bloomberg.pensieve import FileDestination
from bloomberg.pensieve import SocketDestination
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._errors import PensieveCommandError
from bloomberg.pensieve.commands.live import LiveCommand


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
    sys.argv = [args.script, *args.script_args]
    if args.run_as_module:
        sys.argv.insert(0, "-m")
    try:
        tracker = Tracker(destination=destination, native_traces=args.native)
    except OSError as error:
        raise PensieveCommandError(str(error), exit_code=1)

    with tracker:
        sys.argv[1:] = args.script_args
        try:
            if args.run_as_module:
                runpy.run_module(args.script, run_name="__main__", alter_sys=True)
            else:
                runpy.run_path(args.script, run_name="__main__")
        finally:
            if not args.quiet and post_run_message is not None:
                print(post_run_message)


def _child_process(
    port: int,
    native: bool,
    run_as_module: bool,
    quiet: bool,
    script: str,
    script_args: List[str],
) -> None:
    args = argparse.Namespace(
        native=native,
        run_as_module=run_as_module,
        quiet=quiet,
        script=script,
        script_args=script_args,
    )
    _run_tracker(destination=SocketDestination(port=port), args=args)


def _run_child_process_and_attach(args: argparse.Namespace) -> None:
    port = args.live_port
    if port is None:
        port = _get_free_port()
    if not 2 ** 16 > port > 0:
        raise PensieveCommandError(f"Invalid port: {port}", exit_code=1)

    arguments = (
        f"{port},{args.native},{args.run_as_module},{args.quiet},"
        f'"{args.script}",{args.script_args}'
    )
    tracked_app_cmd = [
        sys.executable,
        "-c",
        f"from bloomberg.pensieve.commands.run import _child_process;"
        f"_child_process({arguments})",
    ]
    with contextlib.suppress(KeyboardInterrupt):
        with subprocess.Popen(
            tracked_app_cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True,
        ) as process:
            try:
                LiveCommand().start_live_interface(port)
            except (Exception, KeyboardInterrupt) as error:
                process.terminate()
                raise error from None
            process.terminate()
            if process.returncode:
                if process.stderr:
                    print(process.stderr.read(), file=sys.stderr)
                raise (PensieveCommandError(exit_code=process.returncode))


def _run_with_socket_output(args: argparse.Namespace) -> None:
    port = args.live_port
    if port is None:
        port = _get_free_port()
    if not 2 ** 16 > port > 0:
        raise PensieveCommandError(f"Invalid port: {port}", exit_code=1)

    if not args.quiet:
        pensieve_cli = f"pensieve{sys.version_info.major}.{sys.version_info.minor}"
        print(f"Run '{pensieve_cli} live {port}' in another shell to see live results")
    with suppress(KeyboardInterrupt):
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

    destination = FileDestination(path=filename, exist_ok=args.force)
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
            help="Start a live tracking session and inmediately connect a live server",
            action="store_true",
            dest="live_mode",
            default=False,
        )
        output_group.add_argument(
            "--live-remote",
            help="Start a live tracking session and wait until a client connects",
            action="store_true",
            dest="live_remote_mode",
            default=False,
        )
        parser.add_argument(
            "--live-port",
            "-p",
            help="Port to use when starting live tracking (default: random free port)",
            default=None,
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
            "-f",
            "--force",
            help="If the output file already exists, overwrite it",
            action="store_true",
            default=False,
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

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        if args.live_port is not None and not args.live_remote_mode:
            raise parser.error("The --live-port argument requires --live-remote")

        if args.live_mode:
            _run_child_process_and_attach(args)
        elif args.live_remote_mode:
            _run_with_socket_output(args)
        else:
            _run_with_file_output(args)
