from typing import List
from typing import Tuple

import pytest

from bloomberg.pensieve import AllocatorType as AT
from bloomberg.pensieve.reporters.stats import draw_histogram
from bloomberg.pensieve.reporters.stats import get_allocator_type_distribution
from bloomberg.pensieve.reporters.stats import get_histogram_databins
from bloomberg.pensieve.reporters.stats import get_stats_data
from bloomberg.pensieve.reporters.stats import get_top_allocations_by_count
from bloomberg.pensieve.reporters.stats import get_top_allocations_by_size
from tests.utils import MockAllocationRecord


# data generator for tests
def _generate_mock_allocations(
    count: int,
    sizes: List[int] = [],
    allocators: List[AT] = [],
    n_allocations: List[int] = [],
    stacks: List[List[Tuple[str, str, int]]] = [],
):
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


# tests begin here
def test_allocator_type_distribution():
    # GIVEN
    mag = _generate_mock_allocations(
        7,
        allocators=[
            AT.MALLOC,
            AT.CALLOC,
            AT.MALLOC,
            AT.MMAP,
            AT.FREE,
            AT.MUNMAP,
            AT.FREE,
        ],
    )  # contains FREE and MUNMAP
    shdata = get_stats_data(mag)
    expected_output = [
        "MALLOC: 2",
        "CALLOC: 1",
        "MMAP: 1",
    ]  # does not contain FREE and MUNMAP, but has the others
    actual_output = []

    # WHEN
    for entry in get_allocator_type_distribution(shdata.allocation_type_counter):
        actual_output.append(entry)

    # THEN
    assert expected_output == actual_output


def test_allocator_type_distribution_no_allocators():
    # GIVEN
    mag = _generate_mock_allocations(0, allocators=[])
    shdata = get_stats_data(mag)
    expected_output = []
    actual_output = []

    # WHEN
    for entry in get_allocator_type_distribution(shdata.allocation_type_counter):
        actual_output.append(entry)

    # THEN
    assert expected_output == actual_output


def test_top_allocations_by_size():
    # GIVEN
    mag = _generate_mock_allocations(
        4,
        sizes=[1024, 2048, 3072, 4096],
        stacks=[
            [("first", "f1.py", 1)],
            [("second", "f2.py", 2)],
            [("third", "f3.py", 3)],
            [("fourth", "f4.py", 4)],
        ],
    )

    expected_output = [
        "fourth:f4.py:4 -> 4.000KB",
        "third:f3.py:3 -> 3.000KB",
        "second:f2.py:2 -> 2.000KB",
    ]  # no "1" since we asked only for largest 3
    actual_output = []

    # WHEN
    for entry in get_top_allocations_by_size(mag, num_largest=3):
        actual_output.append(entry)

    assert expected_output == actual_output


def test_top_allocations_by_size_unavailable_strace():
    # GIVEN
    mag = _generate_mock_allocations(
        4,
        sizes=[1024, 2048, 3072, 4096],
        stacks=[
            [("first", "f1.py", 1)],
            [("second", "f2.py", 2)],
            [],  # missing stack trace
            [("fourth", "f4.py", 4)],
        ],
    )

    expected_output = [
        "fourth:f4.py:4 -> 4.000KB",
        "<stack trace unavailable> -> 3.000KB",
        "second:f2.py:2 -> 2.000KB",
    ]  # no "1" since we asked only for largest 3
    actual_output = []

    # WHEN
    for entry in get_top_allocations_by_size(mag, num_largest=3):
        actual_output.append(entry)

    assert expected_output == actual_output


def test_top_allocations_by_count():
    # GIVEN
    mag = _generate_mock_allocations(
        4,
        n_allocations=[11, 22, 33, 44],
        stacks=[
            [("first", "f1.py", 1)],
            [("second", "f2.py", 2)],
            [("third", "f3.py", 3)],
            [("fourth", "f4.py", 4)],
        ],
    )

    expected_output = [
        "fourth:f4.py:4 -> 44",
        "third:f3.py:3 -> 33",
        "second:f2.py:2 -> 22",
    ]  # no "1" since we asked only for largest 3
    actual_output = []

    # WHEN
    for entry in get_top_allocations_by_count(mag, num_largest=3):
        actual_output.append(entry)

    assert expected_output == actual_output


def test_top_allocations_by_count_unavailable_strace():
    # GIVEN
    mag = _generate_mock_allocations(
        4,
        n_allocations=[11, 22, 33, 44],
        stacks=[
            [("first", "f1.py", 1)],
            [("second", "f2.py", 2)],
            [("third", "f3.py", 3)],
            [],
        ],
    )

    expected_output = [
        "<stack trace unavailable> -> 44",
        "third:f3.py:3 -> 33",
        "second:f2.py:2 -> 22",
    ]  # no "1" since we asked only for largest 3
    actual_output = []

    # WHEN
    for entry in get_top_allocations_by_count(mag, num_largest=3):
        actual_output.append(entry)

    assert expected_output == actual_output


def test_get_histogram_databins():
    # GIVEN
    input_data = [
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
    expected_output = [
        (8986, 1),
        (32299, 3),
        (116099, 2),
        (417312, 6),
        (1500000, 1),
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
    input_data = [
        32,
        1050856,
    ]
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


def test_get_histogram_databins_invalid_bins():
    with pytest.raises(ValueError):
        _ = get_histogram_databins([], bins=0)  # invalid bins value
    with pytest.raises(ValueError):
        _ = get_histogram_databins([], bins=-1)  # invalid bins value


def test_draw_histogram():
    # GIVEN
    input_data = [
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
    expected_output = """min: 2.441KB
\t----------------------------------------
\t< 8.775KB  : 1 ▇▇▇▇▇
\t< 31.542KB : 3 ▇▇▇▇▇▇▇▇▇▇▇▇▇
\t< 113.378KB: 2 ▇▇▇▇▇▇▇▇▇
\t< 407.531KB: 6 ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇
\t<=1.431MB  : 1 ▇▇▇▇▇
\t----------------------------------------
\tmax: 1.431MB"""

    # WHEN
    actual_output = draw_histogram(input_data, bins=5)

    # THEN
    assert expected_output == actual_output


def test_draw_histogram_smaller_scale_factor():
    # GIVEN
    input_data = [
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

    expected_output = """min: 2.441KB
\t--------------------
\t< 8.775KB  : 1 ▇
\t< 31.542KB : 3 ▇▇▇
\t< 113.378KB: 2 ▇▇
\t< 407.531KB: 6 ▇▇▇▇▇
\t<=1.431MB  : 1 ▇
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
    input_data = []
    actual_output = draw_histogram(input_data, bins=5)
    assert "<no data for histogram>" == actual_output

    # test#2 - Invalid bins value
    with pytest.raises(ValueError):
        _ = draw_histogram([100, 200, 300], bins=0)

    # test#3 - Invalid hist_scale_factor value
    with pytest.raises(ValueError):
        _ = draw_histogram([100, 200, 300], bins=5, hist_scale_factor=0)
