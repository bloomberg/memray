"""
Convert Docutils' documentation from reStructuredText to <format>.
"""

import contextlib
from pathlib import Path

import docutils
from docutils import core
import pyperf
from memray_helper import get_tracker

from docutils.utils.math.math2html import Trace

Trace.show = lambda message, channel: ...  # don't print to console

DOC_ROOT = (Path(__file__).parent / "docutils_data" / "docs").resolve()


def build_html(doc_root):
    elapsed = 0.0
    for file in doc_root.rglob("*.txt"):
        file_contents = file.read_text(encoding="utf-8")
        t0 = pyperf.perf_counter()
        with get_tracker():
            with contextlib.suppress(docutils.ApplicationError):
                core.publish_string(
                    source=file_contents,
                    reader_name="standalone",
                    parser_name="restructuredtext",
                    writer_name="html5",
                    settings_overrides={
                        "input_encoding": "unicode",
                        "output_encoding": "unicode",
                        "report_level": 5,
                    },
                )
        elapsed += pyperf.perf_counter() - t0
    return elapsed


def bench_docutils(loops, doc_root):
    runs_total = 0
    for _ in range(loops):
        runs_total += build_html(doc_root)
    return runs_total


def add_cmdline_args(cmd, args):
    cmd.append("--doc_root=%s" % args.doc_root)


if __name__ == "__main__":
    runner = pyperf.Runner(add_cmdline_args=add_cmdline_args)
    runner.metadata["description"] = "Render documentation with Docutils"
    runner.argparser.add_argument("--doc_root", default=DOC_ROOT)

    args = runner.parse_args()
    runner.bench_time_func("docutils", bench_docutils, Path(args.doc_root))
