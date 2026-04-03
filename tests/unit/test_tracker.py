from pathlib import Path

import pytest

from memray import Tracker
from memray._test import rss_from_proc_status
from tests.utils import skip_if_macos


def test_two_trackers_cannot_be_active_at_the_same_time(tmpdir):
    # GIVEN
    output = Path(tmpdir) / "test.bin"
    output2 = Path(tmpdir) / "test2.bin"

    # WHEN
    with Tracker(output):
        # THEN
        with pytest.raises(RuntimeError):
            with Tracker(output2):
                pass


def test_the_same_tracker_cannot_be_activated_twice(tmpdir):
    # GIVEN
    output = Path(tmpdir) / "test.bin"

    # WHEN
    tracker = Tracker(output)
    with tracker:
        # Remove the file so we are not stopped by the file existence check
        output.unlink()
        # THEN
        with pytest.raises(RuntimeError):
            with tracker:
                pass


@skip_if_macos
def test_rss_from_proc_status_includes_hugetlb_pages():
    assert (
        rss_from_proc_status(
            "\n".join(
                (
                    "Name:\tpython",
                    "VmRSS:\t  128 kB",
                    "HugetlbPages:\t64 kB",
                )
            )
            + "\n"
        )
        == (128 + 64) * 1024
    )
