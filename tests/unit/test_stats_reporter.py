import json
from collections import Counter
from datetime import datetime
from typing import List
from typing import Optional
from typing import Tuple
from unittest.mock import patch

import pytest

from memray import AllocatorType as AT
from memray._metadata import Metadata
from memray._stats import Stats
from memray.reporters.stats import StatsReporter
from memray.reporters.stats import draw_histogram
from memray.reporters.stats import get_histogram_databins
from tests.utils import MockAllocationRecord


# data generator for tests
def _generate_mock_allocations(
    count: int,
    sizes: Optional[List[int]] = None,
    allocators: Optional[List[AT]] = None,
    n_allocations: Optional[List[int]] = None,
    stacks: Optional[List[List[Tuple[str, str, int]]]] = None,
):  # pragma: no cover
    if sizes is None:
        sizes = []
    if allocators is None:
        allocators = []
    if n_allocations is None:
        n_allocations = []
    if stacks is None:
        stacks = []

    sizes.extend([1024] * (count - len(sizes)))
    sizes = sizes[:count]

    allocators.extend([AT.MALLOC] * (count - len(allocators)))
    allocators = allocators[:count]

    n_allocations.extend([1] * (count - len(n_allocations)))
    n_allocations = n_allocations[:count]

    default_stacks_value = [
        ("me", "fun.py", 12),
        ("parent", "fun.py", 8),
        ("grandparent", "fun.py", 4),
    ]
    stacks.extend([default_stacks_value] * (count - len(stacks)))
    stacks = stacks[:count]

    snapshot = []
    for i in range(count):
        snapshot.append(
            MockAllocationRecord(
                tid=i + 1,
                address=0x1000000,
                size=sizes[i],
                allocator=allocators[i],
                stack_id=i + 1,
                n_allocations=n_allocations[i],
                _stack=stacks[i],
            )
        )

    return snapshot


# data generator for tests
@pytest.fixture(scope="module")
def fake_stats():
    mem_allocation_list = [
        2500,
        11000,
        11000,
        12000,
        60000,
        65000,
        120000,
        125000,
        125000,
        160000,
        170000,
        180000,
        800000,
        1500000,
    ]

    s = Stats(
        metadata=Metadata(
            start_time=datetime(2023, 1, 1, 1),
            end_time=datetime(2023, 1, 1, 2),
            total_allocations=sum(mem_allocation_list),
            total_frames=10,
            peak_memory=max(mem_allocation_list),
            command_line="fake stats",
            pid=123456,
            python_allocator="pymalloc",
            has_native_traces=False,
        ),
        total_num_allocations=20,
        total_memory_allocated=sum(mem_allocation_list),
        peak_memory_allocated=max(mem_allocation_list),
        allocation_count_by_size=Counter(mem_allocation_list),
        allocation_count_by_allocator={
            AT.MALLOC.name: 1013,
            AT.REALLOC.name: 797,
            AT.CALLOC.name: 152,
            AT.MMAP.name: 4,
        },
        top_locations_by_count=[
            (("fake_func", "fake.py", 5), 20),
            (("fake_func2", "fake.py", 10), 50),
            (("__main__", "fake.py", 15), 1),
        ],
        top_locations_by_size=[
            (("fake_func", "fake.py", 5), 5 * 2**20),
            (("fake_func2", "fake.py", 10), 3 * 2**10),
            (("__main__", "fake.py", 15), 4),
        ],
    )
    return s


# tests begin here
def test_get_histogram_databins():
    # GIVEN
    input_data = Counter(
        [
            2500,
            11000,
            11000,
            12000,
            60000,
            65000,
            120000,
            125000,
            125000,
            160000,
            170000,
            180000,
            800000,
            1500000,
        ]
    )
    expected_output = [
        (8986, 1),
        (32299, 3),
        (116099, 2),
        (417312, 6),
        (1500000, 2),
    ]

    # WHEN
    actual_output = get_histogram_databins(input_data, bins=5)

    # THEN
    assert expected_output == actual_output


