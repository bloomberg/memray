from __future__ import annotations

import argparse
import contextlib
import os
import pathlib
import platform
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading

import memray
from memray._errors import MemrayCommandError

from .live import LiveCommand
from .run import _get_free_port

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal  # type: ignore

TrackingMode = Literal["ACTIVATE", "DEACTIVATE", "FOR_DURATION"]


GDB_SCRIPT = pathlib.Path(__file__).parent / "_attach.gdb"
LLDB_SCRIPT = pathlib.Path(__file__).parent / "_attach.lldb"
RTLD_DEFAULT = memray._memray.RTLD_DEFAULT
RTLD_NOW = memray._memray.RTLD_NOW
PAYLOAD = """
import atexit
import time
import threading
import resource
import sys
from contextlib import suppress

import memray


class BareExceptionMessage(Exception):
    def __repr__(self):
        return self.args[0]


class RepeatingTimer(threading.Thread):
    def __init__(self, interval, function):
        self._interval = interval
        self._function = function
        self._canceled = threading.Event()
        super().__init__()

    def cancel(self):
        self._canceled.set()

    def run(self):
        while not self._canceled.wait(self._interval):
            if self._function():
                break


def deactivate_last_tracker():
    tracker = getattr(memray, "_last_tracker", None)
    if not tracker:
        return

    memray._last_tracker = None
    try:
        tracker.__exit__(None, None, None)
    finally:
        # Clean up resources associated with the Tracker ASAP,
        # even if an exception was raised.
        del tracker

    # Stop any waiting threads. This attribute may be unset if an old Memray
    # version attached 1st, setting last_tracker but not _attach_event_threads.
    # It could also be unset if we're racing another deactivate call.
    for thread in memray.__dict__.pop("_attach_event_threads", []):
        thread.cancel()


def activate_tracker():
    deactivate_last_tracker()
    tracker = {tracker_call}
    try:
        tracker.__enter__()
        memray._last_tracker = tracker
    finally:
        # Clean up resources associated with the Tracker ASAP,
        # even if an exception was raised.
        del tracker
    memray._attach_event_threads = []


def track_for_duration(duration=5):
    activate_tracker()

    def deactivate_because_timer_elapsed():
        print(
            "memray: Deactivating tracking:",
            duration,
            "seconds have elapsed",
            file=sys.stderr,
        )
        deactivate_last_tracker()

    thread = threading.Timer(duration, deactivate_because_timer_elapsed)
    thread.start()
    memray._attach_event_threads.append(thread)


if not hasattr(memray, "_last_tracker"):
    # This only needs to be registered the first time we attach.
    atexit.register(deactivate_last_tracker)

if {mode!r} == "ACTIVATE":
    activate_tracker()
elif {mode!r} == "DEACTIVATE":
    if not getattr(memray, "_last_tracker", None):
        raise BareExceptionMessage("no previous `memray attach` call detected")
    deactivate_last_tracker()
elif {mode!r} == "FOR_DURATION":
    track_for_duration({duration})
"""


def inject(debugger: str, pid: int, port: int, verbose: bool) -> str | None:
    """Executes a file in a running Python process."""
    injecter = pathlib.Path(memray.__file__).parent / "_inject.abi3.so"
    assert injecter.exists()

    gdb_cmd = [
        "gdb",
        "-batch",
        "-p",
        str(pid),
        "-nx",
        "-nw",
        "-iex=set auto-solib-add off",
        f"-ex=set $rtld_now={RTLD_NOW}",
        f'-ex=set $libpath="{injecter}"',
        f"-ex=set $port={port}",
        f"-x={GDB_SCRIPT}",
    ]

    lldb_cmd = [
        "lldb",
        "--batch",
        "-p",
        str(pid),
        "--no-lldbinit",
        "-o",
        f'expr char $libpath[]="{injecter}"',
        "-o",
        f"expr int $port={port}",
        "-o",
        f"expr void* $rtld_default=(void*){RTLD_DEFAULT}",
        "-o",
        f"expr int $rtld_now={RTLD_NOW}",
        "--source",
        f"{LLDB_SCRIPT}",
    ]

    cmd = gdb_cmd if debugger == "gdb" else lldb_cmd
    if verbose:
        if sys.version_info >= (3, 8):
            print("Debugger command line:", shlex.join(cmd))
        else:
            print("Debugger command line:", cmd)

    try:
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        returncode = 0
    except subprocess.CalledProcessError as exc:
        output = exc.output
        returncode = exc.returncode

    if cmd is lldb_cmd:
        # A bug in lldb sometimes means processes stay stopped after it exits.
        # Send a signal to wake the process up. Ignore any errors: the process
        # may have died, or may have never existed, or may be owned by another
        # user, etc. Processes that aren't stopped will ignore this signal, so
        # this should be harmless, though it is a huge hack.
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGCONT)

    if verbose:
        print(f"debugger return code: {returncode}")
        print(f"debugger output:\n{output}")

    command_output_lines = (
        line for line in output.splitlines() if not line.startswith(f"({debugger})")
    )
    if returncode == 0 and any(' "SUCCESS"' in line for line in command_output_lines):
        return None

    # An error occurred. Give the best message we can. This is hacky; we don't
    # have a good option besides parsing output from the debugger session.
    if "--help" in output:
        return (
            "The debugger failed to parse our command line arguments.\n"
            "Run with --verbose to see the error message."
        )

    if "error: attach failed: " in output or "ptrace: " in output:
        # We failed to attach to the given pid. A few likely reasons...
        errmsg = "Failed to attach a debugger to the process.\n"
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return errmsg + "The given process ID does not exist."
        except PermissionError:
            return errmsg + "The given process ID is owned by a different user."

        return errmsg + "You most likely do not have permission to trace the process."

    if "MEMRAY: Attached to process." not in output:
        return (
            f"Failed to execute our {debugger} script.\n"
            "Run with --verbose to debug the failure."
        )

    if "MEMRAY: Checking if process is Python 3.7+." in output:
        if "MEMRAY: Process is Python 3.7+." not in output:
            return "The process does not seem to be running Python 3.7 or newer."

    return "An unexpected error occurred. Run with --verbose to debug the failure."


