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


def test_thread_class_swap_during_tracking_does_not_crash(tmpdir, monkeypatch):
    """Regression test for https://github.com/bloomberg/memray/issues/856.

    ``gevent.monkey.patch_all()`` replaces ``threading.Thread`` with its own
    class while tracking is active. ``Tracker.__exit__`` must clean up the
    instrumentation it installed on the original ``Thread`` class, not the
    one that ``threading.Thread`` happens to point at on exit.
    """
    output = Path(tmpdir) / "test.bin"
    with Tracker(output):

        class FakeThread:
            pass

        monkeypatch.setattr("threading.Thread", FakeThread)


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