def test_get_histogram_databins_rounding():
    """Data chosen to provoke a floating point rounding error.

    In particular, so that:

        log(low) + sum([(log(high) - log(low)) / bins] * bins) > log(high)
    """
    # GIVEN
    input_data = Counter(
        [
            32,
            1050856,
        ]
    )
    expected_output = [
        (90, 1),
        (256, 0),
        (724, 0),
        (2049, 0),
        (5798, 0),
        (16405, 0),
        (46411, 0),
        (131299, 0),
        (371453, 0),
        (1050856, 1),
    ]

    # WHEN
    actual_output = get_histogram_databins(input_data, bins=10)

    # THEN
    assert expected_output == actual_output


def test_get_histogram_over_bound():
    """Data chosen to provoke a scenario where the computed allocation exceeds the upper limit.

    In particular, so that:
        Counter(min((x - low) // step, bins-1) for x in it) will default to placing it in the
        last bin instead of creating a new record out of range of the bins.
    """
    input_data = Counter([10000000000, 536, 536, 592, 576, 4486])
    expected_output = [
        (2859, 4),
        (15252, 1),
        (81360, 0),
        (434009, 0),
        (2315167, 0),
        (12349970, 0),
        (65879369, 0),
        (351425246, 0),
        (1874633954, 0),
        (10000000000, 1),
    ]

    # WHEN
    actual_output = get_histogram_databins(input_data, bins=10)

    # THEN
    assert expected_output == actual_output


def test_get_histogram_all_allocations_same_size():
    input_data = Counter([10000000000, 10000000000, 10000000000])
    expected_output = [
        (316227, 0),
        (999999, 0),
        (3162277, 0),
        (10000000, 0),
        (31622776, 0),
        (100000000, 0),
        (316227766, 0),
        (999999999, 0),
        (3162277660, 0),
        (10000000000, 3),
    ]

    # WHEN
    actual_output = get_histogram_databins(input_data, bins=10)

    # THEN
    assert expected_output == actual_output


def test_get_histogram_databins_invalid_bins():
    with pytest.raises(ValueError):
        _ = get_histogram_databins([], bins=0)  # invalid bins value
    with pytest.raises(ValueError):
        _ = get_histogram_databins([], bins=-1)  # invalid bins value


def test_draw_histogram():
    # GIVEN
    input_data = Counter(
        [
            2500,
            11000,
            11000,
            12000,
            60000,
            65000,
            120000,
            125000,
            125000,
            160000,
            170000,
            180000,
            800000,
            1500000,
        ]
    )
    expected_output = """min: 2.441KB
\t----------------------------------------
\t< 8.775KB  : 1 ▇▇▇▇▇
\t< 31.542KB : 3 ▇▇▇▇▇▇▇▇▇▇▇▇▇
\t< 113.378KB: 2 ▇▇▇▇▇▇▇▇▇
\t< 407.531KB: 6 ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇
\t<=1.431MB  : 2 ▇▇▇▇▇▇▇▇▇
\t----------------------------------------
\tmax: 1.431MB"""

    # WHEN
    actual_output = draw_histogram(input_data, bins=5)

    # THEN
    assert expected_output == actual_output


def test_draw_histogram_smaller_scale_factor():
    # GIVEN
    input_data = Counter(
        [
            2500,
            11000,
            11000,
            12000,
            60000,
            65000,
            120000,
            125000,
            125000,
            160000,
            170000,
            180000,
            800000,
            1500000,
        ]
    )

    expected_output = """min: 2.441KB
\t--------------------
\t< 8.775KB  : 1 ▇
\t< 31.542KB : 3 ▇▇▇
\t< 113.378KB: 2 ▇▇
\t< 407.531KB: 6 ▇▇▇▇▇
\t<=1.431MB  : 2 ▇▇
\t--------------------
\tmax: 1.431MB"""

    # WHEN
    actual_output = draw_histogram(
        input_data, bins=5, hist_scale_factor=5
    )  # setting this to 5

    # THEN
    assert expected_output == actual_output


def test_draw_histogram_invalid_input():
    # test#1 - No input data
    input_data = Counter()
    actual_output = draw_histogram(input_data, bins=5)
    assert "<no data for histogram>" == actual_output

    # test#2 - Invalid bins value
    with pytest.raises(ValueError):
        _ = draw_histogram([100, 200, 300], bins=0)

    # test#3 - Invalid hist_scale_factor value
    with pytest.raises(ValueError):
        _ = draw_histogram([100, 200, 300], bins=5, hist_scale_factor=0)