def _gdb_available(verbose: bool) -> bool:
    if not shutil.which("gdb"):
        if verbose:
            print("No gdb executable found")
        return False
    return True


def _lldb_available(verbose: int) -> bool:
    # We need a version of lldb that supports `--batch`. This should be lldb
    # 3.5.2 or newer, but the version string format doesn't appear consistent
    # between macOS and Linux, so it's safer to just check the help output to
    # make sure that option is documented.
    try:
        help_str = subprocess.check_output(
            ["lldb", "--help"],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except FileNotFoundError:
        if verbose:
            print("No lldb executable found")
        return False
    except subprocess.CalledProcessError as exc:
        if verbose:
            print(f"`lldb --version` failed: {exc.output}")
        return False

    if "--batch" not in help_str:
        if verbose:
            print("lldb does not support --batch, which we require")
        return False

    return True


def debugger_available(debugger: str, verbose: bool = False) -> bool:
    return {"gdb": _gdb_available, "lldb": _lldb_available}[debugger](verbose=verbose)


def recvall(sock: socket.socket) -> str:
    return b"".join(iter(lambda: sock.recv(4096), b"")).decode("utf-8")


class ErrorReaderThread(threading.Thread):
    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        super().__init__()

    def run(self) -> None:
        try:
            err = recvall(self._sock)
        except OSError as e:
            err = f"Unexpected exception: {e!r}"

        if not err:
            self.error = None
            return

        self.error = err
        os.kill(os.getpid(), signal.SIGINT)


class _DebuggerCommand:
    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--method",
            help="Method to use for injecting commands into the remote process",
            type=str,
            default="auto",
            choices=["auto", "gdb", "lldb"],
        )

        parser.add_argument(
            "-v",
            "--verbose",
            help="Print verbose debugging information.",
            action="store_true",
        )

        parser.add_argument(
            "pid",
            help="Process id to affect",
            type=int,
        )

    def resolve_debugger(self, method: str, *, verbose: bool = False) -> str:
        if method == "auto":
            # Prefer gdb on Linux but lldb on macOS
            if platform.system() == "Linux":
                debuggers = ("gdb", "lldb")
            else:
                debuggers = ("lldb", "gdb")

            for debugger in debuggers:
                if debugger_available(debugger, verbose=verbose):
                    return debugger
            raise MemrayCommandError(
                "Cannot find a supported lldb or gdb executable.",
                exit_code=1,
            )
        elif not debugger_available(method, verbose=verbose):
            raise MemrayCommandError(
                f"Cannot find a supported {method} executable.",
                exit_code=1,
            )
        return method

    def inject_control_channel(
        self, method: str, pid: int, *, verbose: bool = False
    ) -> socket.socket:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with contextlib.closing(server):
            server.bind(("localhost", 0))
            server.listen(1)
            sidechannel_port = server.getsockname()[1]

            errmsg = inject(method, pid, sidechannel_port, verbose=verbose)
            if errmsg:
                raise MemrayCommandError(errmsg, exit_code=1)

            return server.accept()[0]


