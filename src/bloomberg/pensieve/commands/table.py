from typing import cast

from ..reporters.table import TableReporter
from .common import HighWatermarkCommand
from .common import ReporterFactory


class TableCommand(HighWatermarkCommand):
    """Generate an HTML table with all records in the peak memory usage."""

    def __init__(self) -> None:
        super().__init__(
            reporter_factory=cast(ReporterFactory, TableReporter.from_snapshot),
            reporter_name="table",
        )
