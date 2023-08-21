import pytest

from memray.reporters.templates import get_report_title


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
