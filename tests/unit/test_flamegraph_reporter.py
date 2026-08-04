import os
import sys

from memray import AllocatorType
from memray import FileReader
from memray import Tracker
from memray._test import MemoryAllocator
from memray.reporters.flamegraph import MAX_STACKS
from memray.reporters.flamegraph import FlameGraphReporter
from tests.utils import MockAllocationRecord
from tests.utils import filter_relevant_allocations


def packed_data_to_tree(packed_data):
    """Python implementation of packedDataToTree in flamegraph.js"""
    strings, nodes, unique_threads = (
        packed_data["strings"],
        packed_data["nodes"],
        packed_data["unique_threads"],
    )

    if not len(nodes):
        return {}

    node_objects = [
        {
            "name": strings[nodes["name"][i]],
            "location": [
                strings[nodes["function"][i]],
                strings[nodes["filename"][i]],
                nodes["lineno"][i],
            ],
            "value": nodes["value"][i],
            "children": nodes["children"][i],
            "n_allocations": nodes["n_allocations"][i],
            "thread_id": strings[nodes["thread_id"][i]],
            "interesting": nodes["interesting"][i] != 0,
            "import_system": nodes["import_system"][i] != 0,
        }
        for i in range(len(nodes["name"]))
    ]

    for node in node_objects:
        node["children"] = [node_objects[idx] for idx in node["children"]]

    root = node_objects[0]
    root["unique_threads"] = [strings[tid] for tid in unique_threads]
    return root


def get_packed_trees(packed_data):
    strings, nodes, inverted_no_imports_nodes, unique_threads = (
        packed_data["strings"],
        packed_data["nodes"],
        packed_data["inverted_no_imports_nodes"],
        packed_data["unique_threads"],
    )

    root = packed_data_to_tree(
        {"nodes": nodes, "strings": strings, "unique_threads": unique_threads}
    )
    root_inverted_import_system = packed_data_to_tree(
        {
            "nodes": inverted_no_imports_nodes,
            "strings": strings,
            "unique_threads": unique_threads,
        }
    )

    return [root, root_inverted_import_system]