def test_stats_output(fake_stats):
    reporter = StatsReporter(fake_stats, 5)
    with patch("builtins.print") as mocked_print:
        with patch("rich.print", print):
            reporter.render()
    expected = (
        "📏 [bold]Total allocations:[/]\n"
        "\t20\n"
        "\n"
        "📦 [bold]Total memory allocated:[/]\n"
        "\t3.187MB\n"
        "\n"
        "📊 [bold]Histogram of allocation size:[/]\n"
        "\tmin: 2.441KB\n"
        "\t----------------------------------------\n"
        "\t< 4.628KB  : 1 ▇▇▇▇▇\n"
        "\t< 8.775KB  : 0 \n"
        "\t< 16.637KB : 3 ▇▇▇▇▇▇▇▇▇▇▇▇▇\n"
        "\t< 31.542KB : 0 \n"
        "\t< 59.802KB : 1 ▇▇▇▇▇\n"
        "\t< 113.378KB: 1 ▇▇▇▇▇\n"
        "\t< 214.954KB: 6 ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇\n"
        "\t< 407.531KB: 0 \n"
        "\t< 772.638KB: 0 \n"
        "\t<=1.431MB  : 2 ▇▇▇▇▇▇▇▇▇\n"
        "\t----------------------------------------\n"
        "\tmax: 1.431MB\n"
        "\n"
        "📂 [bold]Allocator type distribution:[/]\n"
        "\t MALLOC: 1013\n"
        "\t REALLOC: 797\n"
        "\t CALLOC: 152\n"
        "\t MMAP: 4\n"
        "\n"
        "🥇 [bold]Top 5 largest allocating locations (by size):[/]\n"
        "\t- fake_func:fake.py:5 -> 5.000MB\n"
        "\t- fake_func2:fake.py:10 -> 3.000KB\n"
        "\t- __main__:fake.py:15 -> 4.000B\n"
        "\n"
        "🥇 [bold]Top 5 largest allocating locations (by number of allocations):[/]\n"
        "\t- fake_func:fake.py:5 -> 20\n"
        "\t- fake_func2:fake.py:10 -> 50\n"
        "\t- __main__:fake.py:15 -> 1"
    )
    printed = "\n".join(" ".join(x[0]) for x in mocked_print.call_args_list)
    assert expected == printed


def test_stats_output_json(fake_stats, tmp_path):
    output_file = tmp_path / "json.out"
    reporter = StatsReporter(fake_stats, 5)
    reporter.render(json_output_file=output_file)
    expected = {
        "total_num_allocations": 20,
        "total_bytes_allocated": 3341500,
        "allocation_size_histogram": [
            {"min_bytes": 0, "max_bytes": 4738, "count": 1},
            {"min_bytes": 4739, "max_bytes": 8985, "count": 0},
            {"min_bytes": 8986, "max_bytes": 17035, "count": 3},
            {"min_bytes": 17036, "max_bytes": 32298, "count": 0},
            {"min_bytes": 32299, "max_bytes": 61236, "count": 1},
            {"min_bytes": 61237, "max_bytes": 116098, "count": 1},
            {"min_bytes": 116099, "max_bytes": 220112, "count": 6},
            {"min_bytes": 220113, "max_bytes": 417311, "count": 0},
            {"min_bytes": 417312, "max_bytes": 791180, "count": 0},
            {"min_bytes": 791181, "max_bytes": 1500000, "count": 2},
        ],
        "allocator_type_distribution": {
            "MALLOC": 1013,
            "REALLOC": 797,
            "CALLOC": 152,
            "MMAP": 4,
        },
        "top_allocations_by_size": [
            {"location": "fake_func:fake.py:5", "size": 5242880},
            {"location": "fake_func2:fake.py:10", "size": 3072},
            {"location": "__main__:fake.py:15", "size": 4},
        ],
        "top_allocations_by_count": [
            {"location": "fake_func:fake.py:5", "count": 20},
            {"location": "fake_func2:fake.py:10", "count": 50},
            {"location": "__main__:fake.py:15", "count": 1},
        ],
        "metadata": {
            "start_time": "2023-01-01 01:00:00",
            "end_time": "2023-01-01 02:00:00",
            "total_allocations": 3341500,
            "total_frames": 10,
            "peak_memory": 1500000,
            "command_line": "fake stats",
            "pid": 123456,
            "python_allocator": "pymalloc",
            "has_native_traces": False,
        },
    }
    actual = json.loads(output_file.read_text())
    assert expected == actual
