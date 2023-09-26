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
        print("Error", captured.err)
        assert "Can't use aggregated mode without an output file." in captured.err


class TestAttachSubCommandOptions:
    @pytest.mark.parametrize(
        "arg1,arg2",
        [
            ("--heap-limit=10", "--duration=10"),
        ],
    )
    def test_memray_attach_stop_tracking_option_with_other_mode_options(
        self, arg1, arg2, capsys
    ):
        # WHEN
        with pytest.raises(SystemExit):
            main(["attach", "1234", arg1, arg2])

        captured = capsys.readouterr()
        arg1_name = arg1.split("=")[0]
        arg2_name = arg2.split("=")[0]
        assert (
            f"argument {arg2_name}: not allowed with argument {arg1_name}"
            in captured.err
        )
