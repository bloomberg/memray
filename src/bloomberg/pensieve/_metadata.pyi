from datetime import datetime

class Metadata:
    start_time: datetime
    end_time: datetime
    total_allocations: int
    total_frames: int
    peak_memory: int
    command_line: str
