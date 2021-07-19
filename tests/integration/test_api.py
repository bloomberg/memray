import pytest

from bloomberg.pensieve import FileReader
from bloomberg.pensieve import Tracker
from bloomberg.pensieve._test import MemoryAllocator


def test_file_reader_as_context_manager(tmp_path):
    # GIVEN
    allocator = MemoryAllocator()
    result_file = tmp_path / "test.bin"
    # WHEN
    with Tracker(result_file):
        allocator.valloc(1234)
        allocator.free()

    # THEN
    with FileReader(result_file) as reader:
        pass

    with pytest.raises(ValueError, match="Operation on a closed FileReader"):
        list(reader.get_high_watermark_allocation_records())
