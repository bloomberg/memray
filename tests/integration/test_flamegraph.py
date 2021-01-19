from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator
from bloomberg.pensieve.reporters.flamegraph import FlameGraphReporter
from tests.utils import MockAllocationRecord
from tests.utils import filter_relevant_allocations


class TestFlameGraphReporter:
    def test_works_with_no_allocations(self):
        reporter = FlameGraphReporter.from_snapshot([])
        assert reporter.data["name"] == "root"
        assert reporter.data["value"] == 0
        assert reporter.data["children"] == []

    def test_works_with_single_call(self):
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
        reporter = FlameGraphReporter.from_snapshot(peak_allocations)
        assert reporter.data == {
            "name": "root",
            "value": 1024,
            "children": [
                {
                    "name": "fun.py:4",
                    "value": 1024,
                    "children": [
                        {
                            "name": "fun.py:8",
                            "value": 1024,
                            "children": [
                                {
                                    "name": "fun.py:12",
                                    "value": 1024,
                                    "children": [],
                                    "function": "me",
                                    "filename": "fun.py",
                                    "lineno": 12,
                                }
                            ],
                            "function": "parent",
                            "filename": "fun.py",
                            "lineno": 8,
                        }
                    ],
                    "function": "grandparent",
                    "filename": "fun.py",
                    "lineno": 4,
                }
            ],
            "filename": "<root>",
            "lineno": 0,
        }

    def test_works_with_multiple_stacks_from_same_caller(self):
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
        reporter = FlameGraphReporter.from_snapshot(peak_allocations)
        assert reporter.data == {
            "name": "root",
            "value": 2048,
            "children": [
                {
                    "name": "fun.py:4",
                    "value": 2048,
                    "children": [
                        {
                            "name": "fun.py:8",
                            "value": 2048,
                            "children": [
                                {
                                    "name": "fun.py:12",
                                    "value": 1024,
                                    "children": [],
                                    "function": "me",
                                    "filename": "fun.py",
                                    "lineno": 12,
                                },
                                {
                                    "name": "fun.py:16",
                                    "value": 1024,
                                    "children": [],
                                    "function": "sibling",
                                    "filename": "fun.py",
                                    "lineno": 16,
                                },
                            ],
                            "function": "parent",
                            "filename": "fun.py",
                            "lineno": 8,
                        }
                    ],
                    "function": "grandparent",
                    "filename": "fun.py",
                    "lineno": 4,
                }
            ],
            "filename": "<root>",
            "lineno": 0,
        }

    def test_sanity_check_with_real_allocations(self, tmp_path):
        allocator = MemoryAllocator()
        with Tracker(tmp_path / "test.bin") as tracker:
            allocator.valloc(1024)
            allocator.free()

        peak_allocations = filter_relevant_allocations(
            tracker.get_high_watermark_allocation_records()
        )

        reporter = FlameGraphReporter.from_snapshot(peak_allocations)

        assert reporter.data["name"] == "root"
        assert reporter.data["value"] == 1024

        assert isinstance(reporter.data["children"], list)
        assert len(reporter.data["children"]) == 1

        child = reporter.data["children"][0]
        assert child["function"] == "valloc"

    def test_works_with_multiple_stacks_from_same_caller_two_frames_above(self):
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
        reporter = FlameGraphReporter.from_snapshot(peak_allocations)
        assert reporter.data == {
            "name": "root",
            "value": 2048,
            "children": [
                {
                    "name": "fun.py:4",
                    "value": 2048,
                    "children": [
                        {
                            "name": "fun.py:8",
                            "value": 1024,
                            "children": [
                                {
                                    "name": "fun.py:12",
                                    "value": 1024,
                                    "children": [],
                                    "function": "me",
                                    "filename": "fun.py",
                                    "lineno": 12,
                                }
                            ],
                            "function": "parent_one",
                            "filename": "fun.py",
                            "lineno": 8,
                        },
                        {
                            "name": "fun.py:10",
                            "value": 1024,
                            "children": [
                                {
                                    "name": "fun.py:16",
                                    "value": 1024,
                                    "children": [],
                                    "function": "sibling",
                                    "filename": "fun.py",
                                    "lineno": 16,
                                }
                            ],
                            "function": "parent_two",
                            "filename": "fun.py",
                            "lineno": 10,
                        },
                    ],
                    "function": "grandparent",
                    "filename": "fun.py",
                    "lineno": 4,
                }
            ],
            "filename": "<root>",
            "lineno": 0,
        }

    def test_works_with_recursive_calls(self):
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
        reporter = FlameGraphReporter.from_snapshot(peak_allocations)
        assert reporter.data == {
            "name": "root",
            "value": 1024,
            "children": [
                {
                    "name": "recursive.py:5",
                    "value": 1024,
                    "children": [
                        {
                            "name": "recursive.py:20",
                            "value": 1024,
                            "children": [
                                {
                                    "name": "recursive.py:10",
                                    "value": 1024,
                                    "children": [
                                        {
                                            "name": "recursive.py:20",
                                            "value": 1024,
                                            "children": [
                                                {
                                                    "name": "recursive.py:10",
                                                    "value": 1024,
                                                    "children": [
                                                        {
                                                            "name": "recursive.py:20",
                                                            "value": 1024,
                                                            "children": [
                                                                {
                                                                    "name": "recursive.py:9",
                                                                    "value": 1024,
                                                                    "children": [],
                                                                    "function": "one",
                                                                    "filename": "recursive.py",
                                                                    "lineno": 9,
                                                                }
                                                            ],
                                                            "function": "two",
                                                            "filename": "recursive.py",
                                                            "lineno": 20,
                                                        }
                                                    ],
                                                    "function": "one",
                                                    "filename": "recursive.py",
                                                    "lineno": 10,
                                                }
                                            ],
                                            "function": "two",
                                            "filename": "recursive.py",
                                            "lineno": 20,
                                        }
                                    ],
                                    "function": "one",
                                    "filename": "recursive.py",
                                    "lineno": 10,
                                }
                            ],
                            "function": "two",
                            "filename": "recursive.py",
                            "lineno": 20,
                        }
                    ],
                    "function": "main",
                    "filename": "recursive.py",
                    "lineno": 5,
                }
            ],
            "filename": "<root>",
            "lineno": 0,
        }

    def test_works_with_multiple_top_level_nodes(self):
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
        reporter = FlameGraphReporter.from_snapshot(peak_allocations)
        assert reporter.data == {
            "name": "root",
            "value": 2048,
            "children": [
                {
                    "name": "/src/lel.py:12",
                    "value": 1024,
                    "children": [
                        {
                            "name": "/src/lel.py:15",
                            "value": 1024,
                            "children": [
                                {
                                    "name": "/src/lel.py:18",
                                    "value": 1024,
                                    "children": [],
                                    "function": "baz2",
                                    "filename": "/src/lel.py",
                                    "lineno": 18,
                                }
                            ],
                            "function": "bar2",
                            "filename": "/src/lel.py",
                            "lineno": 15,
                        }
                    ],
                    "function": "foo2",
                    "filename": "/src/lel.py",
                    "lineno": 12,
                },
                {
                    "name": "/src/lel.py:2",
                    "value": 1024,
                    "children": [
                        {
                            "name": "/src/lel.py:5",
                            "value": 1024,
                            "children": [
                                {
                                    "name": "/src/lel.py:8",
                                    "value": 1024,
                                    "children": [],
                                    "function": "baz1",
                                    "filename": "/src/lel.py",
                                    "lineno": 8,
                                }
                            ],
                            "function": "bar1",
                            "filename": "/src/lel.py",
                            "lineno": 5,
                        }
                    ],
                    "function": "foo1",
                    "filename": "/src/lel.py",
                    "lineno": 2,
                },
            ],
            "filename": "<root>",
            "lineno": 0,
        }
