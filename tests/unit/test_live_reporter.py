import datetime
from io import StringIO
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from rich import print as rprint

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve.commands.live import TUI
from bloomberg.pensieve.commands.live import Location
from bloomberg.pensieve.commands.live import aggregate_allocations
from tests.utils import MockAllocationRecord


class FakeDate(MagicMock):
    @classmethod
    def now(cls):
        return datetime.datetime(2021, 1, 1)


def make_tui(pid=123, cmd="python3 some_program.py"):
    return TUI(pid=pid, cmd_line=cmd)


@patch("bloomberg.pensieve.commands.live.datetime", FakeDate)
class TestTUIHeader:
    @pytest.mark.parametrize(
        "pid, out_str",
        [
            pytest.param(999, 999, id="Valid PID"),
            pytest.param(None, "???", id="Missing PID"),
        ],
    )
    def test_pid(self, pid, out_str):

        # GIVEN
        snapshot = []
        output = StringIO()
        tui = make_tui(pid=pid, cmd="")

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_header(), file=output)

        # THEN
        expected = [
            "Bloomberg pensieve live                                 Fri Jan  1 00:00:00 2021",
            "tracking",
            f"              PID: {out_str}      CMD: ???",
            "(∩｀-´)⊃━☆ﾟ.*…TID: 0x0      Thread 1 of 0",
            "              Samples: 1    Duration: 0.0 seconds",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_command_line(self):
        # GIVEN
        snapshot = []
        output = StringIO()
        tui = make_tui(cmd="python3 some_command_to_test.py")

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_header(), file=output)

        # THEN
        expected = [
            "Bloomberg pensieve live                                 Fri Jan  1 00:00:00 2021",
            "tracking",
            "              PID: 123      CMD: python3 some_command_to_test.py",
            "(∩｀-´)⊃━☆ﾟ.*…TID: 0x0      Thread 1 of 0",
            "              Samples: 1    Duration: 0.0 seconds",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_too_long_command_line_is_trimmed(self):
        # GIVEN
        snapshot = []
        output = StringIO()
        tui = make_tui(cmd="python3 " + "a" * 100)

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_header(), file=output)

        # THEN
        expected = [
            "Bloomberg pensieve live                                 Fri Jan  1 00:00:00 2021",
            "tracking",
            "              PID: 123      CMD: python3",
            "(∩｀-´)⊃━☆ﾟ.*…              aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa...",
            "              TID: 0x0      Thread 1 of 0",
            "              Samples: 1    Duration: 0.0 seconds",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_with_no_allocations(self):

        # GIVEN
        snapshot = []
        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_header(), file=output)

        # THEN
        expected = [
            "Bloomberg pensieve live                                 Fri Jan  1 00:00:00 2021",
            "tracking",
            "              PID: 123      CMD: python3 some_program.py",
            "(∩｀-´)⊃━☆ﾟ.*…TID: 0x0      Thread 1 of 0",
            "              Samples: 1    Duration: 0.0 seconds",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_with_one_allocation(self):
        # GIVEN
        snapshot = [
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
        ]

        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_header(), file=output)

        # THEN
        expected = [
            "Bloomberg pensieve live                                 Fri Jan  1 00:00:00 2021",
            "tracking",
            "              PID: 123      CMD: python3 some_program.py",
            "(∩｀-´)⊃━☆ﾟ.*…TID: 0x1      Thread 1 of 1",
            "              Samples: 1    Duration: 0.0 seconds",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_with_many_allocations_same_thread(self):
        # GIVEN
        snapshot = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * (i + 1),
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    (f"function{i}", "/src/lel.py", 18),
                ],
            )
            for i in range(3)
        ]
        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_header(), file=output)

        # THEN
        expected = [
            "Bloomberg pensieve live                                 Fri Jan  1 00:00:00 2021",
            "tracking",
            "              PID: 123      CMD: python3 some_program.py",
            "(∩｀-´)⊃━☆ﾟ.*…TID: 0x1      Thread 1 of 1",
            "              Samples: 1    Duration: 0.0 seconds",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_with_many_threads_allocation(self):
        # GIVEN
        snapshot = [
            MockAllocationRecord(
                tid=i,
                address=0x1000000,
                size=1024 * (i + 1),
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    (f"function{i}", "/src/lel.py", 18),
                ],
            )
            for i in range(3)
        ]
        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_header(), file=output)

        # THEN
        expected = [
            "Bloomberg pensieve live                                 Fri Jan  1 00:00:00 2021",
            "tracking",
            "              PID: 123      CMD: python3 some_program.py",
            "(∩｀-´)⊃━☆ﾟ.*…TID: 0x0      Thread 1 of 3",
            "              Samples: 1    Duration: 0.0 seconds",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_with_many_threads_and_change_current_thread(self):
        # GIVEN
        snapshot = [
            MockAllocationRecord(
                tid=i,
                address=0x1000000,
                size=1024 * (i + 1),
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    (f"function{i}", "/src/lel.py", 18),
                ],
            )
            for i in range(3)
        ]
        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        tui.next_thread()
        rprint(tui.get_header(), file=output)

        # THEN
        expected = [
            "Bloomberg pensieve live                                 Fri Jan  1 00:00:00 2021",
            "tracking",
            "              PID: 123      CMD: python3 some_program.py",
            "(∩｀-´)⊃━☆ﾟ.*…TID: 0x1      Thread 2 of 3",
            "              Samples: 1    Duration: 0.0 seconds",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_samples(self):
        # GIVEN
        snapshot = [
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
        ]

        output = StringIO()
        tui = make_tui()

        # WHEN
        for _ in range(10):
            tui.update_snapshot(snapshot)
        rprint(tui.get_header(), file=output)

        # THEN
        expected = [
            "Bloomberg pensieve live                                 Fri Jan  1 00:00:00 2021",
            "tracking",
            "              PID: 123       CMD: python3 some_program.py",
            "(∩｀-´)⊃━☆ﾟ.*…TID: 0x1       Thread 1 of 1",
            "              Samples: 10    Duration: 0.0 seconds",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected


class TestTUIHeapBar:
    def test_single_allocation(self):
        # GIVEN
        snapshot = [
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
        ]

        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_heap_size(), file=output)

        # THEN
        expected = [
            "Current heap size: 1.000KB                           Max heap size seen: 1.000KB",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_lowering_value(self):
        # GIVEN
        snapshot1 = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=2048,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("function1", "/src/lel.py", 18),
                ],
            )
        ]

        snapshot2 = [
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
        ]

        output1 = StringIO()
        output2 = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot1)
        rprint(tui.get_heap_size(), file=output1)
        tui.update_snapshot(snapshot2)
        rprint(tui.get_heap_size(), file=output2)

        # THEN
        expected = [
            "Current heap size: 2.000KB                           Max heap size seen: 2.000KB",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸",
        ]
        actual = [line.rstrip() for line in output1.getvalue().splitlines()]
        assert actual == expected

        expected = [
            "Current heap size: 1.000KB                           Max heap size seen: 2.000KB",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸",
        ]
        actual = [line.rstrip() for line in output2.getvalue().splitlines()]
        assert actual == expected

    def test_raising_value(self):
        # GIVEN
        snapshot1 = [
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
        ]

        snapshot2 = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=2048,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("function1", "/src/lel.py", 18),
                ],
            )
        ]

        output1 = StringIO()
        output2 = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot1)
        rprint(tui.get_heap_size(), file=output1)
        tui.update_snapshot(snapshot2)
        rprint(tui.get_heap_size(), file=output2)

        # THEN
        expected = [
            "Current heap size: 1.000KB                           Max heap size seen: 1.000KB",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸",
        ]
        actual = [line.rstrip() for line in output1.getvalue().splitlines()]
        assert actual == expected

        expected = [
            "Current heap size: 2.000KB                           Max heap size seen: 2.000KB",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸",
        ]
        actual = [line.rstrip() for line in output2.getvalue().splitlines()]
        assert actual == expected

    def test_allocations_in_multiple_threads(self):
        # GIVEN
        snapshot = [
            MockAllocationRecord(
                tid=i,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("function1", "/src/lel.py", 18),
                ],
            )
            for i in range(10)
        ]

        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_heap_size(), file=output)

        # THEN
        expected = [
            "Current heap size: 10.000KB                         Max heap size seen: 10.000KB",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected


class TestTUITable:
    def test_no_allocation(self):
        # GIVEN
        snapshot = []

        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ <Total   ┃ Own     ┃ Alloca… ┃",
            "┃                                               ┃ Memory>  ┃ Memory  ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_with_one_allocation(self):
        # GIVEN
        snapshot = [
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
        ]

        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ <Total   ┃ Own     ┃ Alloca… ┃",
            "┃                                               ┃ Memory>  ┃ Memory  ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function1 at /src/lel.py                      │ 1.000KB  │ 1.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_multiple_allocations_same_thread(self):
        # GIVEN
        snapshot = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * (1 + i),
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    (f"function{i}", f"/src/lel_{i}.py", i),
                ],
            )
            for i in range(5)
        ]

        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ <Total   ┃ Own     ┃ Alloca… ┃",
            "┃                                               ┃ Memory>  ┃ Memory  ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function4 at /src/lel_4.py                    │ 5.000KB  │ 5.000KB │ 1       │",
            "│ function3 at /src/lel_3.py                    │ 4.000KB  │ 4.000KB │ 1       │",
            "│ function2 at /src/lel_2.py                    │ 3.000KB  │ 3.000KB │ 1       │",
            "│ function1 at /src/lel_1.py                    │ 2.000KB  │ 2.000KB │ 1       │",
            "│ function0 at /src/lel_0.py                    │ 1.000KB  │ 1.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_multiple_allocations_different_threads(self):
        # GIVEN
        snapshot = [
            MockAllocationRecord(
                tid=i,
                address=0x1000000,
                size=1024 * (1 + i),
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    (f"function{i}", f"/src/lel_{i}.py", i),
                ],
            )
            for i in range(5)
        ]

        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ <Total   ┃ Own     ┃ Alloca… ┃",
            "┃                                               ┃ Memory>  ┃ Memory  ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function0 at /src/lel_0.py                    │ 1.000KB  │ 1.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_multiple_allocations_different_threads_change_thread(self):
        # GIVEN
        snapshot = [
            MockAllocationRecord(
                tid=i,
                address=0x1000000,
                size=1024 * (1 + i),
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    (f"function{i}", f"/src/lel_{i}.py", i),
                ],
            )
            for i in range(5)
        ]

        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        for _ in range(3):
            tui.next_thread()
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ <Total   ┃ Own     ┃ Alloca… ┃",
            "┃                                               ┃ Memory>  ┃ Memory  ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function3 at /src/lel_3.py                    │ 4.000KB  │ 4.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_multiple_allocations_different_n_allocations(self):
        # GIVEN
        snapshot = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * (1 + i),
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=i + 1,
                _stack=[
                    (f"function{i}", f"/src/lel_{i}.py", i),
                ],
            )
            for i in range(5)
        ]

        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        for _ in range(3):
            tui.next_thread()
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ <Total   ┃ Own     ┃ Alloca… ┃",
            "┃                                               ┃ Memory>  ┃ Memory  ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function4 at /src/lel_4.py                    │ 5.000KB  │ 5.000KB │ 5       │",
            "│ function3 at /src/lel_3.py                    │ 4.000KB  │ 4.000KB │ 4       │",
            "│ function2 at /src/lel_2.py                    │ 3.000KB  │ 3.000KB │ 3       │",
            "│ function1 at /src/lel_1.py                    │ 2.000KB  │ 2.000KB │ 2       │",
            "│ function0 at /src/lel_0.py                    │ 1.000KB  │ 1.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_parent_frame_totals(self):
        # GIVEN
        snapshot = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=2,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=20,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("sibling", "fun.py", 16),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
        ]

        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ <Total   ┃ Own     ┃ Alloca… ┃",
            "┃                                               ┃ Memory>  ┃ Memory  ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ parent at fun.py                              │ 30.000B  │ 0.000B  │ 3       │",
            "│ grandparent at fun.py                         │ 30.000B  │ 0.000B  │ 3       │",
            "│ sibling at fun.py                             │ 20.000B  │ 20.000B │ 1       │",
            "│ me at fun.py                                  │ 10.000B  │ 10.000B │ 2       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected


