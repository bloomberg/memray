import subprocess
import sys

import pytest

from memray import AllocatorType
from memray import FileReader

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Arrow hooks use ELF interposition"
)


PYARROW_TEST = """
import sys

from memray import Tracker

output, load_timing = sys.argv[1:]

if load_timing == "before_tracking":
    import pyarrow
elif load_timing == "between_trackers":
    with Tracker(output + ".initial"):
        pass
    import pyarrow

with Tracker(output):
    if load_timing == "while_tracking":
        import pyarrow
    assert pyarrow.default_memory_pool().backend_name == "mimalloc"
    buffer = pyarrow.allocate_buffer(4096, resizable=True)
    allocated = buffer.address
    buffer.resize(8192)
    reallocated = buffer.address
    del buffer

print(allocated, reallocated)
"""


@pytest.mark.parametrize(
    "load_timing", ["before_tracking", "while_tracking", "between_trackers"]
)
def test_tracks_pyarrow_mimalloc_buffers(tmp_path, load_timing):
    pytest.importorskip("pyarrow", minversion="25.0.0")
    output = tmp_path / "test.bin"

    result = subprocess.run(
        [sys.executable, "-c", PYARROW_TEST, output, load_timing],
        check=True,
        capture_output=True,
        text=True,
    )

    allocated, reallocated = map(int, result.stdout.split())
    addresses = {allocated, reallocated}
    records = [
        (record.address, record.size, record.allocator)
        for record in FileReader(output).get_allocation_records()
        if record.address in addresses
    ]
    assert records == [
        (allocated, 4096, AllocatorType.ALIGNED_ALLOC),
        (allocated, 0, AllocatorType.FREE),
        (reallocated, 8192, AllocatorType.REALLOC),
        (reallocated, 0, AllocatorType.FREE),
    ]
