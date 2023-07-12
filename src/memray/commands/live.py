import argparse
import sys
import termios
from contextlib import suppress

from rich.layout import Layout
from rich.live import Live

from memray import SocketReader
from memray._errors import MemrayCommandError
from memray.reporters.tui import TUI

KEYS = {
    "ESC": "\x1b",
    "CTRL_C": "\x03",
    "LEFT": "\x1b\x5b\x44",
    "RIGHT": "\x1b\x5b\x43",
    "O": "o",
    "T": "t",
    "A": "a",
    "P": "p",
    "U": "u",
}


def _readchar() -> str:  # pragma: no cover
    """Read a single character from standard input without echoing.

    This function configures the current terminal and its standard
    input to:

        * Deactivate character echoing
        * Deactivate canonical mode (see 'termios' man page).

    Then, it reads a single character from standard input.

    After the character has been read, it restores the previous configuration.
    """
    if not sys.stdin.isatty():
        return sys.stdin.read(1)
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    new_settings = termios.tcgetattr(fd)
    new_settings[3] = new_settings[3] & ~termios.ECHO & ~termios.ICANON
    termios.tcsetattr(fd, termios.TCSANOW, new_settings)
    try:
        char = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return char


def readkey() -> str:  # pragma: no cover
    """Read a key press respecting ANSI Escape sequences.

    A key-stroke can have:

        1 character for normal keys: 'a', 'z', '9'...
        2 characters for combinations with ALT: ALT+A, ...
        3 characters for cursors: ->, <-, ...
        4 characters for combinations with CTRL and ALT: CTRL+ALT+SUPR
    """
    c1 = _readchar()
    if not c1 or ord(c1) != 0x1B:  # ESC
        return c1
    c2 = _readchar()
    if ord(c2) != 0x5B:  # [
        return c1 + c2
    c3 = _readchar()
    if ord(c3) != 0x33:  # 3 (one more char is needed)
        return c1 + c2 + c3
    c4 = _readchar()
    return c1 + c2 + c3 + c4


class LiveCommand:
    """Remotely monitor allocations in a text-based interface"""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "port",
            help="Remote port to connect to",
            default=None,
            type=int,
        )

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        with suppress(KeyboardInterrupt):
            self.start_live_interface(args.port)

    def start_live_interface(self, port: int) -> None:
        if port >= 2**16 or port <= 0:
            raise MemrayCommandError(f"Invalid port: {port}", exit_code=1)
        with SocketReader(port=port) as reader:
            tui = TUI(reader.pid, reader.command_line, reader.has_native_traces)

            def _get_renderable() -> Layout:
                if tui.active:
                    snapshot = list(reader.get_current_snapshot(merge_threads=False))
                    tui.update_snapshot(snapshot)

                if not reader.is_active:
                    tui.active = False
                    tui.message = "[red]Remote has disconnected[/]"

                return tui.generate_layout()

            with Live(get_renderable=_get_renderable, screen=True):
                while True:
                    char = readkey()
                    if char == KEYS["LEFT"]:
                        tui.previous_thread()
                    elif char == KEYS["RIGHT"]:
                        tui.next_thread()
                    elif char in {"q", KEYS["ESC"]}:
                        break
                    elif char == KEYS["P"]:
                        tui.pause()
                    elif char == KEYS["U"]:
                        tui.unpause()
                    elif char.lower() in TUI.KEY_TO_COLUMN_ID.keys():
                        col_number = tui.KEY_TO_COLUMN_ID[char.lower()]
                        tui.update_sort_key(col_number)
                    elif char == KEYS["CTRL_C"]:
                        raise KeyboardInterrupt()