class TestFlameGraphReporter:
    def test_works_with_no_allocations(self):
        reporter = FlameGraphReporter.from_snapshot(
            [], memory_records=[], native_traces=False
        )
        tree, inverted_import_system_tree = get_packed_trees(reporter.data)
        assert inverted_import_system_tree == {}
        assert tree["name"] == "<root>"
        assert tree["value"] == 0
        assert tree["children"] == []

    def test_inverted_works_with_no_allocations(self):
        reporter = FlameGraphReporter.from_snapshot(
            [], memory_records=[], native_traces=False, inverted=True
        )
        tree, inverted_import_system_tree = get_packed_trees(reporter.data)
        assert tree["name"] == "<root>"
        assert tree["value"] == 0
        assert tree["children"] == []
        assert tree == inverted_import_system_tree

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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}

        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "unique_threads": ["0x1"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "grandparent at fun.py:4",
                    "thread_id": "0x1",
                    "location": ["grandparent", "fun.py", 4],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent at fun.py:8",
                            "thread_id": "0x1",
                            "location": ["parent", "fun.py", 8],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "me at fun.py:12",
                                    "thread_id": "0x1",
                                    "location": ["me", "fun.py", 12],
                                    "value": 1024,
                                    "children": [],
                                    "interesting": True,
                                    "import_system": False,
                                    "n_allocations": 1,
                                }
                            ],
                        }
                    ],
                }
            ],
        } == tree

    def test_inverted_works_with_single_call(self):
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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "unique_threads": ["0x1"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "me at fun.py:12",
                    "thread_id": "0x1",
                    "location": ["me", "fun.py", 12],
                    "value": 1024,
                    "interesting": True,
                    "import_system": False,
                    "n_allocations": 1,
                    "children": [
                        {
                            "name": "parent at fun.py:8",
                            "thread_id": "0x1",
                            "location": ["parent", "fun.py", 8],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "grandparent at fun.py:4",
                                    "thread_id": "0x1",
                                    "location": ["grandparent", "fun.py", 4],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        } == tree

        assert tree == inverted_import_system_tree

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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "unique_threads": ["0x1"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "grandparent at fun.c:4",
                    "thread_id": "0x1",
                    "location": ["grandparent", "fun.c", 4],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent at fun.pyx:8",
                            "thread_id": "0x1",
                            "location": ["parent", "fun.pyx", 8],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "me at fun.py:12",
                                    "thread_id": "0x1",
                                    "location": ["me", "fun.py", 12],
                                    "value": 1024,
                                    "children": [],
                                    "interesting": True,
                                    "import_system": False,
                                    "n_allocations": 1,
                                }
                            ],
                        }
                    ],
                }
            ],
        } == tree

    def test_inverted_uses_hybrid_stack_for_native_traces(self):
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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=True, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "unique_threads": ["0x1"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "me at fun.py:12",
                    "thread_id": "0x1",
                    "location": ["me", "fun.py", 12],
                    "value": 1024,
                    "interesting": True,
                    "import_system": False,
                    "n_allocations": 1,
                    "children": [
                        {
                            "name": "parent at fun.pyx:8",
                            "thread_id": "0x1",
                            "location": ["parent", "fun.pyx", 8],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "grandparent at fun.c:4",
                                    "thread_id": "0x1",
                                    "location": ["grandparent", "fun.c", 4],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        } == tree

        assert inverted_import_system_tree == tree

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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "unique_threads": ["0x1"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "grandparent at fun.py:4",
                    "thread_id": "0x1",
                    "location": ["grandparent", "fun.py", 4],
                    "value": 2048,
                    "n_allocations": 2,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent at fun.py:8",
                            "thread_id": "0x1",
                            "location": ["parent", "fun.py", 8],
                            "value": 2048,
                            "n_allocations": 2,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "me at fun.py:12",
                                    "thread_id": "0x1",
                                    "location": ["me", "fun.py", 12],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                },
                                {
                                    "name": "sibling at fun.py:16",
                                    "thread_id": "0x1",
                                    "location": ["sibling", "fun.py", 16],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                },
                            ],
                        }
                    ],
                }
            ],
        } == tree

    def test_sanity_check_with_real_allocations(self, tmp_path):
        # GIVEN
        allocator = MemoryAllocator()
        output = tmp_path / "test.bin"
        with Tracker(output):
            allocator.valloc(4096)
            allocator.free()

        peak_allocations = filter_relevant_allocations(
            FileReader(output).get_high_watermark_allocation_records()
        )

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert tree["name"] == "<root>"
        assert tree["value"] == 4096

        assert isinstance(tree["children"], list)
        assert len(tree["children"]) == 1

        child = tree["children"][0]
        assert child["name"] == "            allocator.valloc(4096)\n"

    def test_inverted_sanity_check_with_real_allocations(self, tmp_path):
        # GIVEN
        allocator = MemoryAllocator()

        output = tmp_path / "test.bin"

        with Tracker(output):
            allocator.valloc(4096)

            allocator.free()

        peak_allocations = filter_relevant_allocations(
            FileReader(output).get_high_watermark_allocation_records()
        )

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert tree == inverted_import_system_tree
        assert tree["name"] == "<root>"
        assert tree["value"] == 4096
        assert isinstance(tree["children"], list)
        assert len(tree["children"]) == 1
        child = tree["children"][0]
        assert child["name"] == "        return self.allocator.valloc(size)\n"
        assert len(child["children"]) == 1
        assert child["children"][0]["name"] == "            allocator.valloc(4096)\n"

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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "unique_threads": ["0x1"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "grandparent at fun.py:4",
                    "thread_id": "0x1",
                    "location": ["grandparent", "fun.py", 4],
                    "value": 2048,
                    "n_allocations": 2,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent_one at fun.py:8",
                            "thread_id": "0x1",
                            "location": ["parent_one", "fun.py", 8],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "me at fun.py:12",
                                    "thread_id": "0x1",
                                    "location": ["me", "fun.py", 12],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        },
                        {
                            "name": "parent_two at fun.py:10",
                            "thread_id": "0x1",
                            "location": ["parent_two", "fun.py", 10],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "sibling at fun.py:16",
                                    "thread_id": "0x1",
                                    "location": ["sibling", "fun.py", 16],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        },
                    ],
                }
            ],
        } == tree

    def test_inverted_works_with_multiple_stacks_from_same_caller_two_frames_above(
        self,
    ):
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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert tree == inverted_import_system_tree
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "unique_threads": ["0x1"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "me at fun.py:12",
                    "thread_id": "0x1",
                    "location": ["me", "fun.py", 12],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent_one at fun.py:8",
                            "thread_id": "0x1",
                            "location": ["parent_one", "fun.py", 8],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "grandparent at fun.py:4",
                                    "thread_id": "0x1",
                                    "location": ["grandparent", "fun.py", 4],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "sibling at fun.py:16",
                    "thread_id": "0x1",
                    "location": ["sibling", "fun.py", 16],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent_two at fun.py:10",
                            "thread_id": "0x1",
                            "location": ["parent_two", "fun.py", 10],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "grandparent at fun.py:4",
                                    "thread_id": "0x1",
                                    "location": ["grandparent", "fun.py", 4],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            ],
        } == tree

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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "unique_threads": ["0x1"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "main at recursive.py:5",
                    "thread_id": "0x1",
                    "location": ["main", "recursive.py", 5],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "two at recursive.py:20",
                            "thread_id": "0x1",
                            "location": ["two", "recursive.py", 20],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "one at recursive.py:10",
                                    "thread_id": "0x1",
                                    "location": ["one", "recursive.py", 10],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [
                                        {
                                            "name": "two at recursive.py:20",
                                            "thread_id": "0x1",
                                            "location": ["two", "recursive.py", 20],
                                            "value": 1024,
                                            "n_allocations": 1,
                                            "interesting": True,
                                            "import_system": False,
                                            "children": [
                                                {
                                                    "name": "one at recursive.py:10",
                                                    "thread_id": "0x1",
                                                    "location": [
                                                        "one",
                                                        "recursive.py",
                                                        10,
                                                    ],
                                                    "value": 1024,
                                                    "n_allocations": 1,
                                                    "interesting": True,
                                                    "import_system": False,
                                                    "children": [
                                                        {
                                                            "name": "two at recursive.py:20",  # noqa
                                                            "thread_id": "0x1",
                                                            "location": [
                                                                "two",
                                                                "recursive.py",
                                                                20,
                                                            ],
                                                            "value": 1024,
                                                            "n_allocations": 1,
                                                            "interesting": True,
                                                            "import_system": False,
                                                            "children": [
                                                                {
                                                                    "name": "one at recursive.py:9",  # noqa
                                                                    "thread_id": "0x1",
                                                                    "location": [
                                                                        "one",
                                                                        "recursive.py",
                                                                        9,
                                                                    ],
                                                                    "value": 1024,
                                                                    "n_allocations": 1,
                                                                    "interesting": True,
                                                                    "import_system": False,
                                                                    "children": [],
                                                                }
                                                            ],
                                                        }
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        } == tree

    def test_inverted_works_with_recursive_calls(self):
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

        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert tree == inverted_import_system_tree
        grandchildren = [
            {
                "name": "two at recursive.py:20",
                "location": ["two", "recursive.py", 20],
                "value": 1024,
                "n_allocations": 1,
                "thread_id": "0x1",
                "interesting": True,
                "import_system": False,
                "children": [
                    {
                        "name": "one at recursive.py:10",
                        "location": ["one", "recursive.py", 10],
                        "value": 1024,
                        "n_allocations": 1,
                        "thread_id": "0x1",
                        "interesting": True,
                        "import_system": False,
                        "children": [
                            {
                                "name": "two at recursive.py:20",
                                "location": ["two", "recursive.py", 20],
                                "value": 1024,
                                "n_allocations": 1,
                                "thread_id": "0x1",
                                "interesting": True,
                                "import_system": False,
                                "children": [
                                    {
                                        "name": "one at recursive.py:10",
                                        "location": [
                                            "one",
                                            "recursive.py",
                                            10,
                                        ],
                                        "value": 1024,
                                        "n_allocations": 1,
                                        "thread_id": "0x1",
                                        "interesting": True,
                                        "import_system": False,
                                        "children": [
                                            {
                                                "name": "two at recursive.py:20",
                                                "location": [
                                                    "two",
                                                    "recursive.py",
                                                    20,
                                                ],
                                                "value": 1024,
                                                "n_allocations": 1,
                                                "thread_id": "0x1",
                                                "interesting": True,
                                                "import_system": False,
                                                "children": [
                                                    {
                                                        "name": "main at recursive.py:5",
                                                        "location": [
                                                            "main",
                                                            "recursive.py",
                                                            5,
                                                        ],
                                                        "value": 1024,
                                                        "children": [],
                                                        "n_allocations": 1,
                                                        "thread_id": "0x1",
                                                        "interesting": True,
                                                        "import_system": False,
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        children = [
            {
                "name": "one at recursive.py:9",
                "location": ["one", "recursive.py", 9],
                "value": 1024,
                "n_allocations": 1,
                "thread_id": "0x1",
                "interesting": True,
                "import_system": False,
                "children": grandchildren,
            }
        ]
        assert {
            "name": "<root>",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
            "unique_threads": ["0x1"],
            "children": children,
        } == tree

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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "unique_threads": ["0x1"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "foo2 at /src/lel.py:12",
                    "thread_id": "0x1",
                    "location": ["foo2", "/src/lel.py", 12],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "bar2 at /src/lel.py:15",
                            "thread_id": "0x1",
                            "location": ["bar2", "/src/lel.py", 15],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "baz2 at /src/lel.py:18",
                                    "thread_id": "0x1",
                                    "location": ["baz2", "/src/lel.py", 18],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "foo1 at /src/lel.py:2",
                    "thread_id": "0x1",
                    "location": ["foo1", "/src/lel.py", 2],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "bar1 at /src/lel.py:5",
                            "thread_id": "0x1",
                            "location": ["bar1", "/src/lel.py", 5],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "baz1 at /src/lel.py:8",
                                    "thread_id": "0x1",
                                    "location": ["baz1", "/src/lel.py", 8],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            ],
        } == tree

    def test_inverted_works_with_multiple_top_level_nodes_with_merge(self):
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
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=[
                    ("baz1", "/src/lel.py", 8),
                    ("bar2", "/src/lel.py", 10),
                    ("foo2", "/src/lel.py", 14),
                ],
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert tree == inverted_import_system_tree
        assert {
            "name": "<root>",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 3072,
            "n_allocations": 3,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
            "unique_threads": ["0x1"],
            "children": [
                {
                    "name": "baz2 at /src/lel.py:18",
                    "location": ["baz2", "/src/lel.py", 18],
                    "value": 1024,
                    "n_allocations": 1,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "bar2 at /src/lel.py:15",
                            "location": ["bar2", "/src/lel.py", 15],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "foo2 at /src/lel.py:12",
                                    "location": ["foo2", "/src/lel.py", 12],
                                    "value": 1024,
                                    "children": [],
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": True,
                                    "import_system": False,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "baz1 at /src/lel.py:8",
                    "location": ["baz1", "/src/lel.py", 8],
                    "value": 2048,
                    "n_allocations": 2,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "bar1 at /src/lel.py:5",
                            "location": ["bar1", "/src/lel.py", 5],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "foo1 at /src/lel.py:2",
                                    "location": ["foo1", "/src/lel.py", 2],
                                    "value": 1024,
                                    "children": [],
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": True,
                                    "import_system": False,
                                }
                            ],
                        },
                        {
                            "name": "bar2 at /src/lel.py:10",
                            "location": ["bar2", "/src/lel.py", 10],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "foo2 at /src/lel.py:14",
                                    "location": ["foo2", "/src/lel.py", 14],
                                    "value": 1024,
                                    "children": [],
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": True,
                                    "import_system": False,
                                }
                            ],
                        },
                    ],
                },
            ],
        } == tree

    def test_inverted_works_with_one_top_level_node(self):
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
                    ("baz1", "/src/lel.py", 8),
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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert tree == inverted_import_system_tree
        assert {
            "name": "<root>",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
            "unique_threads": ["0x1"],
            "children": [
                {
                    "name": "baz1 at /src/lel.py:8",
                    "location": ["baz1", "/src/lel.py", 8],
                    "value": 2048,
                    "n_allocations": 2,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "bar2 at /src/lel.py:15",
                            "location": ["bar2", "/src/lel.py", 15],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "foo2 at /src/lel.py:12",
                                    "location": ["foo2", "/src/lel.py", 12],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        },
                        {
                            "name": "bar1 at /src/lel.py:5",
                            "location": ["bar1", "/src/lel.py", 5],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "foo1 at /src/lel.py:2",
                                    "location": ["foo1", "/src/lel.py", 2],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        },
                    ],
                }
            ],
        } == tree

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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "unique_threads": ["0x1", "0x2"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "foo2 at /src/lel.py:12",
                    "thread_id": "0x1",
                    "location": ["foo2", "/src/lel.py", 12],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "bar2 at /src/lel.py:15",
                            "thread_id": "0x1",
                            "location": ["bar2", "/src/lel.py", 15],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "baz2 at /src/lel.py:18",
                                    "thread_id": "0x1",
                                    "location": ["baz2", "/src/lel.py", 18],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "foo2 at /src/lel.py:12",
                    "thread_id": "0x2",
                    "location": ["foo2", "/src/lel.py", 12],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "bar2 at /src/lel.py:15",
                            "thread_id": "0x2",
                            "location": ["bar2", "/src/lel.py", 15],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "baz2 at /src/lel.py:18",
                                    "thread_id": "0x2",
                                    "location": ["baz2", "/src/lel.py", 18],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            ],
        } == tree

    def test_inverted_works_with_split_threads(self):
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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert tree == inverted_import_system_tree
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "unique_threads": ["0x1", "0x2"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "baz2 at /src/lel.py:18",
                    "thread_id": "0x1",
                    "location": ["baz2", "/src/lel.py", 18],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "bar2 at /src/lel.py:15",
                            "thread_id": "0x1",
                            "location": ["bar2", "/src/lel.py", 15],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "foo2 at /src/lel.py:12",
                                    "thread_id": "0x1",
                                    "location": ["foo2", "/src/lel.py", 12],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "baz2 at /src/lel.py:18",
                    "thread_id": "0x2",
                    "location": ["baz2", "/src/lel.py", 18],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "bar2 at /src/lel.py:15",
                            "thread_id": "0x2",
                            "location": ["bar2", "/src/lel.py", 15],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "foo2 at /src/lel.py:12",
                                    "thread_id": "0x2",
                                    "location": ["foo2", "/src/lel.py", 12],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            ],
        } == tree

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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "unique_threads": ["merged thread"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "foo2 at /src/lel.py:12",
                    "thread_id": "merged thread",
                    "location": ["foo2", "/src/lel.py", 12],
                    "value": 2048,
                    "n_allocations": 2,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "bar2 at /src/lel.py:15",
                            "thread_id": "merged thread",
                            "location": ["bar2", "/src/lel.py", 15],
                            "value": 2048,
                            "n_allocations": 2,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "baz2 at /src/lel.py:18",
                                    "thread_id": "merged thread",
                                    "location": ["baz2", "/src/lel.py", 18],
                                    "value": 2048,
                                    "n_allocations": 2,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            ],
        } == tree

    def test_inverted_works_with_merged_threads(self):
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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        tree == inverted_import_system_tree
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "unique_threads": ["merged thread"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "baz2 at /src/lel.py:18",
                    "thread_id": "merged thread",
                    "location": ["baz2", "/src/lel.py", 18],
                    "value": 2048,
                    "n_allocations": 2,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "bar2 at /src/lel.py:15",
                            "thread_id": "merged thread",
                            "location": ["bar2", "/src/lel.py", 15],
                            "value": 2048,
                            "n_allocations": 2,
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "foo2 at /src/lel.py:12",
                                    "thread_id": "merged thread",
                                    "location": ["foo2", "/src/lel.py", 12],
                                    "value": 2048,
                                    "n_allocations": 2,
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            ],
        } == tree

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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "unique_threads": ["0x1"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "parent at fun.py:8",
                    "thread_id": "0x1",
                    "location": ["parent", "fun.py", 8],
                    "value": 1024,
                    "n_allocations": 1,
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "me at fun.py:12",
                            "thread_id": "0x1",
                            "location": ["me", "fun.py", 12],
                            "value": 1024,
                            "children": [],
                            "interesting": True,
                            "import_system": False,
                            "n_allocations": 1,
                        }
                    ],
                }
            ],
        } == tree

    def test_inverted_drops_cpython_frames(self):
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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert tree == inverted_import_system_tree
        assert {
            "name": "<root>",
            "thread_id": "0x0",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "unique_threads": ["0x1"],
            "interesting": True,
            "import_system": False,
            "children": [
                {
                    "name": "me at fun.py:12",
                    "thread_id": "0x1",
                    "location": ["me", "fun.py", 12],
                    "value": 1024,
                    "interesting": True,
                    "import_system": False,
                    "n_allocations": 1,
                    "children": [
                        {
                            "name": "parent at fun.py:8",
                            "thread_id": "0x1",
                            "location": ["parent", "fun.py", 8],
                            "value": 1024,
                            "n_allocations": 1,
                            "interesting": True,
                            "import_system": False,
                            "children": [],
                        }
                    ],
                }
            ],
        } == tree

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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}

        current_depth = 0
        current_node = tree["children"][0]
        while current_node["children"]:
            current_depth += 1
            assert len(current_node["children"]) == 1
            name = current_node["name"]
            assert name == f"func_{current_depth} at fun.py:{current_depth}"
            current_node = current_node["children"][0]

        assert current_depth == MAX_STACKS + 1
        assert current_node == {
            "children": [],
            "location": ["...", "...", 0],
            "n_allocations": 1,
            "interesting": True,
            "import_system": False,
            "name": "<STACK TOO DEEP>",
            "thread_id": "0x1",
            "value": 1024,
        }

    def test_inverted_very_deep_call_is_limited(self):
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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, _ = get_packed_trees(reporter.data)

        # THEN
        current_depth = n_frames

        current_node = tree["children"][0]

        while current_node["children"]:
            assert len(current_node["children"]) == 1

            name = current_node["name"]

            assert name == f"func_{current_depth} at fun.py:{current_depth}"

            current_node = current_node["children"][0]

            current_depth -= 1

        assert (n_frames - current_depth) == MAX_STACKS + 1

        assert current_node == {
            "children": [],
            "location": ["...", "...", 0],
            "n_allocations": 1,
            "interesting": True,
            "import_system": False,
            "name": "<STACK TOO DEEP>",
            "thread_id": "0x1",
            "value": 1024,
        }

    def test_single_importlib_frame_is_detected(self):
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
                    ("me", "<frozen importlib>", 4),
                ],
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "children": [
                {
                    "children": [],
                    "import_system": True,
                    "interesting": False,
                    "location": ["me", "&lt;frozen importlib&gt;", 4],
                    "n_allocations": 1,
                    "name": "me at <frozen importlib>:4",
                    "thread_id": "0x1",
                    "value": 1024,
                }
            ],
            "import_system": False,
            "interesting": True,
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "n_allocations": 1,
            "name": "<root>",
            "thread_id": "0x0",
            "unique_threads": ["0x1"],
            "value": 1024,
        } == tree

    def test_inverted_single_importlib_frame_is_detected(self):
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
                    ("me", "<frozen importlib>", 4),
                ],
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert {
            "children": [
                {
                    "children": [],
                    "import_system": False,
                    "interesting": False,
                    "location": ["me", "&lt;frozen importlib&gt;", 4],
                    "n_allocations": 1,
                    "name": "me at <frozen importlib>:4",
                    "thread_id": "0x1",
                    "value": 1024,
                }
            ],
            "import_system": False,
            "interesting": True,
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "n_allocations": 1,
            "name": "<root>",
            "thread_id": "0x0",
            "unique_threads": ["0x1"],
            "value": 1024,
        } == tree

        assert {
            "children": [],
            "import_system": False,
            "interesting": True,
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "n_allocations": 1,
            "name": "<root>",
            "thread_id": "0x0",
            "unique_threads": ["0x1"],
            "value": 1024,
        } == inverted_import_system_tree

    def test_importlib_full_stack_is_detected(self):
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
                    ("grandparent", "<frozen importlib>", 4),
                ],
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "children": [
                {
                    "children": [
                        {
                            "children": [
                                {
                                    "children": [],
                                    "import_system": True,
                                    "interesting": True,
                                    "location": ["me", "fun.py", 12],
                                    "n_allocations": 1,
                                    "name": "me at fun.py:12",
                                    "thread_id": "0x1",
                                    "value": 1024,
                                }
                            ],
                            "import_system": True,
                            "interesting": True,
                            "location": ["parent", "fun.py", 8],
                            "n_allocations": 1,
                            "name": "parent at fun.py:8",
                            "thread_id": "0x1",
                            "value": 1024,
                        }
                    ],
                    "import_system": True,
                    "interesting": False,
                    "location": ["grandparent", "&lt;frozen importlib&gt;", 4],
                    "n_allocations": 1,
                    "name": "grandparent at <frozen importlib>:4",
                    "thread_id": "0x1",
                    "value": 1024,
                }
            ],
            "import_system": False,
            "interesting": True,
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "n_allocations": 1,
            "name": "<root>",
            "thread_id": "0x0",
            "unique_threads": ["0x1"],
            "value": 1024,
        } == tree

    def test_inverted_importlib_full_stack_is_detected(self):
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
                    ("grandparent", "<frozen importlib>", 4),
                ],
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert {
            "name": "<root>",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
            "unique_threads": ["0x1"],
            "children": [
                {
                    "name": "me at fun.py:12",
                    "location": ["me", "fun.py", 12],
                    "value": 1024,
                    "n_allocations": 1,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent at fun.py:8",
                            "location": ["parent", "fun.py", 8],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "grandparent at <frozen importlib>:4",
                                    "location": [
                                        "grandparent",
                                        "&lt;frozen importlib&gt;",
                                        4,
                                    ],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": False,
                                    "import_system": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        } == tree

        assert {
            "name": "<root>",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
            "unique_threads": ["0x1"],
            "children": [],
        } == inverted_import_system_tree

    def test_importlib_partial_stack_is_detected(self):
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
                    ("parent", "<frozen importlib>", 8),
                    ("grandparent", "fun.py", 4),
                    ("grandgrandparent", "fun.py", 4),
                ],
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "children": [
                {
                    "children": [
                        {
                            "children": [
                                {
                                    "children": [
                                        {
                                            "children": [],
                                            "import_system": True,
                                            "interesting": True,
                                            "location": ["me", "fun.py", 12],
                                            "n_allocations": 1,
                                            "name": "me at " "fun.py:12",
                                            "thread_id": "0x1",
                                            "value": 1024,
                                        }
                                    ],
                                    "import_system": True,
                                    "interesting": False,
                                    "location": [
                                        "parent",
                                        "&lt;frozen " "importlib&gt;",
                                        8,
                                    ],
                                    "n_allocations": 1,
                                    "name": "parent at <frozen " "importlib>:8",
                                    "thread_id": "0x1",
                                    "value": 1024,
                                }
                            ],
                            "import_system": False,
                            "interesting": True,
                            "location": ["grandparent", "fun.py", 4],
                            "n_allocations": 1,
                            "name": "grandparent at fun.py:4",
                            "thread_id": "0x1",
                            "value": 1024,
                        }
                    ],
                    "import_system": False,
                    "interesting": True,
                    "location": ["grandgrandparent", "fun.py", 4],
                    "n_allocations": 1,
                    "name": "grandgrandparent at fun.py:4",
                    "thread_id": "0x1",
                    "value": 1024,
                }
            ],
            "import_system": False,
            "interesting": True,
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "n_allocations": 1,
            "name": "<root>",
            "thread_id": "0x0",
            "unique_threads": ["0x1"],
            "value": 1024,
        } == tree

    def test_inverted_importlib_partial_stack_is_detected(self):
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
                    ("parent", "<frozen importlib>", 8),
                    ("grandparent", "fun.py", 4),
                    ("grandgrandparent", "fun.py", 4),
                ],
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert {
            "name": "<root>",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
            "unique_threads": ["0x1"],
            "children": [
                {
                    "name": "me at fun.py:12",
                    "location": ["me", "fun.py", 12],
                    "value": 1024,
                    "n_allocations": 1,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent at <frozen importlib>:8",
                            "location": ["parent", "&lt;frozen importlib&gt;", 8],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": False,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "grandparent at fun.py:4",
                                    "location": ["grandparent", "fun.py", 4],
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": True,
                                    "import_system": False,
                                    "children": [
                                        {
                                            "name": "grandgrandparent at fun.py:4",
                                            "location": [
                                                "grandgrandparent",
                                                "fun.py",
                                                4,
                                            ],
                                            "value": 1024,
                                            "n_allocations": 1,
                                            "thread_id": "0x1",
                                            "interesting": True,
                                            "import_system": False,
                                            "children": [],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        } == tree

        assert {
            "name": "<root>",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 1024,
            "n_allocations": 1,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
            "unique_threads": ["0x1"],
            "children": [
                {
                    "name": "grandparent at fun.py:4",
                    "location": ["grandparent", "fun.py", 4],
                    "value": 1024,
                    "n_allocations": 1,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "grandgrandparent at fun.py:4",
                            "location": [
                                "grandgrandparent",
                                "fun.py",
                                4,
                            ],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": True,
                            "import_system": False,
                            "children": [],
                        }
                    ],
                }
            ],
        } == inverted_import_system_tree

    def test_two_branches_first_is_importlib(self):
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
                    ("parent_one", "<frozen importlib>", 8),
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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "children": [
                {
                    "children": [
                        {
                            "children": [
                                {
                                    "children": [],
                                    "import_system": True,
                                    "interesting": True,
                                    "location": ["me", "fun.py", 12],
                                    "n_allocations": 1,
                                    "name": "me at fun.py:12",
                                    "thread_id": "0x1",
                                    "value": 1024,
                                }
                            ],
                            "import_system": True,
                            "interesting": False,
                            "location": ["parent_one", "&lt;frozen importlib&gt;", 8],
                            "n_allocations": 1,
                            "name": "parent_one at <frozen importlib>:8",
                            "thread_id": "0x1",
                            "value": 1024,
                        },
                        {
                            "children": [
                                {
                                    "children": [],
                                    "import_system": False,
                                    "interesting": True,
                                    "location": ["sibling", "fun.py", 16],
                                    "n_allocations": 1,
                                    "name": "sibling at fun.py:16",
                                    "thread_id": "0x1",
                                    "value": 1024,
                                }
                            ],
                            "import_system": False,
                            "interesting": True,
                            "location": ["parent_two", "fun.py", 10],
                            "n_allocations": 1,
                            "name": "parent_two at fun.py:10",
                            "thread_id": "0x1",
                            "value": 1024,
                        },
                    ],
                    "import_system": False,
                    "interesting": True,
                    "location": ["grandparent", "fun.py", 4],
                    "n_allocations": 2,
                    "name": "grandparent at fun.py:4",
                    "thread_id": "0x1",
                    "value": 2048,
                }
            ],
            "import_system": False,
            "interesting": True,
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "n_allocations": 2,
            "name": "<root>",
            "thread_id": "0x0",
            "unique_threads": ["0x1"],
            "value": 2048,
        } == tree

    def test_inverted_two_branches_first_is_importlib(self):
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
                    ("parent_one", "<frozen importlib>", 8),
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
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert {
            "import_system": False,
            "interesting": True,
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "n_allocations": 2,
            "name": "<root>",
            "thread_id": "0x0",
            "unique_threads": ["0x1"],
            "value": 2048,
            "children": [
                {
                    "import_system": False,
                    "interesting": True,
                    "location": ["me", "fun.py", 12],
                    "n_allocations": 1,
                    "name": "me at fun.py:12",
                    "thread_id": "0x1",
                    "value": 1024,
                    "children": [
                        {
                            "import_system": False,
                            "interesting": False,
                            "location": ["parent_one", "&lt;frozen importlib&gt;", 8],
                            "n_allocations": 1,
                            "name": "parent_one at <frozen importlib>:8",
                            "thread_id": "0x1",
                            "value": 1024,
                            "children": [
                                {
                                    "import_system": False,
                                    "interesting": True,
                                    "location": ["grandparent", "fun.py", 4],
                                    "n_allocations": 1,
                                    "name": "grandparent at fun.py:4",
                                    "thread_id": "0x1",
                                    "value": 1024,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                {
                    "import_system": False,
                    "interesting": True,
                    "location": ["sibling", "fun.py", 16],
                    "n_allocations": 1,
                    "name": "sibling at fun.py:16",
                    "thread_id": "0x1",
                    "value": 1024,
                    "children": [
                        {
                            "import_system": False,
                            "interesting": True,
                            "location": ["parent_two", "fun.py", 10],
                            "n_allocations": 1,
                            "name": "parent_two at fun.py:10",
                            "thread_id": "0x1",
                            "value": 1024,
                            "children": [
                                {
                                    "import_system": False,
                                    "interesting": True,
                                    "location": ["grandparent", "fun.py", 4],
                                    "n_allocations": 1,
                                    "name": "grandparent at fun.py:4",
                                    "thread_id": "0x1",
                                    "value": 1024,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            ],
        } == tree

        assert {
            "import_system": False,
            "interesting": True,
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "n_allocations": 2,
            "name": "<root>",
            "thread_id": "0x0",
            "unique_threads": ["0x1"],
            "value": 2048,
            "children": [
                {
                    "import_system": False,
                    "interesting": True,
                    "location": ["grandparent", "fun.py", 4],
                    "n_allocations": 1,
                    "name": "grandparent at fun.py:4",
                    "thread_id": "0x1",
                    "value": 1024,
                    "children": [],
                },
                {
                    "import_system": False,
                    "interesting": True,
                    "location": ["sibling", "fun.py", 16],
                    "n_allocations": 1,
                    "name": "sibling at fun.py:16",
                    "thread_id": "0x1",
                    "value": 1024,
                    "children": [
                        {
                            "import_system": False,
                            "interesting": True,
                            "location": ["parent_two", "fun.py", 10],
                            "n_allocations": 1,
                            "name": "parent_two at fun.py:10",
                            "thread_id": "0x1",
                            "value": 1024,
                            "children": [
                                {
                                    "import_system": False,
                                    "interesting": True,
                                    "location": ["grandparent", "fun.py", 4],
                                    "n_allocations": 1,
                                    "name": "grandparent at fun.py:4",
                                    "thread_id": "0x1",
                                    "value": 1024,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            ],
        } == inverted_import_system_tree

    def test_two_branches_second_is_importlib(self):
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
                    ("sibling", "fun.py", 16),
                    ("parent_two", "fun.py", 10),
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
                    ("me", "fun.py", 12),
                    ("parent_one", "<frozen importlib>", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "children": [
                {
                    "children": [
                        {
                            "children": [
                                {
                                    "children": [],
                                    "import_system": False,
                                    "interesting": True,
                                    "location": ["sibling", "fun.py", 16],
                                    "n_allocations": 1,
                                    "name": "sibling at fun.py:16",
                                    "thread_id": "0x1",
                                    "value": 1024,
                                }
                            ],
                            "import_system": False,
                            "interesting": True,
                            "location": ["parent_two", "fun.py", 10],
                            "n_allocations": 1,
                            "name": "parent_two at fun.py:10",
                            "thread_id": "0x1",
                            "value": 1024,
                        },
                        {
                            "children": [
                                {
                                    "children": [],
                                    "import_system": True,
                                    "interesting": True,
                                    "location": ["me", "fun.py", 12],
                                    "n_allocations": 1,
                                    "name": "me at fun.py:12",
                                    "thread_id": "0x1",
                                    "value": 1024,
                                }
                            ],
                            "import_system": True,
                            "interesting": False,
                            "location": ["parent_one", "&lt;frozen importlib&gt;", 8],
                            "n_allocations": 1,
                            "name": "parent_one at <frozen importlib>:8",
                            "thread_id": "0x1",
                            "value": 1024,
                        },
                    ],
                    "import_system": False,
                    "interesting": True,
                    "location": ["grandparent", "fun.py", 4],
                    "n_allocations": 2,
                    "name": "grandparent at fun.py:4",
                    "thread_id": "0x1",
                    "value": 2048,
                }
            ],
            "import_system": False,
            "interesting": True,
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "n_allocations": 2,
            "name": "<root>",
            "thread_id": "0x0",
            "unique_threads": ["0x1"],
            "value": 2048,
        } == tree

    def test_inverted_two_branches_second_is_importlib(self):
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
                    ("sibling", "fun.py", 16),
                    ("parent_two", "fun.py", 10),
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
                    ("me", "fun.py", 12),
                    ("parent_one", "<frozen importlib>", 8),
                    ("grandparent", "fun.py", 4),
                ],
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert {
            "name": "<root>",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
            "unique_threads": ["0x1"],
            "children": [
                {
                    "name": "sibling at fun.py:16",
                    "location": ["sibling", "fun.py", 16],
                    "value": 1024,
                    "n_allocations": 1,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent_two at fun.py:10",
                            "location": ["parent_two", "fun.py", 10],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "grandparent at fun.py:4",
                                    "location": ["grandparent", "fun.py", 4],
                                    "value": 1024,
                                    "children": [],
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": True,
                                    "import_system": False,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "me at fun.py:12",
                    "location": ["me", "fun.py", 12],
                    "value": 1024,
                    "n_allocations": 1,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent_one at <frozen importlib>:8",
                            "location": ["parent_one", "&lt;frozen importlib&gt;", 8],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": False,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "grandparent at fun.py:4",
                                    "location": ["grandparent", "fun.py", 4],
                                    "value": 1024,
                                    "children": [],
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": True,
                                    "import_system": False,
                                }
                            ],
                        }
                    ],
                },
            ],
        } == tree

        assert {
            "name": "<root>",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
            "unique_threads": ["0x1"],
            "children": [
                {
                    "name": "sibling at fun.py:16",
                    "location": ["sibling", "fun.py", 16],
                    "value": 1024,
                    "n_allocations": 1,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent_two at fun.py:10",
                            "location": ["parent_two", "fun.py", 10],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "grandparent at fun.py:4",
                                    "location": ["grandparent", "fun.py", 4],
                                    "value": 1024,
                                    "children": [],
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": True,
                                    "import_system": False,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "grandparent at fun.py:4",
                    "location": ["grandparent", "fun.py", 4],
                    "value": 1024,
                    "children": [],
                    "n_allocations": 1,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                },
            ],
        } == inverted_import_system_tree

    def test_two_branches_both_are_importlib(self):
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
                    ("grandparent", "<frozen importlib>", 4),
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
                    ("grandparent", "<frozen importlib>", 4),
                ],
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)

        # THEN
        assert inverted_import_system_tree == {}
        assert {
            "children": [
                {
                    "children": [
                        {
                            "children": [
                                {
                                    "children": [],
                                    "import_system": True,
                                    "interesting": True,
                                    "location": ["me", "fun.py", 12],
                                    "n_allocations": 1,
                                    "name": "me at fun.py:12",
                                    "thread_id": "0x1",
                                    "value": 1024,
                                }
                            ],
                            "import_system": True,
                            "interesting": True,
                            "location": ["parent_one", "fun.py", 8],
                            "n_allocations": 1,
                            "name": "parent_one at fun.py:8",
                            "thread_id": "0x1",
                            "value": 1024,
                        },
                        {
                            "children": [
                                {
                                    "children": [],
                                    "import_system": True,
                                    "interesting": True,
                                    "location": ["sibling", "fun.py", 16],
                                    "n_allocations": 1,
                                    "name": "sibling at fun.py:16",
                                    "thread_id": "0x1",
                                    "value": 1024,
                                }
                            ],
                            "import_system": True,
                            "interesting": True,
                            "location": ["parent_two", "fun.py", 10],
                            "n_allocations": 1,
                            "name": "parent_two at fun.py:10",
                            "thread_id": "0x1",
                            "value": 1024,
                        },
                    ],
                    "import_system": True,
                    "interesting": False,
                    "location": ["grandparent", "&lt;frozen importlib&gt;", 4],
                    "n_allocations": 2,
                    "name": "grandparent at <frozen importlib>:4",
                    "thread_id": "0x1",
                    "value": 2048,
                }
            ],
            "import_system": False,
            "interesting": True,
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "n_allocations": 2,
            "name": "<root>",
            "thread_id": "0x0",
            "unique_threads": ["0x1"],
            "value": 2048,
        } == tree

    def test_inverted_two_branches_both_are_importlib(self):
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
                    ("grandparent", "<frozen importlib>", 4),
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
                    ("grandparent", "<frozen importlib>", 4),
                ],
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False, inverted=True
        )

        tree, inverted_import_system_tree = get_packed_trees(reporter.data)
        # THEN
        assert {
            "name": "<root>",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
            "unique_threads": ["0x1"],
            "children": [
                {
                    "name": "me at fun.py:12",
                    "location": ["me", "fun.py", 12],
                    "value": 1024,
                    "n_allocations": 1,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent_one at fun.py:8",
                            "location": ["parent_one", "fun.py", 8],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "grandparent at <frozen importlib>:4",
                                    "location": [
                                        "grandparent",
                                        "&lt;frozen importlib&gt;",
                                        4,
                                    ],
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": False,
                                    "import_system": False,
                                    "value": 1024,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "sibling at fun.py:16",
                    "location": ["sibling", "fun.py", 16],
                    "value": 1024,
                    "n_allocations": 1,
                    "thread_id": "0x1",
                    "interesting": True,
                    "import_system": False,
                    "children": [
                        {
                            "name": "parent_two at fun.py:10",
                            "location": ["parent_two", "fun.py", 10],
                            "value": 1024,
                            "n_allocations": 1,
                            "thread_id": "0x1",
                            "interesting": True,
                            "import_system": False,
                            "children": [
                                {
                                    "name": "grandparent at <frozen importlib>:4",
                                    "location": [
                                        "grandparent",
                                        "&lt;frozen importlib&gt;",
                                        4,
                                    ],
                                    "n_allocations": 1,
                                    "thread_id": "0x1",
                                    "interesting": False,
                                    "import_system": False,
                                    "value": 1024,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            ],
        } == tree

        assert {
            "name": "<root>",
            "location": ["&lt;tracker&gt;", "<b>memray</b>", 0],
            "value": 2048,
            "n_allocations": 2,
            "thread_id": "0x0",
            "interesting": True,
            "import_system": False,
            "unique_threads": ["0x1"],
            "children": [],
        } == inverted_import_system_tree

    def test_source_lines_are_only_rendered_for_non_confidential_files(self, tmp_path):
        # GIVEN
        # A file's contents are only rendered into the flame graph when the
        # file is not "confidential". A file is considered non-confidential
        # (and so its source is rendered) if it is a Python source file, an
        # executable file, or a world-readable file. Any other existing file
        # is treated as confidential.

        # Non-confidential files: their contents should be rendered.
        # A .py file is non-confidential even with restrictive permissions.
        py_file = tmp_path / "module.py"
        py_file.write_text("py_source_line\nsecond line\n")
        os.chmod(py_file, 0o600)

        # A non-.py file that is executable (but not world-readable).
        executable_file = tmp_path / "script.sh"
        executable_file.write_text("executable_source_line\nsecond\n")
        os.chmod(executable_file, 0o700)

        # A non-.py file that is world-readable (but not executable).
        world_readable_file = tmp_path / "data.txt"
        world_readable_file.write_text("world_readable_source_line\nx\n")
        os.chmod(world_readable_file, 0o644)

        # Confidential files: their contents should NOT be rendered.
        # An existing non-.py file that is neither executable nor world-readable.
        confidential_file = tmp_path / "secret.pem"
        confidential_file.write_text("PRIVATE KEY MATERIAL DO NOT LEAK\nsecond\n")
        os.chmod(confidential_file, 0o600)

        # A non-.py file that doesn't exist (os.stat raises, so it's confidential).
        missing_secret = str(tmp_path / "missing.pem")

        # A .py file that doesn't exist: is_confidential_file returns False, but
        # there is no source line to read, so only location info is rendered.
        missing_python_file = str(tmp_path / "missing.py")

        stack = [
            ("apple", str(py_file), 1),
            ("banana", str(executable_file), 1),
            ("cherry", str(world_readable_file), 1),
            ("date", str(confidential_file), 1),
            ("elderberry", missing_secret, 1),
            ("fig", missing_python_file, 1),
        ]

        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=stack,
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations, memory_records=[], native_traces=False
        )
        tree, _ = get_packed_trees(reporter.data)

        # Collect the rendered `name` for each frame, keyed by its file name.
        read_lines = {}
        pending = [tree]
        while pending:
            node = pending.pop()
            read_lines[node["location"][1]] = node["name"]
            pending.extend(node["children"])

        # THEN
        # Non-confidential files have their source line rendered verbatim.
        assert read_lines[str(py_file)] == "py_source_line\n"
        assert read_lines[str(executable_file)] == "executable_source_line\n"
        assert read_lines[str(world_readable_file)] == "world_readable_source_line\n"

        # Confidential and missing files just render the location.
        assert read_lines[str(confidential_file)] == f"date at {confidential_file}:1"
        assert read_lines[missing_secret] == f"elderberry at {missing_secret}:1"
        assert read_lines[missing_python_file] == f"fig at {missing_python_file}:1"

    def test_confidential_files_all_never_renders_source(self, tmp_path):
        # GIVEN
        # With confidential_files="all", is_confidential_file is never called and
        # every file is treated as confidential, so no source line is ever
        # rendered - not even for files that the default heuristic would deem
        # safe (Python source files, executable files, world-readable files).

        # A .py file, which the default heuristic would deem non-confidential.
        py_file = tmp_path / "module.py"
        py_file.write_text("py_source_line\nsecond line\n")
        os.chmod(py_file, 0o600)

        # An executable non-.py file, non-confidential by default.
        executable_file = tmp_path / "script.sh"
        executable_file.write_text("executable_source_line\nsecond\n")
        os.chmod(executable_file, 0o700)

        # A world-readable non-.py file, non-confidential by default.
        world_readable_file = tmp_path / "data.txt"
        world_readable_file.write_text("world_readable_source_line\nx\n")
        os.chmod(world_readable_file, 0o644)

        # A non-.py file that is neither executable nor world-readable.
        confidential_file = tmp_path / "secret.pem"
        confidential_file.write_text("PRIVATE KEY MATERIAL DO NOT LEAK\nsecond\n")
        os.chmod(confidential_file, 0o600)

        # Files that don't exist.
        missing_secret = str(tmp_path / "missing.pem")
        missing_python_file = str(tmp_path / "missing.py")

        stack = [
            ("apple", str(py_file), 1),
            ("banana", str(executable_file), 1),
            ("cherry", str(world_readable_file), 1),
            ("date", str(confidential_file), 1),
            ("elderberry", missing_secret, 1),
            ("fig", missing_python_file, 1),
        ]

        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=stack,
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations,
            memory_records=[],
            native_traces=False,
            confidential_files="all",
        )
        tree, _ = get_packed_trees(reporter.data)

        # Collect the rendered `name` for each frame, keyed by its file name.
        read_lines = {}
        pending = [tree]
        while pending:
            node = pending.pop()
            read_lines[node["location"][1]] = node["name"]
            pending.extend(node["children"])

        # THEN
        # No file has its contents rendered; only the location is shown.
        assert read_lines[str(py_file)] == f"apple at {py_file}:1"
        assert read_lines[str(executable_file)] == f"banana at {executable_file}:1"
        assert (
            read_lines[str(world_readable_file)] == f"cherry at {world_readable_file}:1"
        )
        assert read_lines[str(confidential_file)] == f"date at {confidential_file}:1"
        assert read_lines[missing_secret] == f"elderberry at {missing_secret}:1"
        assert read_lines[missing_python_file] == f"fig at {missing_python_file}:1"

    def test_confidential_files_none_always_renders_source(self, tmp_path):
        # GIVEN
        # With confidential_files="none", is_confidential_file is never called and
        # no file is treated as confidential, so source lines are rendered for
        # every file that exists - even for files the default heuristic would
        # deem confidential. Files that don't exist have no source to render, so
        # only their location is shown.

        # A .py file, non-confidential by default too.
        py_file = tmp_path / "module.py"
        py_file.write_text("py_source_line\nsecond line\n")
        os.chmod(py_file, 0o600)

        # An executable non-.py file.
        executable_file = tmp_path / "script.sh"
        executable_file.write_text("executable_source_line\nsecond\n")
        os.chmod(executable_file, 0o700)

        # A world-readable non-.py file.
        world_readable_file = tmp_path / "data.txt"
        world_readable_file.write_text("world_readable_source_line\nx\n")
        os.chmod(world_readable_file, 0o644)

        # A non-.py file that the default heuristic would deem confidential.
        confidential_file = tmp_path / "secret.pem"
        confidential_file.write_text("PRIVATE KEY MATERIAL DO NOT LEAK\nsecond\n")
        os.chmod(confidential_file, 0o600)

        # Files that don't exist.
        missing_secret = str(tmp_path / "missing.pem")
        missing_python_file = str(tmp_path / "missing.py")

        stack = [
            ("apple", str(py_file), 1),
            ("banana", str(executable_file), 1),
            ("cherry", str(world_readable_file), 1),
            ("date", str(confidential_file), 1),
            ("elderberry", missing_secret, 1),
            ("fig", missing_python_file, 1),
        ]

        peak_allocations = [
            MockAllocationRecord(
                tid=1,
                address=0x1000000,
                size=1024,
                allocator=AllocatorType.MALLOC,
                stack_id=1,
                n_allocations=1,
                _stack=stack,
            ),
        ]

        # WHEN
        reporter = FlameGraphReporter.from_snapshot(
            peak_allocations,
            memory_records=[],
            native_traces=False,
            confidential_files="none",
        )
        tree, _ = get_packed_trees(reporter.data)

        # Collect the rendered `name` for each frame, keyed by its file name.
        read_lines = {}
        pending = [tree]
        while pending:
            node = pending.pop()
            read_lines[node["location"][1]] = node["name"]
            pending.extend(node["children"])

        # THEN
        # Every existing file has its source line rendered verbatim, including
        # the file the default heuristic would have treated as confidential.
        assert read_lines[str(py_file)] == "py_source_line\n"
        assert read_lines[str(executable_file)] == "executable_source_line\n"
        assert read_lines[str(world_readable_file)] == "world_readable_source_line\n"
        assert (
            read_lines[str(confidential_file)] == "PRIVATE KEY MATERIAL DO NOT LEAK\n"
        )

        # Missing files still render only their location.
        assert read_lines[missing_secret] == f"elderberry at {missing_secret}:1"
        assert read_lines[missing_python_file] == f"fig at {missing_python_file}:1"
