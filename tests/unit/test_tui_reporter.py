import datetime
from io import StringIO
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from rich import print as rprint

from memray import AllocatorType
from memray.reporters.tui import TUI
from memray.reporters.tui import Location
from memray.reporters.tui import MemoryGraph
from memray.reporters.tui import aggregate_allocations
from tests.utils import MockAllocationRecord


class FakeDate(MagicMock):
    @classmethod
    def now(cls):
        return datetime.datetime(2021, 1, 1)


def make_tui(pid=123, cmd="python3 some_program.py", native=False):
    return TUI(pid=pid, cmd_line=cmd, native=native)


@patch("memray.reporters.tui.datetime", FakeDate)
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
            "Memray live tracking                                    Fri Jan  1 00:00:00 "
            "2021",
            "                                               ╭─ Memory ─╮",
            f"(∩｀-´)⊃━☆ﾟ.*…PID: {out_str}      CMD: ???           │          │",
            "              TID: 0x0      Thread 1 of 1      │          │",
            "              Samples: 1    Duration: 0.0      │          │",
            "                            seconds            │          │",
            "                                               ╰──────────╯",
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
            "Memray live tracking                                    Fri Jan  1 00:00:00 "
            "2021",
            "                                               ╭─ Memory ─╮",
            "(∩｀-´)⊃━☆ﾟ.*…PID: 123      CMD: python3       │          │",
            "                            some_command_to_te…│          │",
            "              TID: 0x0      Thread 1 of 1      │          │",
            "              Samples: 1    Duration: 0.0      │          │",
            "                            seconds            ╰──────────╯",
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
            "Memray live tracking                                    Fri Jan  1 00:00:00 "
            "2021",
            "                                               ╭─ Memory ─╮",
            "(∩｀-´)⊃━☆ﾟ.*…PID: 123      CMD: python3       │          │",
            "                            aaaaaaaaaaaaaaaaaa…│          │",
            "              TID: 0x0      Thread 1 of 1      │          │",
            "              Samples: 1    Duration: 0.0      │          │",
            "                            seconds            ╰──────────╯",
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
            "Memray live tracking                                    Fri Jan  1 00:00:00 "
            "2021",
            "                                               ╭─ Memory ─╮",
            "(∩｀-´)⊃━☆ﾟ.*…PID: 123      CMD: python3       │          │",
            "                            some_program.py    │          │",
            "              TID: 0x0      Thread 1 of 1      │          │",
            "              Samples: 1    Duration: 0.0      │          │",
            "                            seconds            ╰──────────╯",
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
            "Memray live tracking                                    Fri Jan  1 00:00:00 "
            "2021",
            "                                               ╭─ Memory ──────────────────────╮",
            "(∩｀-´)⊃━☆ﾟ.*…PID: 123      CMD: python3       │                             … │",
            "                            some_program.py    │                             … │",
            "              TID: 0x1      Thread 1 of 1      │                             … │",
            "              Samples: 1    Duration: 0.0      │                             … │",
            "                            seconds            ╰───────────────────────────────╯",
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
            "Memray live tracking                                    Fri Jan  1 00:00:00 "
            "2021",
            "                                               ╭─ Memory ──────────────────────╮",
            "(∩｀-´)⊃━☆ﾟ.*…PID: 123      CMD: python3       │                             … │",
            "                            some_program.py    │                             … │",
            "              TID: 0x1      Thread 1 of 1      │                             … │",
            "              Samples: 1    Duration: 0.0      │                             … │",
            "                            seconds            ╰───────────────────────────────╯",
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
            "Memray live tracking                                    Fri Jan  1 00:00:00 "
            "2021",
            "                                               ╭─ Memory ──────────────────────╮",
            "(∩｀-´)⊃━☆ﾟ.*…PID: 123      CMD: python3       │                             … │",
            "                            some_program.py    │                             … │",
            "              TID: 0x0      Thread 1 of 3      │                             … │",
            "              Samples: 1    Duration: 0.0      │                             … │",
            "                            seconds            ╰───────────────────────────────╯",
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
            "Memray live tracking                                    Fri Jan  1 00:00:00 "
            "2021",
            "                                               ╭─ Memory ──────────────────────╮",
            "(∩｀-´)⊃━☆ﾟ.*…PID: 123      CMD: python3       │                             … │",
            "                            some_program.py    │                             … │",
            "              TID: 0x1      Thread 2 of 3      │                             … │",
            "              Samples: 1    Duration: 0.0      │                             … │",
            "                            seconds            ╰───────────────────────────────╯",
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
            "Memray live tracking                                    Fri Jan  1 00:00:00 "
            "2021",
            "                                               ╭─ Memory ──────────────────────╮",
            "(∩｀-´)⊃━☆ﾟ.*…PID: 123       CMD: python3      │                             … │",
            "                             some_program.py   │                             … │",
            "              TID: 0x1       Thread 1 of 1     │                             … │",
            "              Samples: 10    Duration: 0.0     │                             … │",
            "                             seconds           ╰───────────────────────────────╯",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_plot_with_increasing_allocations(self):
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
        for _ in range(50):
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

        rprint(tui.get_header(), file=output)

        # THEN
        expected = [
            "Memray live tracking                                    Fri Jan  1 00:00:00 "
            "2021",
            "                                               ╭─ Memory ──────────────────────╮",
            "(∩｀-´)⊃━☆ﾟ.*…PID: 123       CMD: python3      │                             … │",
            "                             some_program.py   │                         ⢀⣀⣀⣠… │",
            "              TID: 0x1       Thread 1 of 1     │            ⢀⣀⣀⣠⣤⣤⣤⣴⣶⣶⣾⣿⣿⣿⣿⣿⣿… │",
            "              Samples: 50    Duration: 0.0     │ ⢀⣀⣠⣤⣤⣴⣶⣶⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿… │",
            "                             seconds           ╰───────────────────────────────╯",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected


class TestGraph:
    def test_empty(self):
        # GIVEN

        plot = MemoryGraph(50, 4, 0.0, 100.0)

        # WHEN

        graph = plot.graph

        # THEN

        assert plot.maxval == 100.0
        assert plot.minval == 0
        assert graph == ("", "", "", "")

    def test_size_of_graph(self):
        # GIVEN
        size = 36
        rows = 10

        plot = MemoryGraph(size, rows, 0.0, 100.0)

        # WHEN

        for point in range(50):
            plot.add_value(point)
        graph = plot.graph

        # THEN

        assert len(graph) == rows
        assert all(len(row) == size for row in graph)

    def test_one_point_lower_than_max(self):
        # GIVEN

        plot = MemoryGraph(50, 4, 0.0, 100.0)

        # WHEN

        plot.add_value(50.0)

        # THEN

        assert plot.maxval == 100.0
        assert plot.minval == 0
        assert plot.graph == (" ", " ", "⢸", "⢸")

    def test_one_point_bigger_than_max(self):
        # GIVEN

        plot = MemoryGraph(50, 4, 0.0, 100.0)

        # WHEN

        plot.add_value(500.0)

        # THEN

        assert plot.maxval == 100.0
        assert plot.minval == 0
        assert plot.graph == ("⢸", "⢸", "⢸", "⢸")

    def test_one_point_bigger_than_max_before_resize(self):
        # GIVEN

        plot = MemoryGraph(50, 4, 0.0, 100.0)

        # WHEN

        plot.reset_max(1000)
        plot.add_value(500.0)

        # THEN

        assert plot.maxval == 1000.0
        assert plot.minval == 0
        assert plot.graph == (
            "                                                  ",
            "                                                  ",
            "                                                 ⢸",
            "                                                 ⢸",
        )

    def test_one_point_bigger_than_max_after_resize(self):
        # GIVEN

        plot = MemoryGraph(50, 4, 0.0, 100.0)

        # WHEN

        plot.add_value(500.0)
        plot.reset_max(1000)

        # THEN

        assert plot.maxval == 1000.0
        assert plot.minval == 0
        assert plot.graph == (
            "                                                  ",
            "                                                  ",
            "                                                 ⢸",
            "                                                 ⢸",
        )

    def test_multiple_points(self):
        # GIVEN

        plot = MemoryGraph(50, 4, 0.0, 100.0)

        # WHEN

        for point in range(50):
            plot.add_value(point)

        # THEN

        assert plot.maxval == 100.0
        assert plot.minval == 0
        assert plot.graph == (
            "                                                  ",
            "                                                  ",
            "                          ⢀⣀⣀⣀⣀⣀⣠⣤⣤⣤⣤⣤⣴⣶⣶⣶⣶⣶⣾⣿⣿⣿⣿⣿",
            " ⢀⣀⣀⣀⣀⣀⣠⣤⣤⣤⣤⣤⣴⣶⣶⣶⣶⣶⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
        )

    def test_multiple_points_with_resize(self):
        # GIVEN

        plot = MemoryGraph(50, 4, 0.0, 40.0)

        # WHEN

        for point in range(50):
            plot.add_value(point)
        plot_before_resize = plot.graph
        plot.reset_max(100.0)
        plot_after_resize = plot.graph

        # THEN
        assert plot_before_resize == (
            "                               ⢀⣀⣠⣤⣤⣴⣶⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
            "                     ⢀⣀⣠⣤⣤⣴⣶⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
            "           ⢀⣀⣠⣤⣤⣴⣶⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
            " ⢀⣀⣠⣤⣤⣴⣶⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
        )
        assert plot.maxval == 100.0
        assert plot.minval == 0
        assert plot_after_resize == (
            "                                                  ",
            "                                                  ",
            "                          ⢀⣀⣀⣀⣀⣀⣠⣤⣤⣤⣤⣤⣴⣶⣶⣶⣶⣶⣾⣿⣿⣿⣿⣿",
            " ⢀⣀⣀⣀⣀⣀⣠⣤⣤⣤⣤⣤⣴⣶⣶⣶⣶⣶⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
        )

    def test_multiple_points_with_resize_with_more_additions(self):
        # GIVEN

        plot = MemoryGraph(50, 4, 0.0, 15.0)

        # WHEN

        for point in range(25):
            plot.add_value(point)
        plot_before_resize = plot.graph
        plot.reset_max(50.0)
        for point in range(25, 50):
            plot.add_value(point)
        plot_after_resize = plot.graph

        # THEN
        assert plot_before_resize == (
            "            ⢀⣠⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿",
            "        ⢀⣠⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
            "    ⢀⣠⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
            " ⢠⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
        )
        assert plot.maxval == 50.0
        assert plot.minval == 0
        assert plot_after_resize == (
            "                                      ⢀⣀⣀⣠⣤⣤⣴⣶⣶⣾⣿⣿",
            "                          ⢀⣀⣀⣠⣤⣤⣴⣶⣶⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
            "             ⢀⣀⣀⣠⣤⣤⣴⣶⣶⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
            " ⢀⣀⣀⣠⣤⣤⣴⣶⣶⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿",
        )


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
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
            "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
            "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
            "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
            "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
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
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
            "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
            "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
            "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
            "│ function1 at /src/lel.py            │ 1.000… │ 100.… │ 1.00… │ 100.… │     1 │",
            "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
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
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
            "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
            "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
            "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
            "│ function4 at /src/lel_4.py          │ 5.000… │ 33.3… │ 5.00… │ 33.3… │     1 │",
            "│ function3 at /src/lel_3.py          │ 4.000… │ 26.6… │ 4.00… │ 26.6… │     1 │",
            "│ function2 at /src/lel_2.py          │ 3.000… │ 20.0… │ 3.00… │ 20.0… │     1 │",
            "│ function1 at /src/lel_1.py          │ 2.000… │ 13.3… │ 2.00… │ 13.3… │     1 │",
            "│ function0 at /src/lel_0.py          │ 1.000… │ 6.67% │ 1.00… │ 6.67% │     1 │",
            "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
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
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
            "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
            "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
            "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
            "│ function0 at /src/lel_0.py          │ 1.000… │ 6.67% │ 1.00… │ 6.67% │     1 │",
            "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
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
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
            "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
            "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
            "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
            "│ function3 at /src/lel_3.py          │ 4.000… │ 26.6… │ 4.00… │ 26.6… │     1 │",
            "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
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
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
            "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
            "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
            "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
            "│ function4 at /src/lel_4.py          │ 5.000… │ 33.3… │ 5.00… │ 33.3… │     5 │",
            "│ function3 at /src/lel_3.py          │ 4.000… │ 26.6… │ 4.00… │ 26.6… │     4 │",
            "│ function2 at /src/lel_2.py          │ 3.000… │ 20.0… │ 3.00… │ 20.0… │     3 │",
            "│ function1 at /src/lel_1.py          │ 2.000… │ 13.3… │ 2.00… │ 13.3… │     2 │",
            "│ function0 at /src/lel_0.py          │ 1.000… │ 6.67% │ 1.00… │ 6.67% │     1 │",
            "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
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
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
            "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
            "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
            "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
            "│ parent at fun.py                    │ 30.00… │ 100.… │ 0.00… │ 0.00% │     3 │",
            "│ grandparent at fun.py               │ 30.00… │ 100.… │ 0.00… │ 0.00% │     3 │",
            "│ sibling at fun.py                   │ 20.00… │ 66.6… │ 20.0… │ 66.6… │     1 │",
            "│ me at fun.py                        │ 10.00… │ 33.3… │ 10.0… │ 33.3… │     2 │",
            "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected


@patch("memray.reporters.tui.datetime", FakeDate)
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
            "Memray live tracking                                    Fri Jan  1 00:00:00 2021",
            "                                               ╭─ Memory ──────────────────────╮",
            "(∩｀-´)⊃━☆ﾟ.*…PID: 123      CMD: python3       │                             … │",
            "                            some_program.py    │                             … │",
            "              TID: 0x1      Thread 1 of 1      │                             … │",
            "              Samples: 1    Duration: 0.0      │                             … │",
            "                            seconds            ╰───────────────────────────────╯",
            "Current heap size: 15.000KB                         Max heap size seen: 15.000KB",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸",
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
            "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
            "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
            "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
            "│ function4 at /src/lel_4.py          │ 5.000… │ 33.3… │ 5.00… │ 33.3… │     5 │",
            "│ function3 at /src/lel_3.py          │ 4.000… │ 26.6… │ 4.00… │ 26.6… │     4 │",
            "│ function2 at /src/lel_2.py          │ 3.000… │ 20.0… │ 3.00… │ 20.0… │     3 │",
            "│ function1 at /src/lel_1.py          │ 2.000… │ 13.3… │ 2.00… │ 13.3… │     2 │",
            "│ function0 at /src/lel_0.py          │ 1.000… │ 6.67% │ 1.00… │ 6.67% │     1 │",
            "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
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

    def test_native_frames(self):
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
                _hybrid_stack=[],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=20,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _hybrid_stack=[
                    ("sibling", "fun.c", 16),
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
                _hybrid_stack=[],
            ),
        ]
        # WHEN
        result = aggregate_allocations(allocation_records, native_traces=True)

        # THEN
        grandparent = result[Location(function="grandparent", file="fun.py")]
        assert grandparent.own_memory == 0
        assert grandparent.total_memory == 20
        assert grandparent.n_allocations == 1

        me = result[Location(function="???", file="???")]
        assert me.own_memory == 40
        assert me.total_memory == 40
        assert me.n_allocations == 3


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
