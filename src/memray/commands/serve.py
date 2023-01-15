import argparse
from pathlib import Path

from memray._errors import MemrayCommandError
from memray.reporters.serve import MemraySever


class ServeCommand:
    """Run a web server to view the results of a tracker run"""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("results", help="Results of the tracker run")

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        result_path = Path(args.results)
        if not result_path.exists() or not result_path.is_file():
            raise MemrayCommandError(f"No such file: {args.results}", exit_code=1)

        server = MemraySever(result_path)
        server.run()
