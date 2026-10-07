import argparse
import os
from pathlib import Path
from typing import Optional

from memray._errors import MemrayCommandError
from memray._memray import compute_statistics
from memray.reporters.stats import StatsReporter


class StatsCommand:
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
                    f"File already exists, will not overwrite without --force:"
                    f" {json_output_file}",
                    exit_code=1,
                )

        reporter = StatsReporter(stats, args.num_largest)
        reporter.render(json_output_file=json_output_file)
        if json_output_file is not None:
            print(f"Wrote {json_output_file}")
