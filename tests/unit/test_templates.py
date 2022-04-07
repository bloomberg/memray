import pytest

from memray.reporters.templates import get_report_title


@pytest.mark.parametrize(
    ["kind", "show_memory_leaks", "expected"],
    [
        ("flamegraph", False, "flamegraph report"),
        ("flamegraph", True, "flamegraph report (memory leaks)"),
        ("table", False, "table report"),
        ("table", True, "table report (memory leaks)"),
    ],
)
def test_title_for_regular_report(kind, show_memory_leaks, expected):
    assert get_report_title(kind=kind, show_memory_leaks=show_memory_leaks) == expected
