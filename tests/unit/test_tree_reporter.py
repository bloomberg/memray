import sys
from io import StringIO

from memray import AllocatorType
from memray.reporters.tree import MAX_STACKS
from memray.reporters.tree import ROOT_NODE
from memray.reporters.tree import Frame
from memray.reporters.tree import TreeReporter
from tests.utils import MockAllocationRecord


class TestCollapseTree:
    def test_single_node(self):
        location_1 = ("A", "A", 1)
        node_1 = Frame(location=location_1, value=10, children={})

        # WHEN

        tree = node_1.collapse_tree()

        # THEN

        assert tree == Frame(
            location=("A", "A", 1),
            value=10,
            children={},
            n_allocations=0,
            thread_id="",
            interesting=True,
            group=[],
        )

    def test_many_nodes(self):
        # GIVEN
        location_1 = ("A", "A", 1)
        node_1 = Frame(location=location_1, value=10, children={})
        location_2 = ("B", "B", 1)
        node_2 = Frame(location=location_2, value=10, children={})
        location_3 = ("C", "C", 1)
        node_3 = Frame(location=location_3, value=10, children={})
        root = Frame(
            location=("<ROOT>", "", 0),
            value=10,
            children={location_1: node_1, location_2: node_2, location_3: node_3},
        )
        # WHEN

        tree = root.collapse_tree()

        # THEN

        assert tree.location == ("<ROOT>", "", 0)
        assert tree.value == 10
        assert [node.location for node in tree.children.values()] == [
            location_1,
            location_2,
            location_3,
        ]
        assert tree.group == []

    def test_collapse_line(self):
        # GIVEN

        location_1 = ("A", "A", 1)
        node_1 = Frame(location=location_1, value=10, children={})
        location_2 = ("B", "B", 1)
        node_2 = Frame(location=location_2, value=10, children={location_1: node_1})
        location_3 = ("C", "C", 1)
        node_3 = Frame(location=location_3, value=10, children={location_2: node_2})
        # WHEN

        tree = node_3.collapse_tree()

        # THEN

        assert tree.location == location_1
        assert tree.value == 10
        assert tree.children == {}
        assert tree.group == [node_2, node_3]

    def test_root_is_not_collapsed(self):
        # GIVEN

        location_1 = ("A", "A", 1)
        node_1 = Frame(location=location_1, value=10, children={})
        location_2 = ("B", "B", 1)
        node_2 = Frame(location=location_2, value=10, children={location_1: node_1})
        location_3 = ("C", "C", 1)
        node_3 = Frame(location=location_3, value=10, children={location_2: node_2})
        root = Frame(location=ROOT_NODE, value=10, children={location_3: node_3})
        # WHEN

        tree = root.collapse_tree()

        # THEN

        assert tree.location == ROOT_NODE
        assert tree.value == 10
        assert len(tree.children) == 1
        assert not tree.group

        (child,) = tree.children.values()
        assert child.location == location_1
        assert child.group == [node_2, node_3]
        assert child.value == 10

    def test_collapse_line_with_branching_root(self):
        # GIVEN

        location_1 = ("A", "A", 1)
        node_1 = Frame(location=location_1, value=10, children={})
        location_2 = ("B", "B", 1)
        node_2 = Frame(location=location_2, value=10, children={location_1: node_1})
        location_3 = ("C", "C", 1)
        node_3 = Frame(location=location_3, value=10, children={location_2: node_2})
        location_4 = ("D", "D", 1)
        node_4 = Frame(location=location_4, value=10, children={})
        root = Frame(
            location=("<ROOT>", "", 0),
            value=10,
            children={location_3: node_3, location_4: node_4},
        )
        # WHEN

        tree = root.collapse_tree()

        # THEN

        assert tree.location == ("<ROOT>", "", 0)
        assert tree.value == 10
        assert len(tree.children) == 2
        assert tree.group == []
        assert [node.location for node in tree.children.values()] == [
            location_1,
            location_4,
        ]

        branch1, branch2 = tree.children.values()
        assert branch1.location == location_1
        assert branch1.value == 10
        assert branch1.children == {}
        assert branch1.group == [node_2, node_3]

        assert branch2.location == location_4
        assert branch2.value == 10
        assert branch2.children == {}
        assert branch2.group == []

    def test_no_lines(self):
        location_1 = ("A", "A", 1)
        node_1 = Frame(location=location_1, value=10, children={})
        location_2 = ("B", "B", 1)
        node_2 = Frame(location=location_2, value=10, children={})
        location_3 = ("C", "C", 1)
        node_3 = Frame(
            location=location_3,
            value=10,
            children={location_1: node_1, location_2: node_2},
        )
        location_4 = ("D", "D", 1)
        node_4 = Frame(location=location_4, value=10, children={})
        root = Frame(
            location=("<ROOT>", "", 0),
            value=10,
            children={location_3: node_3, location_4: node_4},
        )
        # WHEN

        tree = root.collapse_tree()

        # THEN

        assert tree.location == ("<ROOT>", "", 0)
        assert tree.value == 10
        assert len(tree.children) == 2
        assert tree.group == []
        assert [node.location for node in tree.children.values()] == [
            location_3,
            location_4,
        ]

        branch1, branch2 = tree.children.values()
        assert branch1.location == location_3
        assert branch1.value == 10
        assert [node.location for node in branch1.children.values()] == [
            location_1,
            location_2,
        ]

        assert branch2.location == location_4
        assert branch2.value == 10
        assert branch2.children == {}
        assert branch2.group == []

    def test_two_lines(self):
        location_a1 = ("A1", "A1", 1)
        node_a1 = Frame(location=location_a1, value=10, children={})
        location_a2 = ("B1", "B1", 1)
        node_a2 = Frame(location=location_a2, value=10, children={location_a1: node_a1})
        location_a3 = ("C1", "C1", 1)
        node_a3 = Frame(location=location_a3, value=10, children={location_a2: node_a2})
        location_b1 = ("A2", "A2", 1)
        node_b1 = Frame(location=location_b1, value=10, children={})
        location_b2 = ("B2", "B2", 1)
        node_b2 = Frame(location=location_b2, value=10, children={location_b1: node_b1})
        location_b3 = ("C2", "C2", 1)
        node_b3 = Frame(location=location_b3, value=10, children={location_b2: node_b2})
        root = Frame(
            location=("<ROOT>", "", 0),
            value=10,
            children={location_a3: node_a3, location_b3: node_b3},
        )

        # WHEN

        tree = root.collapse_tree()

        # THEN

        assert tree.location == ("<ROOT>", "", 0)
        assert tree.value == 10
        assert [node.location for node in tree.children.values()] == [
            location_a1,
            location_b1,
        ]
        assert tree.group == []

        branch1, branch2 = tree.children.values()
        assert branch1.location == location_a1
        assert branch1.value == 10
        assert branch1.children == {}
        assert branch1.group == [node_a2, node_a3]

        assert branch2.location == location_b1
        assert branch2.value == 10
        assert branch2.children == {}
        assert branch2.group == [node_b2, node_b3]


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
            group=[],
        )

    def test_biggest_allocations(self):
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

        # WHEN
        reporter = TreeReporter.from_snapshot(
            peak_allocations, native_traces=False, biggest_allocs=3
        )

        # THEN
        assert reporter.data == Frame(
            location=("<ROOT>", "", 0),
            value=3065856,
            children={
                ("function_999", "fun.py", 12): Frame(
                    location=("function_999", "fun.py", 12),
                    value=1022976,
                    children={},
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    group=[],
                ),
                ("function_998", "fun.py", 12): Frame(
                    location=("function_998", "fun.py", 12),
                    value=1021952,
                    children={},
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    group=[],
                ),
                ("function_997", "fun.py", 12): Frame(
                    location=("function_997", "fun.py", 12),
                    value=1020928,
                    children={},
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    group=[],
                ),
            },
            n_allocations=3,
            thread_id="",
            interesting=True,
            group=[],
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
                    location=("me", "fun.py", 12),
                    value=1024,
                    children={},
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    group=[
                        Frame(
                            location=("parent", "fun.py", 8),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                        Frame(
                            location=("grandparent", "fun.py", 4),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                    ],
                )
            },
            n_allocations=1,
            thread_id="",
            interesting=True,
            group=[],
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
                    location=("me", "fun.py", 12),
                    value=1024,
                    children={},
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    group=[
                        Frame(
                            location=("parent", "fun.pyx", 8),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                        Frame(
                            location=("grandparent", "fun.c", 4),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                    ],
                )
            },
            n_allocations=1,
            thread_id="",
            interesting=True,
            group=[],
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
                            group=[],
                        ),
                        ("sibling", "fun.py", 16): Frame(
                            location=("sibling", "fun.py", 16),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                    },
                    n_allocations=2,
                    thread_id="0x1",
                    interesting=True,
                    group=[
                        Frame(
                            location=("grandparent", "fun.py", 4),
                            value=2048,
                            children={},
                            n_allocations=2,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        )
                    ],
                )
            },
            n_allocations=2,
            thread_id="",
            interesting=True,
            group=[],
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
                            location=("me", "fun.py", 12),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[
                                Frame(
                                    location=("parent_one", "fun.py", 8),
                                    value=1024,
                                    children={},
                                    n_allocations=1,
                                    thread_id="0x1",
                                    interesting=True,
                                    group=[],
                                )
                            ],
                        ),
                        ("parent_two", "fun.py", 10): Frame(
                            location=("sibling", "fun.py", 16),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[
                                Frame(
                                    location=("parent_two", "fun.py", 10),
                                    value=1024,
                                    children={},
                                    n_allocations=1,
                                    thread_id="0x1",
                                    interesting=True,
                                    group=[],
                                )
                            ],
                        ),
                    },
                    n_allocations=2,
                    thread_id="0x1",
                    interesting=True,
                    group=[],
                )
            },
            n_allocations=2,
            thread_id="",
            interesting=True,
            group=[],
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
                    location=("one", "recursive.py", 9),
                    value=1024,
                    children={},
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    group=[
                        Frame(
                            location=("two", "recursive.py", 20),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                        Frame(
                            location=("one", "recursive.py", 10),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                        Frame(
                            location=("two", "recursive.py", 20),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                        Frame(
                            location=("one", "recursive.py", 10),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                        Frame(
                            location=("two", "recursive.py", 20),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                        Frame(
                            location=("main", "recursive.py", 5),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                    ],
                )
            },
            n_allocations=1,
            thread_id="",
            interesting=True,
            group=[],
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
                    location=("baz2", "/src/lel.py", 18),
                    value=1024,
                    children={},
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    group=[
                        Frame(
                            location=("bar2", "/src/lel.py", 15),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                        Frame(
                            location=("foo2", "/src/lel.py", 12),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                    ],
                ),
                ("foo1", "/src/lel.py", 2): Frame(
                    location=("baz1", "/src/lel.py", 8),
                    value=1024,
                    children={},
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    group=[
                        Frame(
                            location=("bar1", "/src/lel.py", 5),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                        Frame(
                            location=("foo1", "/src/lel.py", 2),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        ),
                    ],
                ),
            },
            n_allocations=2,
            thread_id="",
            interesting=True,
            group=[],
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
                    location=("baz2", "/src/lel.py", 18),
                    value=2048,
                    children={},
                    n_allocations=2,
                    thread_id="0x2",
                    interesting=True,
                    group=[
                        Frame(
                            location=("bar2", "/src/lel.py", 15),
                            value=2048,
                            children={},
                            n_allocations=2,
                            thread_id="0x2",
                            interesting=True,
                            group=[],
                        ),
                        Frame(
                            location=("foo2", "/src/lel.py", 12),
                            value=2048,
                            children={},
                            n_allocations=2,
                            thread_id="0x2",
                            interesting=True,
                            group=[],
                        ),
                    ],
                )
            },
            n_allocations=2,
            thread_id="",
            interesting=True,
            group=[],
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
                    location=("baz2", "/src/lel.py", 18),
                    value=2048,
                    children={},
                    n_allocations=2,
                    thread_id="merged thread",
                    interesting=True,
                    group=[
                        Frame(
                            location=("bar2", "/src/lel.py", 15),
                            value=2048,
                            children={},
                            n_allocations=2,
                            thread_id="merged thread",
                            interesting=True,
                            group=[],
                        ),
                        Frame(
                            location=("foo2", "/src/lel.py", 12),
                            value=2048,
                            children={},
                            n_allocations=2,
                            thread_id="merged thread",
                            interesting=True,
                            group=[],
                        ),
                    ],
                )
            },
            n_allocations=2,
            thread_id="",
            interesting=True,
            group=[],
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
                    location=("me", "fun.py", 12),
                    value=1024,
                    children={},
                    n_allocations=1,
                    thread_id="0x1",
                    interesting=True,
                    group=[
                        Frame(
                            location=("parent", "fun.py", 8),
                            value=1024,
                            children={},
                            n_allocations=1,
                            thread_id="0x1",
                            interesting=True,
                            group=[],
                        )
                    ],
                )
            },
            n_allocations=1,
            thread_id="",
            interesting=True,
            group=[],
        )

    def test_very_deep_call_is_limited(self):
        # GIVEN
        n_frames = sys.getrecursionlimit() * 2
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

        # WHEN
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)

        # THEN
        assert reporter.data.location == ("<ROOT>", "", 0)
        assert len(reporter.data.children) == 1
        (branch,) = reporter.data.children.values()
        collapsed_nodes = branch.group
        assert len(collapsed_nodes) == MAX_STACKS + 1
        for index, frame in enumerate(reversed(collapsed_nodes), start=1):
            assert frame.location == (
                f"func_{index}",
                "fun.py",
                index,
            )


