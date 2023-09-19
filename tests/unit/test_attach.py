from unittest.mock import patch

import pytest

from memray.commands import main


@patch("memray.commands.attach.debugger_available")
class TestAttachSubCommand:
    def test_memray_attach_aggregated_without_output_file(
        self, is_debugger_available_mock, capsys
    ):
        # GIVEN
        is_debugger_available_mock.return_value = True

        # WHEN
        with pytest.raises(SystemExit):
            main(["attach", "--aggregate", "1234"])

        captured = capsys.readouterr()
        assert "Can't use aggregated mode without an output file." in captured.err
