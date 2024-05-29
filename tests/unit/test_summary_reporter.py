from io import StringIO

from memray import AllocatorType
from memray.reporters.summary import SummaryReporter
from tests.utils import MockAllocationRecord


def test_with_multiple_allocations():
    # GIVEN
    snapshot = [
        MockAllocationRecord(
            tid=1,
            address=0x1000000,
            size=1024 - (4 - i),
            allocator=AllocatorType.MALLOC,
            stack_id=1,
            n_allocations=i + 1,
            _stack=[
                (f"function{i}", f"/src/lel_{i}.py", i),
                (f"function{i+1}", f"/src/lel_{i+1}.py", i),
            ],
        )
        for i in range(5)
    ]

    reporter = SummaryReporter.from_snapshot(snapshot)
    output = StringIO()

    # WHEN
    reporter.render(sort_column=1, file=output)

    # THEN
    expected = [
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
        "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
        "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
        "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
        "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
        "│ function4 at /src/lel_4.py          │ 1.999… │ 40.0… │ 1.00… │ 20.0… │     9 │",
        "│ function3 at /src/lel_3.py          │ 1.997… │ 40.0… │ 1023… │ 20.0… │     7 │",
        "│ function2 at /src/lel_2.py          │ 1.995… │ 39.9… │ 1022… │ 20.0… │     5 │",
        "│ function1 at /src/lel_1.py          │ 1.993… │ 39.9… │ 1021… │ 19.9… │     3 │",
        "│ function5 at /src/lel_5.py          │ 1.000… │ 20.0… │ 0.00… │ 0.00% │     5 │",
        "│ function0 at /src/lel_0.py          │ 1020.… │ 19.9… │ 1020… │ 19.9… │     1 │",
        "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
    ]
    actual = [line.rstrip() for line in output.getvalue().splitlines()]
    assert actual == expected


def test_with_multiple_allocations_and_native_traces():
    # GIVEN
    snapshot = [
        MockAllocationRecord(
            tid=1,
            address=0x1000000,
            size=1024 - (4 - i),
            allocator=AllocatorType.MALLOC,
            stack_id=1,
            n_allocations=i + 1,
            _stack=[],
            _hybrid_stack=[
                ("me", "fun.py", 12),
                ("parent", "fun.pyx", 8),
                ("grandparent", "fun.c", 4),
            ],
        )
        for i in range(5)
    ]

    reporter = SummaryReporter.from_snapshot(snapshot, native=True)
    output = StringIO()

    # WHEN
    reporter.render(sort_column=1, file=output)

    # THEN
    expected = [
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
        "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
        "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
        "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
        "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
        "│ me at fun.py                        │ 4.990… │ 100.… │ 4.99… │ 100.… │    15 │",
        "│ parent at fun.pyx                   │ 4.990… │ 100.… │ 0.00… │ 0.00% │    15 │",
        "│ grandparent at fun.c                │ 4.990… │ 100.… │ 0.00… │ 0.00% │    15 │",
        "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
    ]
    actual = [line.rstrip() for line in output.getvalue().splitlines()]
    assert actual == expected


