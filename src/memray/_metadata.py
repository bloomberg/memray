from dataclasses import dataclass
from datetime import datetime


@dataclass
class Metadata:
    start_time: datetime
    end_time: datetime
    total_allocations: int
    total_frames: int
    peak_memory: int
    command_line: str
    pid: int
    python_allocator: str
    has_native_traces: bool
