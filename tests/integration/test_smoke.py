import logging
import mmap

from bloomberg.pensieve import tracker


def test_smoke(caplog):
    caplog.set_level(logging.INFO)
    with tracker():
        with mmap.mmap(-1, length=2048, access=mmap.ACCESS_WRITE) as mmap_obj:
            mmap_obj[0:100] = b"a" * 100
    assert any("mmap64" in record.message for record in caplog.records)
    assert any("munmap" in record.message for record in caplog.records)
