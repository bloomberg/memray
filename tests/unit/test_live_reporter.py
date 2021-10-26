from io import StringIO

from rich import print as rprint

from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve.commands.live import construct_allocation_table
from tests.utils import MockAllocationRecord


def test_initializes_with_empty_table():
    # GIVEN
    snapshot = []
    output = StringIO()

    # WHEN
    rprint(construct_allocation_table(snapshot), file=output)

    # THEN
    expected = [
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┓",
        "┃ Location                                 ┃ Alloc… ┃ Thread ┃ Size   ┃ Alloc… ┃",
        "┃                                          ┃        ┃ ID     ┃        ┃ Count  ┃",
        "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━┩",
        "└──────────────────────────────────────────┴────────┴────────┴────────┴────────┘",
    ]
    assert [line.rstrip() for line in output.getvalue().splitlines()] == expected


def test_shows_single_allocation():
    # GIVEN
    snapshot = [
        MockAllocationRecord(
            tid=1,
            address=0x1000000,
            size=1024,
            allocator=AllocatorType.MALLOC,
            stack_id=1,
            n_allocations=1,
            _stack=[("function1", "/src/lel.py", 42)],
        )
    ]
    output = StringIO()

    # WHEN
    rprint(construct_allocation_table(snapshot), file=output)

    # THEN
    expected = [
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┓",
        "┃ Location                                 ┃ Alloc… ┃ Thread ┃ Size   ┃ Alloc… ┃",
        "┃                                          ┃        ┃ ID     ┃        ┃ Count  ┃",
        "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━┩",
        "│ function1 at /src/lel.py:42              │ malloc │ 1      │ 1.000… │ 1      │",
        "└──────────────────────────────────────────┴────────┴────────┴────────┴────────┘",
    ]
    assert [line.rstrip() for line in output.getvalue().splitlines()] == expected


def test_shows_all_allocations():
    # GIVEN
    table_size = 10
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
        for i in range(table_size)
    ]
    output = StringIO()

    # WHEN
    rprint(construct_allocation_table(snapshot), file=output)

    # THEN
    expected = [
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┓",
        "┃ Location                                 ┃ Alloc… ┃ Thread ┃ Size   ┃ Alloc… ┃",
        "┃                                          ┃        ┃ ID     ┃        ┃ Count  ┃",
        "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━┩",
        "│ function9 at /src/lel.py:18              │ malloc │ 1      │ 10.00… │ 1      │",
        "│ function8 at /src/lel.py:18              │ malloc │ 1      │ 9.000… │ 1      │",
        "│ function7 at /src/lel.py:18              │ malloc │ 1      │ 8.000… │ 1      │",
        "│ function6 at /src/lel.py:18              │ malloc │ 1      │ 7.000… │ 1      │",
        "│ function5 at /src/lel.py:18              │ malloc │ 1      │ 6.000… │ 1      │",
        "│ function4 at /src/lel.py:18              │ malloc │ 1      │ 5.000… │ 1      │",
        "│ function3 at /src/lel.py:18              │ malloc │ 1      │ 4.000… │ 1      │",
        "│ function2 at /src/lel.py:18              │ malloc │ 1      │ 3.000… │ 1      │",
        "│ function1 at /src/lel.py:18              │ malloc │ 1      │ 2.000… │ 1      │",
        "│ function0 at /src/lel.py:18              │ malloc │ 1      │ 1.000… │ 1      │",
        "└──────────────────────────────────────────┴────────┴────────┴────────┴────────┘",
    ]
    assert [line.rstrip() for line in output.getvalue().splitlines()] == expected
