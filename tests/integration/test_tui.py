from memray import AllocatorType
from memray.reporters.tui import TUI
from tests.utils import MockAllocationRecord


def test_pausing():
    tui = TUI(pid=123, cmd_line="python3 some_program.py", native=False)
    snapshot = []

    snapshot.append(
        MockAllocationRecord(
            tid=1,
            address=0x1000000,
            size=1024,
            allocator=AllocatorType.MALLOC,
            stack_id=1,
            n_allocations=1,
            _stack=[
                ("function1", "/src/lel.py", 18),
            ],
        )
    )
    tui.update_snapshot(snapshot)

    # CHECK DEFAULT DATA
    # User hasn't paused, display data should equal live data
    assert tui.display_data.n_samples == 1
    assert tui.display_data.current_memory_size == 1024
    assert tui.live_data.n_samples == 1
    assert tui.live_data.current_memory_size == 1024

    tui.pause()

    snapshot.append(
        MockAllocationRecord(
            tid=1,
            address=0x1000000,
            size=1024,
            allocator=AllocatorType.MALLOC,
            stack_id=1,
            n_allocations=1,
            _stack=[
                ("function1", "/src/lel.py", 18),
            ],
        )
    )
    tui.update_snapshot(snapshot)

    # CHECK DATA AFTER PAUSE ACTION
    # Display data shouldn't include last write, but we should still see latest data
    # in live_data field
    assert tui.display_data.n_samples == 1
    assert tui.display_data.current_memory_size == 1024
    assert tui.live_data.n_samples == 2
    assert tui.live_data.current_memory_size == 2048

    tui.unpause()

    # CHECK DATA AFTER UNPAUSE ACTION
    # Display should be back in sync with live data
    assert tui.display_data.n_samples == 2
    assert tui.display_data.current_memory_size == 2048
    assert tui.live_data.n_samples == 2
    assert tui.live_data.current_memory_size == 2048
