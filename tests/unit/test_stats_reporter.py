from collections import Counter
from typing import List
from typing import Optional
from typing import Tuple

import pytest

from memray import AllocatorType as AT
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
):
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
