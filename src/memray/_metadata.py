from dataclasses import dataclass
from datetime import datetime

from ._memray import FileFormat


@dataclass
class Metadata:
    start_time: datetime
    end_time: datetime
    total_allocations: int
    total_frames: int
    peak_memory: int
    command_line: str
    pid: int
    main_thread_id: int
    python_allocator: str
    has_native_traces: bool
    trace_python_allocators: bool
    file_format: FileFormat
