from typing import Union

from memray._memray import AllocationRecord
from memray._memray import TemporalAllocationRecord


def format_thread_name(
    record: Union[AllocationRecord, TemporalAllocationRecord]
) -> str:
    if record.tid == -1:
        return "merged thread"
    name = record.thread_name
    thread_id = hex(record.tid)
    return f"{thread_id} ({name})" if name else f"{thread_id}"
