from bloomberg.pensieve import AllocatorType
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator
from bloomberg.pensieve.reporters.flamegraph import FlameGraphReporter
from tests.utils import MockAllocationRecord
from tests.utils import filter_relevant_allocations


class TestFlameGraphReporter:
    def test_works_with_no_allocations(self):
        reporter = FlameGraphReporter.from_snapshot([])
        assert reporter.data["name"] == "<root>"
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
            "name": "<root>",
            "tooltip": "The overall context that <b>pensieve</b> is run in.",
            "value": 1024,
            "n_allocations": 1,
            "allocations_label": "1 allocation",
            "children": [
                {
                    "name": "fun.py:4",
                    "tooltip": "File fun.py, line 4 in grandparent",
                    "value": 1024,
                    "n_allocations": 1,
                    "allocations_label": "1 allocation",
                    "children": [
                        {
                            "name": "fun.py:8",
                            "tooltip": "File fun.py, line 8 in parent",
                            "value": 1024,
                            "n_allocations": 1,
                            "allocations_label": "1 allocation",
                            "children": [
                                {
                                    "name": "fun.py:12",
                                    "tooltip": "File fun.py, line 12 in me",
                                    "value": 1024,
                                    "children": [],
                                    "n_allocations": 1,
                                    "allocations_label": "1 allocation",
                                }
                            ],
                        }
                    ],
                }
            ],
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
            "name": "<root>",
            "tooltip": "The overall context that <b>pensieve</b> is run in.",
            "value": 2048,
            "n_allocations": 2,
            "allocations_label": "2 allocations",
            "children": [
                {
                    "name": "fun.py:4",
                    "tooltip": "File fun.py, line 4 in grandparent",
                    "value": 2048,
                    "n_allocations": 2,
                    "allocations_label": "2 allocations",
                    "children": [
                        {
                            "name": "fun.py:8",
                            "tooltip": "File fun.py, line 8 in parent",
                            "value": 2048,
                            "n_allocations": 2,
                            "allocations_label": "2 allocations",
                            "children": [
                                {
                                    "name": "fun.py:12",
                                    "tooltip": "File fun.py, line 12 in me",
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "allocations_label": "1 allocation",
                                    "children": [],
                                },
                                {
                                    "name": "fun.py:16",
                                    "tooltip": "File fun.py, line 16 in sibling",
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "allocations_label": "1 allocation",
                                    "children": [],
                                },
                            ],
                        }
                    ],
                }
            ],
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

        assert reporter.data["name"] == "<root>"
        assert reporter.data["value"] == 1024

        assert isinstance(reporter.data["children"], list)
        assert len(reporter.data["children"]) == 1

        child = reporter.data["children"][0]
        assert child["name"] == "    def valloc(self, size_t size):\n"

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
            "name": "<root>",
            "tooltip": "The overall context that <b>pensieve</b> is run in.",
            "value": 2048,
            "n_allocations": 2,
            "allocations_label": "2 allocations",
            "children": [
                {
                    "name": "fun.py:4",
                    "tooltip": "File fun.py, line 4 in grandparent",
                    "value": 2048,
                    "n_allocations": 2,
                    "allocations_label": "2 allocations",
                    "children": [
                        {
                            "name": "fun.py:8",
                            "tooltip": "File fun.py, line 8 in parent_one",
                            "value": 1024,
                            "n_allocations": 1,
                            "allocations_label": "1 allocation",
                            "children": [
                                {
                                    "name": "fun.py:12",
                                    "tooltip": "File fun.py, line 12 in me",
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "allocations_label": "1 allocation",
                                    "children": [],
                                }
                            ],
                        },
                        {
                            "name": "fun.py:10",
                            "tooltip": "File fun.py, line 10 in parent_two",
                            "value": 1024,
                            "n_allocations": 1,
                            "allocations_label": "1 allocation",
                            "children": [
                                {
                                    "name": "fun.py:16",
                                    "tooltip": "File fun.py, line 16 in sibling",
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "allocations_label": "1 allocation",
                                    "children": [],
                                }
                            ],
                        },
                    ],
                }
            ],
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
            "name": "<root>",
            "tooltip": "The overall context that <b>pensieve</b> is run in.",
            "value": 1024,
            "n_allocations": 1,
            "allocations_label": "1 allocation",
            "children": [
                {
                    "name": "recursive.py:5",
                    "tooltip": "File recursive.py, line 5 in main",
                    "value": 1024,
                    "n_allocations": 1,
                    "allocations_label": "1 allocation",
                    "children": [
                        {
                            "name": "recursive.py:20",
                            "tooltip": "File recursive.py, line 20 in two",
                            "value": 1024,
                            "n_allocations": 1,
                            "allocations_label": "1 allocation",
                            "children": [
                                {
                                    "name": "recursive.py:10",
                                    "tooltip": "File recursive.py, line 10 in one",
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "allocations_label": "1 allocation",
                                    "children": [
                                        {
                                            "name": "recursive.py:20",
                                            "tooltip": "File recursive.py, line 20 in two",
                                            "value": 1024,
                                            "n_allocations": 1,
                                            "allocations_label": "1 allocation",
                                            "children": [
                                                {
                                                    "name": "recursive.py:10",
                                                    "tooltip": "File recursive.py, line 10 in one",  # noqa
                                                    "value": 1024,
                                                    "n_allocations": 1,
                                                    "allocations_label": "1 allocation",
                                                    "children": [
                                                        {
                                                            "name": "recursive.py:20",
                                                            "tooltip": "File recursive.py, line 20 in two",  # noqa
                                                            "value": 1024,
                                                            "n_allocations": 1,
                                                            "allocations_label": "1 allocation",  # noqa
                                                            "children": [
                                                                {
                                                                    "name": "recursive.py:9",
                                                                    "tooltip": "File recursive.py, line 9 in one",  # noqa
                                                                    "value": 1024,
                                                                    "n_allocations": 1,
                                                                    "allocations_label": "1 allocation",  # noqa
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
            "name": "<root>",
            "tooltip": "The overall context that <b>pensieve</b> is run in.",
            "value": 2048,
            "n_allocations": 2,
            "allocations_label": "2 allocations",
            "children": [
                {
                    "name": "/src/lel.py:12",
                    "tooltip": "File /src/lel.py, line 12 in foo2",
                    "value": 1024,
                    "n_allocations": 1,
                    "allocations_label": "1 allocation",
                    "children": [
                        {
                            "name": "/src/lel.py:15",
                            "tooltip": "File /src/lel.py, line 15 in bar2",
                            "value": 1024,
                            "n_allocations": 1,
                            "allocations_label": "1 allocation",
                            "children": [
                                {
                                    "name": "/src/lel.py:18",
                                    "tooltip": "File /src/lel.py, line 18 in baz2",
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "allocations_label": "1 allocation",
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "/src/lel.py:2",
                    "tooltip": "File /src/lel.py, line 2 in foo1",
                    "value": 1024,
                    "n_allocations": 1,
                    "allocations_label": "1 allocation",
                    "children": [
                        {
                            "name": "/src/lel.py:5",
                            "tooltip": "File /src/lel.py, line 5 in bar1",
                            "value": 1024,
                            "n_allocations": 1,
                            "allocations_label": "1 allocation",
                            "children": [
                                {
                                    "name": "/src/lel.py:8",
                                    "tooltip": "File /src/lel.py, line 8 in baz1",
                                    "value": 1024,
                                    "n_allocations": 1,
                                    "allocations_label": "1 allocation",
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            ],
        }
