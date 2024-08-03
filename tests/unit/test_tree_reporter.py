from dataclasses import dataclass
from textwrap import dedent
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Optional
from typing import Tuple
from unittest.mock import patch

import pytest
from textual.pilot import Pilot
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from memray import AllocationRecord
from memray import AllocatorType
from memray.reporters.tree import MAX_STACKS
from memray.reporters.tree import Frame
from memray.reporters.tree import TreeReporter
from tests.utils import MockAllocationRecord
from tests.utils import async_run


class TestTreeReporter:
    def test_works_with_no_allocations(self):
        reporter = TreeReporter.from_snapshot([], native_traces=False)
        assert reporter.data == Frame(
            location=("<ROOT>", "", 0),
            value=0,
            children={},
            n_allocations=0,
            thread_id="",
            interesting=True,
        )

    def test_works_with_single_call(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
        ]

        # WHEN
        reporter = TreeReporter.from_snapshot(
            peak_allocations, native_traces=False, biggest_allocs=5
        )

        # THEN
        assert reporter.data == Frame(
            location=("<ROOT>", "", 0),
            value=1024,
            children={
                ("grandparent", "fun.py", 4): Frame(
                    location=("grandparent", "fun.py", 4),
                    value=1024,
                    children={
                        ("parent", "fun.py", 8): Frame(
                            location=("parent", "fun.py", 8),
                            value=1024,
                            children={
                                ("me", "fun.py", 12): Frame(
                                    location=("me", "fun.py", 12),
                                    value=1024,
                                    children={},
                                    n_allocations=1,
                                    thread_id="0x1",
                                    interesting=True,
                                    import_system=False,
                                )
                            },
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            import_system=False,
                        )
                    },
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    import_system=False,
                )
            },
            n_allocations=1,
            thread_id="",
            interesting=True,
            import_system=False,
        )

    def test_uses_hybrid_stack_for_native_traces(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _hybrid_stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.pyx", 8),
                    ("grandparent", "fun.c", 4),
                ],
            ),
        ]

        # WHEN
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=True)

        # THEN
        assert reporter.data == Frame(
            location=("<ROOT>", "", 0),
            value=1024,
            children={
                ("grandparent", "fun.c", 4): Frame(
                    location=("grandparent", "fun.c", 4),
                    value=1024,
                    children={
                        ("parent", "fun.pyx", 8): Frame(
                            location=("parent", "fun.pyx", 8),
                            value=1024,
                            children={
                                ("me", "fun.py", 12): Frame(
                                    location=("me", "fun.py", 12),
                                    value=1024,
                                    children={},
                                    n_allocations=1,
                                    thread_id="0x1",
                                    interesting=True,
                                    import_system=False,
                                )
                            },
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            import_system=False,
                        )
                    },
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    import_system=False,
                )
            },
            n_allocations=1,
            thread_id="",
            interesting=True,
            import_system=False,
        )

    def test_works_with_multiple_stacks_from_same_caller(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
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
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)

        # THEN
        assert reporter.data == Frame(
            location=("<ROOT>", "", 0),
            value=2048,
            children={
                ("grandparent", "fun.py", 4): Frame(
                    location=("grandparent", "fun.py", 4),
                    value=2048,
                    children={
                        ("parent", "fun.py", 8): Frame(
                            location=("parent", "fun.py", 8),
                            value=2048,
                            children={
                                ("me", "fun.py", 12): Frame(
                                    location=("me", "fun.py", 12),
                                    value=1024,
                                    children={},
                                    n_allocations=1,
                                    thread_id="0x1",
                                    interesting=True,
                                    import_system=False,
                                ),
                                ("sibling", "fun.py", 16): Frame(
                                    location=("sibling", "fun.py", 16),
                                    value=1024,
                                    children={},
                                    n_allocations=1,
                                    thread_id="0x1",
                                    interesting=True,
                                    import_system=False,
                                ),
                            },
                            n_allocations=2,
                            thread_id="0x1",
                            interesting=True,
                            import_system=False,
                        )
                    },
                    n_allocations=2,
                    thread_id="0x1",
                    interesting=True,
                    import_system=False,
                )
            },
            n_allocations=2,
            thread_id="",
            interesting=True,
            import_system=False,
        )

    def test_works_with_multiple_stacks_from_same_caller_two_frames_above(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent_one", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("sibling", "fun.py", 16),
                    ("parent_two", "fun.py", 10),
                    ("grandparent", "fun.py", 4),
                ],
            ),
        ]

        # WHEN
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)

        # THEN
        assert reporter.data == Frame(
            location=("<ROOT>", "", 0),
            value=2048,
            children={
                ("grandparent", "fun.py", 4): Frame(
                    location=("grandparent", "fun.py", 4),
                    value=2048,
                    children={
                        ("parent_one", "fun.py", 8): Frame(
                            location=("parent_one", "fun.py", 8),
                            value=1024,
                            children={
                                ("me", "fun.py", 12): Frame(
                                    location=("me", "fun.py", 12),
                                    value=1024,
                                    children={},
                                    n_allocations=1,
                                    thread_id="0x1",
                                    interesting=True,
                                    import_system=False,
                                )
                            },
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            import_system=False,
                        ),
                        ("parent_two", "fun.py", 10): Frame(
                            location=("parent_two", "fun.py", 10),
                            value=1024,
                            children={
                                ("sibling", "fun.py", 16): Frame(
                                    location=("sibling", "fun.py", 16),
                                    value=1024,
                                    children={},
                                    n_allocations=1,
                                    thread_id="0x1",
                                    interesting=True,
                                    import_system=False,
                                )
                            },
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            import_system=False,
                        ),
                    },
                    n_allocations=2,
                    thread_id="0x1",
                    interesting=True,
                    import_system=False,
                )
            },
            n_allocations=2,
            thread_id="",
            interesting=True,
            import_system=False,
        )

    def test_works_with_recursive_calls(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("one", "recursive.py", 9),
                    ("two", "recursive.py", 20),
                    ("one", "recursive.py", 10),
                    ("two", "recursive.py", 20),
                    ("one", "recursive.py", 10),
                    ("two", "recursive.py", 20),
                    ("main", "recursive.py", 5),
                ],
            ),
        ]

        # WHEN
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)

        # THEN
        assert reporter.data == Frame(
            location=("<ROOT>", "", 0),
            value=1024,
            children={
                ("main", "recursive.py", 5): Frame(
                    location=("main", "recursive.py", 5),
                    value=1024,
                    children={
                        ("two", "recursive.py", 20): Frame(
                            location=("two", "recursive.py", 20),
                            value=1024,
                            children={
                                ("one", "recursive.py", 10): Frame(
                                    location=("one", "recursive.py", 10),
                                    value=1024,
                                    children={
                                        ("two", "recursive.py", 20): Frame(
                                            location=("two", "recursive.py", 20),
                                            value=1024,
                                            children={
                                                ("one", "recursive.py", 10): Frame(
                                                    location=(
                                                        "one",
                                                        "recursive.py",
                                                        10,
                                                    ),
                                                    value=1024,
                                                    children={
                                                        (
                                                            "two",
                                                            "recursive.py",
                                                            20,
                                                        ): Frame(
                                                            location=(
                                                                "two",
                                                                "recursive.py",
                                                                20,
                                                            ),
                                                            value=1024,
                                                            children={
                                                                (
                                                                    "one",
                                                                    "recursive.py",
                                                                    9,
                                                                ): Frame(
                                                                    location=(
                                                                        "one",
                                                                        "recursive.py",
                                                                        9,
                                                                    ),
                                                                    value=1024,
                                                                    children={},
                                                                    n_allocations=1,
                                                                    thread_id="0x1",
                                                                    interesting=True,
                                                                    import_system=False,
                                                                )
                                                            },
                                                            n_allocations=1,
                                                            thread_id="0x1",
                                                            interesting=True,
                                                            import_system=False,
                                                        )
                                                    },
                                                    n_allocations=1,
                                                    thread_id="0x1",
                                                    interesting=True,
                                                    import_system=False,
                                                )
                                            },
                                            n_allocations=1,
                                            thread_id="0x1",
                                            interesting=True,
                                            import_system=False,
                                        )
                                    },
                                    n_allocations=1,
                                    thread_id="0x1",
                                    interesting=True,
                                    import_system=False,
                                )
                            },
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            import_system=False,
                        )
                    },
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    import_system=False,
                )
            },
            n_allocations=1,
            thread_id="",
            interesting=True,
            import_system=False,
        )

    def test_works_with_multiple_top_level_nodes(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("baz2", "/src/lel.py", 18),
                    ("bar2", "/src/lel.py", 15),
                    ("foo2", "/src/lel.py", 12),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("baz1", "/src/lel.py", 8),
                    ("bar1", "/src/lel.py", 5),
                    ("foo1", "/src/lel.py", 2),
                ],
            ),
        ]

        # WHEN
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)

        # THEN
        assert reporter.data == Frame(
            location=("<ROOT>", "", 0),
            value=2048,
            children={
                ("foo2", "/src/lel.py", 12): Frame(
                    location=("foo2", "/src/lel.py", 12),
                    value=1024,
                    children={
                        ("bar2", "/src/lel.py", 15): Frame(
                            location=("bar2", "/src/lel.py", 15),
                            value=1024,
                            children={
                                ("baz2", "/src/lel.py", 18): Frame(
                                    location=("baz2", "/src/lel.py", 18),
                                    value=1024,
                                    children={},
                                    n_allocations=1,
                                    thread_id="0x1",
                                    interesting=True,
                                    import_system=False,
                                )
                            },
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            import_system=False,
                        )
                    },
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    import_system=False,
                ),
                ("foo1", "/src/lel.py", 2): Frame(
                    location=("foo1", "/src/lel.py", 2),
                    value=1024,
                    children={
                        ("bar1", "/src/lel.py", 5): Frame(
                            location=("bar1", "/src/lel.py", 5),
                            value=1024,
                            children={
                                ("baz1", "/src/lel.py", 8): Frame(
                                    location=("baz1", "/src/lel.py", 8),
                                    value=1024,
                                    children={},
                                    n_allocations=1,
                                    thread_id="0x1",
                                    interesting=True,
                                    import_system=False,
                                )
                            },
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            import_system=False,
                        )
                    },
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    import_system=False,
                ),
            },
            n_allocations=2,
            thread_id="",
            interesting=True,
            import_system=False,
        )

    def test_works_with_split_threads(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("baz2", "/src/lel.py", 18),
                    ("bar2", "/src/lel.py", 15),
                    ("foo2", "/src/lel.py", 12),
                ],
            ),
            MockAllocationRecord(
                tid=2,
                address=0x2000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("baz2", "/src/lel.py", 18),
                    ("bar2", "/src/lel.py", 15),
                    ("foo2", "/src/lel.py", 12),
                ],
            ),
        ]

        # WHEN
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)

        # THEN
        assert reporter.data == Frame(
            location=("<ROOT>", "", 0),
            value=2048,
            children={
                ("foo2", "/src/lel.py", 12): Frame(
                    location=("foo2", "/src/lel.py", 12),
                    value=2048,
                    children={
                        ("bar2", "/src/lel.py", 15): Frame(
                            location=("bar2", "/src/lel.py", 15),
                            value=2048,
                            children={
                                ("baz2", "/src/lel.py", 18): Frame(
                                    location=("baz2", "/src/lel.py", 18),
                                    value=2048,
                                    children={},
                                    n_allocations=2,
                                    thread_id="0x2",
                                    interesting=True,
                                    import_system=False,
                                )
                            },
                            n_allocations=2,
                            thread_id="0x2",
                            interesting=True,
                            import_system=False,
                        )
                    },
                    n_allocations=2,
                    thread_id="0x2",
                    interesting=True,
                    import_system=False,
                )
            },
            n_allocations=2,
            thread_id="",
            interesting=True,
            import_system=False,
        )

    def test_works_with_merged_threads(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=-1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("baz2", "/src/lel.py", 18),
                    ("bar2", "/src/lel.py", 15),
                    ("foo2", "/src/lel.py", 12),
                ],
            ),
            MockAllocationRecord(
                tid=-1,
                address=0x2000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("baz2", "/src/lel.py", 18),
                    ("bar2", "/src/lel.py", 15),
                    ("foo2", "/src/lel.py", 12),
                ],
            ),
        ]

        # WHEN
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)

        # THEN
        assert reporter.data == Frame(
            location=("<ROOT>", "", 0),
            value=2048,
            children={
                ("foo2", "/src/lel.py", 12): Frame(
                    location=("foo2", "/src/lel.py", 12),
                    value=2048,
                    children={
                        ("bar2", "/src/lel.py", 15): Frame(
                            location=("bar2", "/src/lel.py", 15),
                            value=2048,
                            children={
                                ("baz2", "/src/lel.py", 18): Frame(
                                    location=("baz2", "/src/lel.py", 18),
                                    value=2048,
                                    children={},
                                    n_allocations=2,
                                    thread_id="merged thread",
                                    interesting=True,
                                    import_system=False,
                                )
                            },
                            n_allocations=2,
                            thread_id="merged thread",
                            interesting=True,
                            import_system=False,
                        )
                    },
                    n_allocations=2,
                    thread_id="merged thread",
                    interesting=True,
                    import_system=False,
                )
            },
            n_allocations=2,
            thread_id="",
            interesting=True,
            import_system=False,
        )

    def test_drops_cpython_frames(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("PyObject_Call", "/src/python/python3.8/Python/ceval.c", 4),
                    (
                        "PyCFunction_Call",
                        "/src/python/python3.8/Objects/call.c",
                        1,
                    ),
                ],
            ),
        ]

        # WHEN
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)

        # THEN
        assert reporter.data == Frame(
            location=("<ROOT>", "", 0),
            value=1024,
            children={
                ("parent", "fun.py", 8): Frame(
                    location=("parent", "fun.py", 8),
                    value=1024,
                    children={
                        ("me", "fun.py", 12): Frame(
                            location=("me", "fun.py", 12),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            import_system=False,
                        )
                    },
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    import_system=False,
                )
            },
            n_allocations=1,
            thread_id="",
            interesting=True,
            import_system=False,
        )


