import argparse
import os
from pathlib import Path
from typing import Optional

from memray._errors import MemrayCommandError
from memray._memray import compute_statistics
from memray.reporters.stats import StatsReporter


class StatsCommand:
    """Generate high level stats of the memory usage in the terminal"""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("results", help="Results of the tracker run")

        def valid_positive_int(value: str) -> int:
            try:
                ivalue = int(value)
                if ivalue <= 0:
                    raise ValueError
            except ValueError:
                raise argparse.ArgumentTypeError(
                    f"{value} is an invalid positive int value"
                )

            return ivalue

        parser.add_argument(
            "-n",
            "--num-largest",
            help="Displays the top 'n' largest allocating functions. Default is 5",
            type=valid_positive_int,
            default=5,
        )

        parser.add_argument(
            "--json",
            help="Exports stats to a JSON file",
            action="store_true",
            default=False,
        )
        parser.add_argument(
            "-o",
            "--output",
            help="Output file name for JSON output",
            default=None,
        )
        parser.add_argument(
            "-f",
            "--force",
            help="If the JSON output file already exists, overwrite it",
            action="store_true",
            default=False,
        )

    def run(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        result_path = Path(args.results)
        if not result_path.exists() or not result_path.is_file():
            raise MemrayCommandError(f"No such file: {args.results}", exit_code=1)
        try:
            stats = compute_statistics(
                os.fspath(args.results),
                report_progress=True,
                num_largest=args.num_largest,
            )
        except OSError as e:
            raise MemrayCommandError(
                f"Failed to compute statistics for {result_path}\nReason: {e}",
                exit_code=1,
            )

        json_output_file: Optional[Path] = None
        if args.json:
            if args.output:
                json_output_file = Path(args.output)
            else:
                filename = str(result_path.name) + ".json"
                if filename.startswith("memray-"):
                    filename = filename[len("memray-") :]
                filename = "memray-stats-" + filename
                json_output_file = result_path.with_name(filename)

            if not args.force and json_output_file.exists():
                raise MemrayCommandError(
                    f"File already exists, will not overwrite: {json_output_file}",
                    exit_code=1,
                )

        reporter = StatsReporter(stats, args.num_largest)
        reporter.render(json_output_file=json_output_file)
        if json_output_file is not None:
            print(f"Wrote {json_output_file}")
