from pathlib import Path

import pytest

from memray import Tracker


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
