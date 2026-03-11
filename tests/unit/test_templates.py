from datetime import datetime

import pytest

from memray import Metadata
from memray._memray import FileFormat
from memray.reporters.templates import get_report_title
from memray.reporters.templates import render_report


@pytest.mark.parametrize(
    ["kind", "show_memory_leaks", "inverted", "expected"],
    [
        ("flamegraph", False, False, "flamegraph report"),
        ("flamegraph", True, False, "flamegraph report (memory leaks)"),
        ("table", False, False, "table report"),
        ("table", True, False, "table report (memory leaks)"),
        ("flamegraph", False, True, "inverted flamegraph report"),
        ("flamegraph", True, True, "inverted flamegraph report (memory leaks)"),
    ],
)
def test_title_for_regular_report(kind, show_memory_leaks, inverted, expected):
    assert (
        get_report_title(
            kind=kind, show_memory_leaks=show_memory_leaks, inverted=inverted
        )
        == expected
    )


@pytest.mark.parametrize(
    "kind",
    ["flamegraph", "table"],
)
def test_html_report_escaping(kind):
    """Test that command line arguments are properly escaped."""
    # GIVEN
    metadata = Metadata(
        start_time=datetime(2024, 1, 1, 0, 0, 0),
        end_time=datetime(2024, 1, 1, 0, 1, 0),
        total_allocations=100,
        total_frames=10,
        peak_memory=1024,
        command_line="python test.py </code>",
        pid=12345,
        main_thread_id=1,
        python_allocator="pymalloc",
        has_native_traces=False,
        trace_python_allocators=False,
        file_format=FileFormat.ALL_ALLOCATIONS,
    )

    # WHEN
    html_output = render_report(
        kind=kind,
        data=[],
        metadata=metadata,
        memory_records=[],
        show_memory_leaks=False,
        merge_threads=False,
        inverted=False,
        no_web=True,
    )

    # THEN
    assert html_output.count("<code>") == html_output.count("</code>")
    assert "python test.py &lt;/code&gt;" in html_output