class AttachCommand(_DebuggerCommand):
    """Begin tracking allocations in an already-started process"""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-o",
            "--output",
            metavar="FILE",
            help=(
                "Capture allocations into the given file"
                " instead of starting a live tracking session"
            ),
        )
        parser.add_argument(
            "-f",
            "--force",
            help="If the output file already exists, overwrite it",
            action="store_true",
            default=False,
        )

        parser.add_argument(
            "--aggregate",
            help="Write aggregated stats to the output file instead of all allocations",
            action="store_true",
            default=False,
        )

        parser.add_argument(
            "--native",
            help="Track native (C/C++) stack frames as well",
            action="store_true",
            dest="native",
            default=False,
        )
        parser.add_argument(
            "--follow-fork",
            action="store_true",
            help="Record allocations in child processes forked from the tracked script",
            default=False,
        )
        parser.add_argument(
            "--trace-python-allocators",
            action="store_true",
            help="Record allocations made by the pymalloc allocator",
            default=False,
        )
        compression = parser.add_mutually_exclusive_group()
        compression.add_argument(
            "--compress-on-exit",
            help="Compress the resulting file using lz4 after tracking completes",
            default=True,
            action="store_true",
        )
        compression.add_argument(
            "--no-compress",
            help="Do not compress the resulting file using lz4",
            default=False,
            action="store_true",
        )

        parser.add_argument(
            "--duration", type=int, help="Duration to track for (in seconds)"
        )

        super().prepare_parser(parser)

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        verbose = args.verbose
        mode: TrackingMode = "ACTIVATE"
        duration = None

        if args.duration:
            mode = "FOR_DURATION"
            duration = args.duration

        args.method = self.resolve_debugger(args.method, verbose=verbose)

        destination: memray.Destination
        if args.output:
            live_port = None
            destination = memray.FileDestination(
                path=os.path.abspath(args.output),
                overwrite=args.force,
                compress_on_exit=not args.no_compress,
            )
        else:
            live_port = _get_free_port()
            destination = memray.SocketDestination(server_port=live_port)

        if args.aggregate and not args.output:
            parser.error("Can't use aggregated mode without an output file.")

        file_format = (
            "file_format=memray.FileFormat.AGGREGATED_ALLOCATIONS"
            if args.aggregate
            else ""
        )

        tracker_call = (
            f"memray.Tracker(destination=memray.{destination!r},"
            f" native_traces={args.native},"
            f" follow_fork={args.follow_fork},"
            f" trace_python_allocators={args.trace_python_allocators},"
            f"{file_format})"
        )

        client = self.inject_control_channel(args.method, args.pid, verbose=verbose)
        client.sendall(
            PAYLOAD.format(
                tracker_call=tracker_call,
                mode=mode,
                duration=duration,
            ).encode("utf-8")
        )
        client.shutdown(socket.SHUT_WR)

        if not live_port:
            err = recvall(client)
            if err:
                raise MemrayCommandError(
                    f"Failed to start tracking in remote process: {err}",
                    exit_code=1,
                )
            return

        # If an error prevents the tracked process from binding a server to
        # live_port, the TUI will hang forever trying to connect. Handle this
        # by spawning a background thread that watches for an error report over
        # the side channel and raises a SIGINT to interrupt the TUI if it sees
        # one. This can race, though: in some cases the TUI will also see an
        # error (if no header is sent over the socket), and the background
        # thread may raise a SIGINT that we see only after the live TUI has
        # already exited. If so we must ignore the extra KeyboardInterrupt.
        error_reader = ErrorReaderThread(client)
        error_reader.start()
        live = LiveCommand()

        with contextlib.suppress(KeyboardInterrupt):
            try:
                try:
                    live.start_live_interface(live_port)
                finally:
                    # Note: may get a spurious KeyboardInterrupt!
                    error_reader.join()
            except (Exception, KeyboardInterrupt):
                remote_err = error_reader.error
                if not remote_err:
                    raise  # Propagate the exception

                raise MemrayCommandError(
                    f"Failed to start tracking in remote process: {remote_err}",
                    exit_code=1,
                ) from None


class DetachCommand(_DebuggerCommand):
    """End the tracking started by a previous ``memray attach`` call"""

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        verbose = args.verbose
        mode: TrackingMode = "DEACTIVATE"
        args.method = self.resolve_debugger(args.method, verbose=verbose)
        client = self.inject_control_channel(args.method, args.pid, verbose=verbose)

        client.sendall(
            PAYLOAD.format(
                tracker_call=None,
                mode=mode,
                duration=None,
            ).encode("utf-8")
        )
        client.shutdown(socket.SHUT_WR)

        err = recvall(client)
        if err:
            raise MemrayCommandError(
                f"Failed to stop tracking in remote process: {err}",
                exit_code=1,
            )