class TestRenderFrame:
    def test_render_no_data(self):
        # GIVEN
        reporter = TreeReporter.from_snapshot([], native_traces=False)
        output = StringIO()

        # WHEN
        reporter.render(file=output)

        # THEN
        assert output.getvalue().strip() == "<No allocations>"

    def test_render_one_allocation(self):
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
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)
        output = StringIO()

        # WHEN
        reporter.render(file=output)

        # THEN
        expected = [
            "📂 1.000KB (100.00 %) <ROOT>",
            "└── [[2 frames hidden in 1 file(s)]]",
            "    └── 📄 1.000KB (100.00 %) me  fun.py:12",
        ]
        assert [line.rstrip() for line in output.getvalue().splitlines()] == expected

    def test_render_multiple_allocations_in_same_branch(self):
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
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)
        output = StringIO()

        # WHEN
        reporter.render(file=output)

        # THEN
        expected = [
            "📂 2.000KB (100.00 %) <ROOT>",
            "└── [[1 frames hidden in 1 file(s)]]",
            "    └── 📂 2.000KB (100.00 %) parent  fun.py:8",
            "        ├── 📄 1.000KB (50.00 %) me  fun.py:12",
            "        └── 📄 1.000KB (50.00 %) sibling  fun.py:16",
        ]
        assert [line.rstrip() for line in output.getvalue().splitlines()] == expected

    def test_render_multiple_allocations_in_diferent_branches(self):
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
                    ("me2", "fun.py", 16),
                    ("parent2", "fun.py", 8),
                    ("grandparent2", "fun.py", 4),
                ],
            ),
        ]
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)
        output = StringIO()

        # WHEN
        reporter.render(file=output)

        # THEN
        expected = [
            "📂 2.000KB (100.00 %) <ROOT>",
            "├── [[2 frames hidden in 1 file(s)]]",
            "│   └── 📄 1.000KB (50.00 %) me  fun.py:12",
            "└── [[2 frames hidden in 1 file(s)]]",
            "    └── 📄 1.000KB (50.00 %) me2  fun.py:16",
        ]
        assert [line.rstrip() for line in output.getvalue().splitlines()] == expected

    def test_render_multiple_allocations_with_no_single_childs(self):
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
                    ("me2", "fun.py", 16),
                    ("parent", "fun.py", 8),
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
                    ("me", "fun.py", 16),
                    ("parent2", "fun.py", 8),
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
                    ("me2", "fun.py", 16),
                    ("parent2", "fun.py", 8),
                ],
            ),
        ]
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)
        output = StringIO()

        # WHEN
        reporter.render(file=output)

        # THEN
        expected = [
            "📂 4.000KB (100.00 %) <ROOT>",
            "├── 📂 2.000KB (50.00 %) parent  fun.py:8",
            "│   ├── 📄 1.000KB (25.00 %) me  fun.py:12",
            "│   └── 📄 1.000KB (25.00 %) me2  fun.py:16",
            "└── 📂 2.000KB (50.00 %) parent2  fun.py:8",
            "    ├── 📄 1.000KB (25.00 %) me  fun.py:16",
            "    └── 📄 1.000KB (25.00 %) me2  fun.py:16",
        ]
        assert [line.rstrip() for line in output.getvalue().splitlines()] == expected

    def test_render_long_chain(self):
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
                    ("a", "fun.py", 1),
                    ("b", "fun.py", 9),
                    ("c", "fun.py", 10),
                    ("d", "fun.py", 11),
                    ("e", "fun.py", 11),
                    ("f", "fun.py", 11),
                ],
            ),
        ]
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)
        output = StringIO()

        # WHEN
        reporter.render(file=output)

        # THEN
        expected = [
            "📂 1.000KB (100.00 %) <ROOT>",
            "└── [[5 frames hidden in 1 file(s)]]",
            "    └── 📄 1.000KB (100.00 %) a  fun.py:1",
        ]
        assert [line.rstrip() for line in output.getvalue().splitlines()] == expected

    def test_render_long_chain_with_branch_at_the_end(self):
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
                    ("a1", "fun.py", 1),
                    ("b", "fun2.py", 9),
                    ("c", "fun3.py", 10),
                    ("d", "fun4.py", 11),
                    ("e", "fun5.py", 11),
                    ("f", "fun6.py", 11),
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
                    ("a2", "fun.py", 1),
                    ("b", "fun2.py", 9),
                    ("c", "fun3.py", 10),
                    ("d", "fun4.py", 11),
                    ("e", "fun5.py", 11),
                    ("f", "fun6.py", 11),
                ],
            ),
        ]
        reporter = TreeReporter.from_snapshot(peak_allocations, native_traces=False)
        output = StringIO()

        # WHEN
        reporter.render(file=output)

        # THEN
        expected = [
            "📂 2.000KB (100.00 %) <ROOT>",
            "└── [[4 frames hidden in 4 file(s)]]",
            "    └── 📂 2.000KB (100.00 %) b  fun2.py:9",
            "        ├── 📄 1.000KB (50.00 %) a1  fun.py:1",
            "        └── 📄 1.000KB (50.00 %) a2  fun.py:1",
        ]
        assert [line.rstrip() for line in output.getvalue().splitlines()] == expected
