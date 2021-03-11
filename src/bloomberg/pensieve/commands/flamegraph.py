import argparse
import sys
from pathlib import Path

from bloomberg.pensieve import Tracker
from bloomberg.pensieve.reporters.flamegraph import FlameGraphReporter


class FlamegraphCommand:
    """Generate an HTML-based flamegraph for peak memory usage."""

    def prepare_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-o",
            "--output",
            help="Output file name",
            default="pensieve-flamegraph.html",
        )
        parser.add_argument("results", help="Results of the tracker run")

    def run(self, args: argparse.Namespace) -> int:
        if not Path(args.results).exists():
            print(f"No such file: {args.results}", file=sys.stderr)
            return 1

        tracker = Tracker(args.results)

        snapshot = tracker.get_high_watermark_allocation_records()
        try:
            reporter = FlameGraphReporter.from_snapshot(snapshot)
        except OSError:
            print(
                f"Failed to parse allocation records in {args.results}",
                file=sys.stderr,
            )
            return 1

        with open(args.output, "w") as f:
            reporter.render(f)

        print(f"Wrote {args.output}")
        return 0