@dataclass(frozen=True)
class TreeElement:
    label: str
    children: List["TreeElement"]
    allow_expand: bool
    is_expanded: bool


def tree_to_dict(tree: TreeNode):
    return TreeElement(
        str(tree.label),
        [tree_to_dict(child) for child in tree.children],
        tree.allow_expand,
        tree.is_expanded,
    )


class TestTreeTui:
    def test_no_allocations(self):
        # GIVEN
        peak_allocations = []

        reporter = TreeReporter.from_snapshot(
            peak_allocations, native_traces=False, biggest_allocs=3
        )
        app = reporter.get_app()

        # WHEN
        async def run_test():
            async with app.run_test() as pilot:
                await pilot.pause()
                return app.query_one(Tree).root

        root = async_run(run_test())

        # THEN
        assert tree_to_dict(root) == TreeElement(
            label="<No allocations>", children=[], is_expanded=True, allow_expand=True
        )

    def test_single_chain_is_expanded(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
        ]

        reporter = TreeReporter.from_snapshot(
            peak_allocations, native_traces=False, biggest_allocs=3
        )
        app = reporter.get_app()

        # WHEN
        async def run_test():
            async with app.run_test() as pilot:
                await pilot.pause()
                return app.query_one(Tree).root

        root = async_run(run_test())

        # THEN
        assert tree_to_dict(root) == TreeElement(
            label="📂 1.000KB (100.00 %) <ROOT>",
            children=[
                TreeElement(
                    label="📂 1.000KB (100.00 %) grandparent  fun.py:4",
                    children=[
                        TreeElement(
                            label="📂 1.000KB (100.00 %) parent  fun.py:8",
                            children=[
                                TreeElement(
                                    label="📄 1.000KB (100.00 %) me  fun.py:12",
                                    children=[],
                                    allow_expand=False,
                                    is_expanded=True,
                                )
                            ],
                            allow_expand=True,
                            is_expanded=True,
                        )
                    ],
                    allow_expand=True,
                    is_expanded=True,
                )
            ],
            allow_expand=True,
            is_expanded=True,
        )

    def test_only_biggest_chain_is_expanded(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 4,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 3,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 3,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("child2", "fun2.py", 22),
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
        ]

        reporter = TreeReporter.from_snapshot(
            peak_allocations, native_traces=False, biggest_allocs=3
        )
        app = reporter.get_app()

        # WHEN
        async def run_test():
            async with app.run_test() as pilot:
                await pilot.pause()
                return app.query_one(Tree).root

        root = async_run(run_test())

        # THEN
        assert tree_to_dict(root) == TreeElement(
            label="📂 10.000KB (100.00 %) <ROOT>",
            children=[
                TreeElement(
                    label="📂 6.000KB (60.00 %) grandparent2  fun2.py:4",
                    children=[
                        TreeElement(
                            label="📂 6.000KB (60.00 %) parent2  fun2.py:8",
                            children=[
                                TreeElement(
                                    label="📂 6.000KB (60.00 %) me2  fun2.py:12",
                                    children=[
                                        TreeElement(
                                            label="📄 3.000KB (30.00 %) child2  fun2.py:22",
                                            children=[],
                                            allow_expand=False,
                                            is_expanded=True,
                                        )
                                    ],
                                    allow_expand=True,
                                    is_expanded=True,
                                )
                            ],
                            allow_expand=True,
                            is_expanded=True,
                        )
                    ],
                    allow_expand=True,
                    is_expanded=True,
                ),
                TreeElement(
                    label="📂 4.000KB (40.00 %) grandparent  fun.py:4",
                    children=[
                        TreeElement(
                            label="📂 4.000KB (40.00 %) parent  fun.py:8",
                            children=[
                                TreeElement(
                                    label="📄 4.000KB (40.00 %) me  fun.py:12",
                                    children=[],
                                    allow_expand=False,
                                    is_expanded=False,
                                )
                            ],
                            allow_expand=True,
                            is_expanded=False,
                        )
                    ],
                    allow_expand=True,
                    is_expanded=False,
                ),
            ],
            allow_expand=True,
            is_expanded=True,
        )

    def test_show_uninteresting_system(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "foo.py", 12),
                    ("parent", "runpy.py", 8),
                    ("grandparent", "runpy.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
        ]

        reporter = TreeReporter.from_snapshot(
            peak_allocations, native_traces=False, biggest_allocs=3
        )
        app = reporter.get_app()

        # WHEN
        async def run_test():
            async with app.run_test() as pilot:
                await pilot.pause()
                tree = app.query_one(Tree)
                first_tree = tree_to_dict(tree.root)
                await pilot.press("u")
                await pilot.pause()
                second_tree = tree_to_dict(tree.root)
                return first_tree, second_tree

        first_tree, second_tree = async_run(run_test())

        # THEN
        assert first_tree == TreeElement(
            label="📂 11.000KB (100.00 %) <ROOT>",
            children=[
                TreeElement(
                    label="📂 10.000KB (90.91 %) grandparent2  fun2.py:4",
                    children=[
                        TreeElement(
                            label="📂 10.000KB (90.91 %) parent2  fun2.py:8",
                            children=[
                                TreeElement(
                                    label="📄 10.000KB (90.91 %) me2  fun2.py:12",
                                    children=[],
                                    allow_expand=False,
                                    is_expanded=True,
                                )
                            ],
                            allow_expand=True,
                            is_expanded=True,
                        )
                    ],
                    allow_expand=True,
                    is_expanded=True,
                ),
                TreeElement(
                    label="📄 1.000KB (9.09 %) me  foo.py:12",
                    children=[],
                    allow_expand=False,
                    is_expanded=False,
                ),
            ],
            allow_expand=True,
            is_expanded=True,
        )
        assert second_tree == TreeElement(
            label="📂 11.000KB (100.00 %) <ROOT>",
            children=[
                TreeElement(
                    label="📂 10.000KB (90.91 %) grandparent2  fun2.py:4",
                    children=[
                        TreeElement(
                            label="📂 10.000KB (90.91 %) parent2  fun2.py:8",
                            children=[
                                TreeElement(
                                    label="📄 10.000KB (90.91 %) me2  fun2.py:12",
                                    children=[],
                                    allow_expand=False,
                                    is_expanded=True,
                                )
                            ],
                            allow_expand=True,
                            is_expanded=True,
                        )
                    ],
                    allow_expand=True,
                    is_expanded=True,
                ),
                TreeElement(
                    label="📂 1.000KB (9.09 %) grandparent  runpy.py:4",
                    children=[
                        TreeElement(
                            label="📂 1.000KB (9.09 %) parent  runpy.py:8",
                            children=[
                                TreeElement(
                                    label="📄 1.000KB (9.09 %) me  foo.py:12",
                                    children=[],
                                    allow_expand=False,
                                    is_expanded=False,
                                )
                            ],
                            allow_expand=True,
                            is_expanded=False,
                        )
                    ],
                    allow_expand=True,
                    is_expanded=False,
                ),
            ],
            allow_expand=True,
            is_expanded=True,
        )

    def test_show_uninteresting_idempotency(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "foo.py", 12),
                    ("parent", "runpy.py", 8),
                    ("grandparent", "runpy.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
        ]

        reporter = TreeReporter.from_snapshot(
            peak_allocations, native_traces=False, biggest_allocs=3
        )
        app = reporter.get_app()

        # WHEN
        async def run_test():
            async with app.run_test() as pilot:
                await pilot.pause()
                tree = app.query_one(Tree)
                first_tree = tree_to_dict(tree.root)
                await pilot.press("i")
                await pilot.pause()
                await pilot.press("i")
                await pilot.pause()
                second_tree = tree_to_dict(tree.root)
                return first_tree, second_tree

        first_tree, second_tree = async_run(run_test())

        # THEN
        assert first_tree == second_tree

    def test_uninteresting_leaves(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("parent", "runpy.py", 8),
                    ("grandparent", "runpy.py", 4),
                    ("me", "foo.py", 12),
                ],
            ),
        ]

        reporter = TreeReporter.from_snapshot(
            peak_allocations, native_traces=False, biggest_allocs=3
        )
        app = reporter.get_app()

        # WHEN
        async def run_test():
            async with app.run_test() as pilot:
                await pilot.pause()
                tree = app.query_one(Tree)
                return tree.root

        root = async_run(run_test())

        # THEN

        assert tree_to_dict(root) == TreeElement(
            label="📂 1.000KB (100.00 %) <ROOT>",
            children=[
                TreeElement(
                    label="📄 1.000KB (100.00 %) me  foo.py:12",
                    children=[],
                    allow_expand=False,
                    is_expanded=True,
                )
            ],
            allow_expand=True,
            is_expanded=True,
        )

    def test_hide_import_system(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "<frozen importlib>", 12),
                    ("parent", "<frozen importlib>", 8),
                    ("grandparent", "<frozen importlib>", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
        ]

        reporter = TreeReporter.from_snapshot(
            peak_allocations, native_traces=False, biggest_allocs=3
        )
        app = reporter.get_app()

        # WHEN
        async def run_test():
            async with app.run_test() as pilot:
                await pilot.pause()
                tree = app.query_one(Tree)
                first_tree = tree_to_dict(tree.root)
                await pilot.press("i")
                await pilot.pause()
                second_tree = tree_to_dict(tree.root)
                return first_tree, second_tree

        first_tree, second_tree = async_run(run_test())

        # THEN
        assert first_tree == TreeElement(
            label="📂 11.000KB (100.00 %) <ROOT>",
            children=[
                TreeElement(
                    label="📂 10.000KB (90.91 %) grandparent2  fun2.py:4",
                    children=[
                        TreeElement(
                            label="📂 10.000KB (90.91 %) parent2  fun2.py:8",
                            children=[
                                TreeElement(
                                    label="📄 10.000KB (90.91 %) me2  fun2.py:12",
                                    children=[],
                                    allow_expand=False,
                                    is_expanded=True,
                                )
                            ],
                            allow_expand=True,
                            is_expanded=True,
                        )
                    ],
                    allow_expand=True,
                    is_expanded=True,
                )
            ],
            allow_expand=True,
            is_expanded=True,
        )
        assert second_tree == TreeElement(
            label="📂 11.000KB (100.00 %) <ROOT>",
            children=[
                TreeElement(
                    label="📂 10.000KB (90.91 %) grandparent2  fun2.py:4",
                    children=[
                        TreeElement(
                            label="📂 10.000KB (90.91 %) parent2  fun2.py:8",
                            children=[
                                TreeElement(
                                    label="📄 10.000KB (90.91 %) me2  fun2.py:12",
                                    children=[],
                                    allow_expand=False,
                                    is_expanded=True,
                                )
                            ],
                            allow_expand=True,
                            is_expanded=True,
                        )
                    ],
                    allow_expand=True,
                    is_expanded=True,
                )
            ],
            allow_expand=True,
            is_expanded=True,
        )

    def test_hide_import_system_idempotency(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "<frozen importlib>", 12),
                    ("parent", "<frozen importlib>", 8),
                    ("grandparent", "<frozen importlib>", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
        ]

        reporter = TreeReporter.from_snapshot(
            peak_allocations, native_traces=False, biggest_allocs=3
        )
        app = reporter.get_app()

        # WHEN
        async def run_test():
            async with app.run_test() as pilot:
                await pilot.pause()
                tree = app.query_one(Tree)
                first_tree = tree_to_dict(tree.root)
                await pilot.press("i")
                await pilot.pause()
                await pilot.press("i")
                await pilot.pause()
                second_tree = tree_to_dict(tree.root)
                return first_tree, second_tree

        first_tree, second_tree = async_run(run_test())

        # THEN
        assert first_tree == second_tree

    def test_expand_linear_chain(self):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
        ]

        reporter = TreeReporter.from_snapshot(
            peak_allocations, native_traces=False, biggest_allocs=3
        )
        app = reporter.get_app()

        # WHEN
        async def run_test():
            async with app.run_test() as pilot:
                await pilot.pause()
                tree = app.query_one(Tree)
                child = tree.root.children[1]
                # From Textual 0.73 on, Tree.select_node toggles the node's expanded
                # state. The new Tree.move_cursor method selects without expanding.
                getattr(tree, "move_cursor", tree.select_node)(child)
                await pilot.press("e")
                await pilot.pause()
                return tree.root

        root = async_run(run_test())

        # THEN
        assert tree_to_dict(root) == TreeElement(
            label="📂 11.000KB (100.00 %) <ROOT>",
            children=[
                TreeElement(
                    label="📂 10.000KB (90.91 %) grandparent2  fun2.py:4",
                    children=[
                        TreeElement(
                            label="📂 10.000KB (90.91 %) parent2  fun2.py:8",
                            children=[
                                TreeElement(
                                    label="📄 10.000KB (90.91 %) me2  fun2.py:12",
                                    children=[],
                                    allow_expand=False,
                                    is_expanded=True,
                                )
                            ],
                            allow_expand=True,
                            is_expanded=True,
                        )
                    ],
                    allow_expand=True,
                    is_expanded=True,
                ),
                TreeElement(
                    label="📂 1.000KB (9.09 %) grandparent  fun.py:4",
                    children=[
                        TreeElement(
                            label="📂 1.000KB (9.09 %) parent  fun.py:8",
                            children=[
                                TreeElement(
                                    label="📄 1.000KB (9.09 %) me  fun.py:12",
                                    children=[],
                                    allow_expand=False,
                                    is_expanded=True,
                                )
                            ],
                            allow_expand=True,
                            is_expanded=True,
                        )
                    ],
                    allow_expand=True,
                    is_expanded=True,
                ),
            ],
            allow_expand=True,
            is_expanded=True,
        )

    def test_very_deep_call_is_limited(self):
        # GIVEN
        n_frames = MAX_STACKS + 50
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[(f"func_{i}", "fun.py", i) for i in range(n_frames, 0, -1)],
            ),
        ]

        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)
        app = reporter.get_app()

        # WHEN
        async def run_test():
            async with app.run_test() as pilot:
                await pilot.pause()
                return app.query_one(Tree).root

        root = async_run(run_test())

        assert str(root.label) == "📂 1.000KB (100.00 %) <ROOT>"
        assert len(root.children) == 1
        current_node = root.children[0]
        for i in range(1, MAX_STACKS + 2):
            assert f"func_{i}" in str(current_node.label)
            assert len(current_node.children) == 1
            current_node = current_node.children[0]
        assert not current_node.children

    def test_render_runs_the_app(self):
        # GIVEN
        with patch("memray.reporters.tree.TreeReporter.get_app") as get_app:
            reporter = TreeReporter.from_snapshot([], native_traces=False)
            # WHEN
            reporter.render()

        # THEN
        get_app.return_value.run.assert_called()


