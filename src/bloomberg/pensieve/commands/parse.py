import argparse
import os

from bloomberg.pensieve import FileReader
from bloomberg.pensieve._errors import PensieveCommandError


class ParseCommand:
    """Debug a results file by parsing and printing each record in it."""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("results", help="Results of the tracker run")

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        if os.isatty(1):
            raise PensieveCommandError(
                "You must redirect stdout to a file or shell pipeline.",
                exit_code=1,
            )

        try:
            FileReader(args.results).dump_all_records()
        except OSError as e:
            raise PensieveCommandError(
                f"Failed to parse allocation records in {args.results}\nReason: {e}",
                exit_code=1,
            )
