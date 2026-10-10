import argparse
from contextlib import suppress
from typing import Optional

from memray import SocketReader
from memray._errors import MemrayCommandError
from memray.reporters.tui import TUIApp


class LiveCommand:
    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        with suppress(KeyboardInterrupt):
            self.start_live_interface(args.port)

    def start_live_interface(
        self, port: int, cmdline_override: Optional[str] = None
    ) -> None:
        if port >= 2**16 or port <= 0:
            raise MemrayCommandError(f"Invalid port: {port}", exit_code=1)
        with SocketReader(port=port) as reader:
            TUIApp(reader, cmdline_override=cmdline_override).run()