@patch("bloomberg.pensieve.commands.live.datetime", FakeDate)
class TestTUILayout:
    def test_with_multiple_allocations(self):
        # GIVEN
        snapshot = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * (1 + i),
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=i + 1,
                _stack=[
                    (f"function{i}", f"/src/lel_{i}.py", i),
                ],
            )
            for i in range(5)
        ]

        output = StringIO()
        tui = make_tui()

        # WHEN
        tui.update_snapshot(snapshot)
        for _ in range(3):
            tui.next_thread()
        rprint(tui.generate_layout(), file=output)

        # THEN
        expected = [
            "Bloomberg pensieve live                                 Fri Jan  1 00:00:00 2021",
            "tracking",
            "              PID: 123      CMD: python3 some_program.py",
            "(∩｀-´)⊃━☆ﾟ.*…TID: 0x1      Thread 1 of 1",
            "              Samples: 1    Duration: 0.0 seconds",
            "Current heap size: 15.000KB                         Max heap size seen: 15.000KB",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸",
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ <Total   ┃ Own     ┃ Alloca… ┃",
            "┃                                               ┃ Memory>  ┃ Memory  ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function4 at /src/lel_4.py                    │ 5.000KB  │ 5.000KB │ 5       │",
            "│ function3 at /src/lel_3.py                    │ 4.000KB  │ 4.000KB │ 4       │",
            "│ function2 at /src/lel_2.py                    │ 3.000KB  │ 3.000KB │ 3       │",
            "│ function1 at /src/lel_1.py                    │ 2.000KB  │ 2.000KB │ 2       │",
            "│ function0 at /src/lel_0.py                    │ 1.000KB  │ 1.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
            " Q  Quit  ←   Previous Thread  →   Next Thread  T  Sort By Total  O  Sort By Own",
        ]
        actual = [
            line.rstrip() for line in output.getvalue().splitlines() if line.rstrip()
        ]
        assert actual == expected