@pytest.fixture
def compare(monkeypatch, tmp_path, snap_compare):
    def compare_impl(
        allocations: Iterator[AllocationRecord],
        press: Iterable[str] = (),
        terminal_size: Tuple[int, int] = (120, 60),
        run_before: Optional[Callable[[Pilot], Optional[Awaitable[None]]]] = None,
        native: bool = False,
        biggest_allocs: Optional[int] = None,
    ):
        from_snapshot_kwargs: Dict[str, Any] = {"native_traces": native}
        if biggest_allocs is not None:
            from_snapshot_kwargs["biggest_allocs"] = biggest_allocs
        reporter = TreeReporter.from_snapshot(allocations, **from_snapshot_kwargs)
        app = reporter.get_app()
        tmp_main = tmp_path / "main.py"
        app_global = "_CURRENT_APP_"
        with monkeypatch.context() as app_patch:
            app_patch.setitem(globals(), app_global, app)
            tmp_main.write_text(f"from {__name__} import {app_global} as app")
            return snap_compare(
                str(tmp_main),
                press=press,
                terminal_size=terminal_size,
                run_before=run_before,
            )

    yield compare_impl


class TestTUILooks:
    def test_basic(self, compare):
        # GIVEN
        code = dedent(
            """\
        import itertools
        def generate_primes():
            numbers = itertools.count(2)
            while True:
                prime = next(numbers)
                yield prime
                numbers = filter(lambda x, prime=prime: x % prime, numbers)
        """
        )
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
        ]

        # WHEN / THEN
        with patch("linecache.getlines") as getlines:
            getlines.return_value = code.splitlines()
            assert compare(peak_allocations, press=[])

    def test_basic_node_selected_not_leaf(self, compare):
        # GIVEN
        code = dedent(
            """\
        import itertools
        def generate_primes():
            numbers = itertools.count(2)
            while True:
                prime = next(numbers)
                yield prime
                numbers = filter(lambda x, prime=prime: x % prime, numbers)
        """
        )
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
        ]

        # WHEN / THEN
        with patch("linecache.getlines") as getlines:
            getlines.return_value = code.splitlines()
            assert compare(peak_allocations, press=[*["down"] * 2])

    def test_basic_node_selected_leaf(self, compare):
        # GIVEN
        code = dedent(
            """\
        import itertools
        def generate_primes():
            numbers = itertools.count(2)
            while True:
                prime = next(numbers)
                yield prime
                numbers = filter(lambda x, prime=prime: x % prime, numbers)
        """
        )
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
        ]

        # WHEN / THEN
        with patch("linecache.getlines") as getlines:
            getlines.return_value = code.splitlines()
            assert compare(peak_allocations, press=[*["down"] * 3])

    def test_two_chains(self, compare):
        # GIVEN
        code = dedent(
            """\
        import itertools
        def generate_primes():
            numbers = itertools.count(2)
            while True:
                prime = next(numbers)
                yield prime
                numbers = filter(lambda x, prime=prime: x % prime, numbers)
        """
        )
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me", "fun.py", 12),
                    ("parent", "fun.py", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
        ]

        # WHEN / THEN
        with patch("linecache.getlines") as getlines:
            getlines.return_value = code.splitlines()
            assert compare(peak_allocations, press=[])

    def test_two_chains_after_expanding_second(self, compare):
        # GIVEN
        code = dedent(
            """\
        import itertools
        def generate_primes():
            numbers = itertools.count(2)
            while True:
                prime = next(numbers)
                yield prime
                numbers = filter(lambda x, prime=prime: x % prime, numbers)
        """
        )
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("a", "fun.py", 1),
                    ("b", "fun.py", 2),
                    ("c", "fun.py", 3),
                    ("d", "fun.py", 4),
                    ("e", "fun.py", 5),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
        ]

        # WHEN / THEN
        with patch("linecache.getlines") as getlines:
            getlines.return_value = code.splitlines()
            assert compare(peak_allocations, press=[*["down"] * 4, "e"])

    def test_hide_import_system(self, compare):
        # GIVEN
        code = dedent(
            """\
        import itertools
        def generate_primes():
            numbers = itertools.count(2)
            while True:
                prime = next(numbers)
                yield prime
                numbers = filter(lambda x, prime=prime: x % prime, numbers)
        """
        )
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("a0", "some other frame", 4),
                    ("a", "<frozen importlib>", 1),
                    ("b", "<frozen importlib>", 2),
                    ("c", "<frozen importlib>", 3),
                    ("d", "<frozen importlib>", 4),
                    ("e", "<frozen importlib>", 5),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
        ]

        # WHEN / THEN
        with patch("linecache.getlines") as getlines:
            getlines.return_value = code.splitlines()
            assert compare(peak_allocations, press=["i"])

    def test_show_uninteresting(self, compare):
        # GIVEN
        code = dedent(
            """\
        import itertools
        def generate_primes():
            numbers = itertools.count(2)
            while True:
                prime = next(numbers)
                yield prime
                numbers = filter(lambda x, prime=prime: x % prime, numbers)
        """
        )
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("a0", "some other frame", 4),
                    ("a", "runpy.py", 1),
                    ("b", "runpy.py", 2),
                    ("c", "runpy.py", 3),
                    ("d", "runpy.py", 4),
                    ("e", "runpy.py", 5),
                ],
            ),
        ]

        # WHEN / THEN
        with patch("linecache.getlines") as getlines:
            getlines.return_value = code.splitlines()
            assert compare(peak_allocations, press=["u"])

    def test_show_uninteresting_and_hide_import_system(self, compare):
        # GIVEN
        code = dedent(
            """\
        import itertools
        def generate_primes():
            numbers = itertools.count(2)
            while True:
                prime = next(numbers)
                yield prime
                numbers = filter(lambda x, prime=prime: x % prime, numbers)
        """
        )
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024 * 10,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("B", "some other frame", 4),
                    ("d", "<frozen importlib>", 3),
                    ("e", "<frozen importlib>", 4),
                    ("A", "some other frame", 4),
                    ("a", "runpy.py", 1),
                    ("b", "runpy.py", 2),
                    ("c", "runpy.py", 5),
                ],
            ),
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "fun2.py", 12),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
        ]

        # WHEN / THEN
        with patch("linecache.getlines") as getlines:
            getlines.return_value = code.splitlines()
            assert compare(peak_allocations, press=["u", "i"])

    def test_select_screen(self, tmp_path, compare):
        # GIVEN
        code = dedent(
            """\
        import itertools
        def generate_primes():
            numbers = itertools.count(2)
            while True:
                prime = next(numbers)
                yield prime
                numbers = filter(lambda x, prime=prime: x % prime, numbers)
        """
        )
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("me2", "func2.py", 4),
                    ("parent2", "fun2.py", 8),
                    ("grandparent2", "fun2.py", 4),
                ],
            ),
        ]
        # WHEN / THEN
        with patch("linecache.getlines") as getlines:
            getlines.return_value = code.splitlines()
            assert compare(peak_allocations, press=[*["down"] * 3])

    def test_allocations_of_different_sizes(self, compare):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=65,
                allocator=AllocatorType.MALLOC,
                stack_id=j,
                n_allocations=1,
                _stack=[(f"func{i}", f"fun{i}.py", i) for i in range(1, 51)][:j][::-1],
            )
            for j in range(1, 51)
        ]

        # WHEN / THEN
        with patch("linecache.getlines") as getlines:
            getlines.return_value = []
            assert compare(peak_allocations, press=[], terminal_size=(350, 100))

    def test_biggest_allocations(self, compare):
        # GIVEN
        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=index * 1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    (f"function_{index}", "fun.py", 12),
                ],
            )
            for index in range(1000)
        ]

        # WHEN / THEN
        with patch("linecache.getlines") as getlines:
            getlines.return_value = []
            assert compare(
                peak_allocations,
                press=["end"],
                biggest_allocs=10,
                terminal_size=(200, 40),
            )