def test_sort_column():
    # GIVEN
    snapshot = [
        MockAllocationRecord(
            tid=1,
            address=0x1000000,
            size=1024 - (4 - i),
            allocator=AllocatorType.MALLOC,
            stack_id=1,
            n_allocations=i + 1,
            _stack=[
                (f"function{i}", f"/src/lel_{i}.py", i),
                (f"function{i+1}", f"/src/lel_{i+1}.py", i),
            ],
        )
        for i in range(5)
    ]

    reporter = SummaryReporter.from_snapshot(snapshot)
    output = StringIO()

    # WHEN
    reporter.render(sort_column=3, file=output)

    # THEN
    expected = [
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
        "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
        "┃                                     ┃  Total ┃ Memo… ┃  <Own ┃ Memo… ┃ Allo… ┃",
        "┃ Location                            ┃ Memory ┃     % ┃ Memo… ┃     % ┃ Count ┃",
        "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
        "│ function4 at /src/lel_4.py          │ 1.999… │ 40.0… │ 1.00… │ 20.0… │     9 │",
        "│ function3 at /src/lel_3.py          │ 1.997… │ 40.0… │ 1023… │ 20.0… │     7 │",
        "│ function2 at /src/lel_2.py          │ 1.995… │ 39.9… │ 1022… │ 20.0… │     5 │",
        "│ function1 at /src/lel_1.py          │ 1.993… │ 39.9… │ 1021… │ 19.9… │     3 │",
        "│ function0 at /src/lel_0.py          │ 1020.… │ 19.9… │ 1020… │ 19.9… │     1 │",
        "│ function5 at /src/lel_5.py          │ 1.000… │ 20.0… │ 0.00… │ 0.00% │     5 │",
        "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
    ]
    actual = [line.rstrip() for line in output.getvalue().splitlines()]
    assert actual == expected


def test_max_rows():
    # GIVEN
    snapshot = [
        MockAllocationRecord(
            tid=1,
            address=0x1000000,
            size=1024 - (4 - i),
            allocator=AllocatorType.MALLOC,
            stack_id=1,
            n_allocations=i + 1,
            _stack=[
                (f"function{i}", f"/src/lel_{i}.py", i),
                (f"function{i+1}", f"/src/lel_{i+1}.py", i),
            ],
        )
        for i in range(5)
    ]

    reporter = SummaryReporter.from_snapshot(snapshot)
    output = StringIO()

    # WHEN
    reporter.render(sort_column=1, max_rows=3, file=output)

    # THEN
    expected = [
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
        "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
        "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
        "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
        "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
        "│ function4 at /src/lel_4.py          │ 1.999… │ 40.0… │ 1.00… │ 20.0… │     9 │",
        "│ function3 at /src/lel_3.py          │ 1.997… │ 40.0… │ 1023… │ 20.0… │     7 │",
        "│ function2 at /src/lel_2.py          │ 1.995… │ 39.9… │ 1022… │ 20.0… │     5 │",
        "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
    ]
    actual = [line.rstrip() for line in output.getvalue().splitlines()]
    assert actual == expected


def test_non_sequence_iterable():
    # GIVEN
    snapshot = (
        MockAllocationRecord(
            tid=1,
            address=0x1000000,
            size=1024 - (4 - i),
            allocator=AllocatorType.MALLOC,
            stack_id=1,
            n_allocations=i + 1,
            _stack=[
                (f"function{i}", f"/src/lel_{i}.py", i),
                (f"function{i+1}", f"/src/lel_{i+1}.py", i),
            ],
        )
        for i in range(5)
    )

    reporter = SummaryReporter.from_snapshot(snapshot)
    output = StringIO()

    # WHEN
    reporter.render(sort_column=1, max_rows=3, file=output)

    # THEN
    expected = [
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━┓",
        "┃                                     ┃        ┃ Total ┃       ┃   Own ┃       ┃",
        "┃                                     ┃ <Total ┃ Memo… ┃   Own ┃ Memo… ┃ Allo… ┃",
        "┃ Location                            ┃ Memor… ┃     % ┃ Memo… ┃     % ┃ Count ┃",
        "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━┩",
        "│ function4 at /src/lel_4.py          │ 1.999… │ 40.0… │ 1.00… │ 20.0… │     9 │",
        "│ function3 at /src/lel_3.py          │ 1.997… │ 40.0… │ 1023… │ 20.0… │     7 │",
        "│ function2 at /src/lel_2.py          │ 1.995… │ 39.9… │ 1022… │ 20.0… │     5 │",
        "└─────────────────────────────────────┴────────┴───────┴───────┴───────┴───────┘",
    ]
    actual = [line.rstrip() for line in output.getvalue().splitlines()]
    assert actual == expected