class TestAggregateResults:
    def test_simple_allocations(self):
        # GIVEN
        allocation_records = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=2,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=20,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("sibling", "fun.py", 16),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
        ]
        # WHEN
        result = aggregate_allocations(allocation_records)

        # THEN
        grandparent = result[Location(function="grandparent", file="fun.py")]
        assert grandparent.own_memory == 0
        assert grandparent.total_memory == 30
        assert grandparent.n_allocations == 3

        me = result[Location(function="me", file="fun.py")]
        assert me.own_memory == 10
        assert me.total_memory == 10
        assert me.n_allocations == 2

        parent = result[Location(function="parent", file="fun.py")]
        assert parent.own_memory == 0
        assert parent.total_memory == 30
        assert parent.n_allocations == 3

    def test_missing_frames(self):
        # GIVEN
        allocation_records = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=2,
                _stack=[],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=20,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("sibling", "fun.py", 16),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=30,
                allocator=AllocatorType.MALLOC,
                stack_id=2,
                n_allocations=1,
                _stack=[],
            ),
        ]
        # WHEN
        result = aggregate_allocations(allocation_records)

        # THEN
        grandparent = result[Location(function="grandparent", file="fun.py")]
        assert grandparent.own_memory == 0
        assert grandparent.total_memory == 20
        assert grandparent.n_allocations == 1

        me = result[Location(function="???", file="???")]
        assert me.own_memory == 40
        assert me.total_memory == 40
        assert me.n_allocations == 3
