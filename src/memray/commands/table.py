from ..reporters.table import TableReporter
from .common import HighWatermarkCommand


class TableCommand(HighWatermarkCommand):
    def __init__(self) -> None:
        super().__init__(
            reporter_factory=TableReporter.from_snapshot,
            reporter_name="table",
        )
