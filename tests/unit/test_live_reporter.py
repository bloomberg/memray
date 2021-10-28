import datetime
from io import StringIO
from unittest.mock import MagicMock
from unittest.mock import patch

from rich import print as rprint

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve.commands.live import TUI
from tests.utils import MockAllocationRecord


class FakeDate(MagicMock):
    @classmethod
    def now(cls):
        return datetime.datetime(2021, 1, 1)


@patch("bloomberg.pensieve.commands.live.datetime", FakeDate)
class TestTUIHeader:
    def test_pid(self):

        # GIVEN
        pid = 9999
        cmd_line = ""
        snapshot = []
        output = StringIO()
        tui = TUI(pid, cmd_line)

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_header(), file=output)

        # THEN
        expected = [
            "Bloomberg pensieve live                                 Fri Jan  1 00:00:00 2021",
            "tracking",
            "              PID: 123      CMD:",
            "(∩｀-´)⊃━☆ﾟ.*…TID: 0x0      Thread 1 of 0",
            "              Samples: 1    Duration: 0.0 seconds",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_command_line(self):
        # GIVEN
        pid = 0
        cmd_line = "python3 some_command_to_test.py"
        snapshot = []
        output = StringIO()
        tui = TUI(pid, cmd_line)

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
        pid = 0
        cmd_line = "python3 " + "a" * 100
        snapshot = []
        output = StringIO()
        tui = TUI(pid, cmd_line)

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
        pid = 1234
        cmd_line = "python3 some_program.py"
        snapshot = []
        output = StringIO()
        tui = TUI(pid, cmd_line)

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
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

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
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

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
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

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
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

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
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

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
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

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
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

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
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

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
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

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
        pid = 1234
        cmd_line = "python3 some_program.py"
        snapshot = []

        output = StringIO()
        tui = TUI(pid, cmd_line)

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ Allocat… ┃ Size    ┃ Alloca… ┃",
            "┃                                               ┃          ┃         ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_with_one_allocation(self):
        # GIVEN
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ Allocat… ┃ Size    ┃ Alloca… ┃",
            "┃                                               ┃          ┃         ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function1 at /src/lel.py:18                   │ malloc   │ 1.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_multiple_allocations_same_thread(self):
        # GIVEN
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ Allocat… ┃ Size    ┃ Alloca… ┃",
            "┃                                               ┃          ┃         ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function4 at /src/lel_4.py:4                  │ malloc   │ 5.000KB │ 1       │",
            "│ function3 at /src/lel_3.py:3                  │ malloc   │ 4.000KB │ 1       │",
            "│ function2 at /src/lel_2.py:2                  │ malloc   │ 3.000KB │ 1       │",
            "│ function1 at /src/lel_1.py:1                  │ malloc   │ 2.000KB │ 1       │",
            "│ function0 at /src/lel_0.py:0                  │ malloc   │ 1.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_multiple_allocations_different_threads(self):
        # GIVEN
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

        # WHEN
        tui.update_snapshot(snapshot)
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ Allocat… ┃ Size    ┃ Alloca… ┃",
            "┃                                               ┃          ┃         ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function0 at /src/lel_0.py:0                  │ malloc   │ 1.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_multiple_allocations_different_threads_change_thread(self):
        # GIVEN
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

        # WHEN
        tui.update_snapshot(snapshot)
        for _ in range(3):
            tui.next_thread()
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ Allocat… ┃ Size    ┃ Alloca… ┃",
            "┃                                               ┃          ┃         ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function3 at /src/lel_3.py:3                  │ malloc   │ 4.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected

    def test_multiple_allocations_different_n_allocations(self):
        # GIVEN
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

        # WHEN
        tui.update_snapshot(snapshot)
        for _ in range(3):
            tui.next_thread()
        rprint(tui.get_body(), file=output)

        # THEN
        expected = [
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┓",
            "┃ Location                                      ┃ Allocat… ┃ Size    ┃ Alloca… ┃",
            "┃                                               ┃          ┃         ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function4 at /src/lel_4.py:4                  │ malloc   │ 5.000KB │ 5       │",
            "│ function3 at /src/lel_3.py:3                  │ malloc   │ 4.000KB │ 4       │",
            "│ function2 at /src/lel_2.py:2                  │ malloc   │ 3.000KB │ 3       │",
            "│ function1 at /src/lel_1.py:1                  │ malloc   │ 2.000KB │ 2       │",
            "│ function0 at /src/lel_0.py:0                  │ malloc   │ 1.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
        ]
        actual = [line.rstrip() for line in output.getvalue().splitlines()]
        assert actual == expected


@patch("bloomberg.pensieve.commands.live.datetime", FakeDate)
class TestTUILayout:
    def test_with_multiple_allocations(self):
        # GIVEN
        pid = 1234
        cmd_line = "python3 some_program.py"
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
        tui = TUI(pid, cmd_line)

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
            "┃ Location                                      ┃ Allocat… ┃ Size    ┃ Alloca… ┃",
            "┃                                               ┃          ┃         ┃ Count   ┃",
            "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━┩",
            "│ function4 at /src/lel_4.py:4                  │ malloc   │ 5.000KB │ 5       │",
            "│ function3 at /src/lel_3.py:3                  │ malloc   │ 4.000KB │ 4       │",
            "│ function2 at /src/lel_2.py:2                  │ malloc   │ 3.000KB │ 3       │",
            "│ function1 at /src/lel_1.py:1                  │ malloc   │ 2.000KB │ 2       │",
            "│ function0 at /src/lel_0.py:0                  │ malloc   │ 1.000KB │ 1       │",
            "└───────────────────────────────────────────────┴──────────┴─────────┴─────────┘",
            " Q  Quit  ←   Previous Thread  →   Next Thread",
        ]
        actual = [
            line.rstrip() for line in output.getvalue().splitlines() if line.rstrip()
        ]
        assert actual == expected
