from unittest.mock import patch

import pytest

from bloomberg.pensieve.__main__ import main


def test_no_args_passed(capsys):
    with pytest.raises(SystemExit):
        main([])

    captured = capsys.readouterr()
    assert "usage:" in captured.err
    assert "error: the following arguments are required:" in captured.err


@patch("bloomberg.pensieve.commands.run.Tracker")
@patch("bloomberg.pensieve.commands.run.runpy")
@patch("bloomberg.pensieve.commands.run.os.getpid")
class TestRunSubCommand:
    def test_run_without_arguments(self, getpid_mock, runpy_mock, tracker_mock, capsys):
        with pytest.raises(SystemExit):
            main(["run"])

        captured = capsys.readouterr()
        assert "error: the following arguments are required: module" in captured.err

    def test_run_default_output(self, getpid_mock, runpy_mock, tracker_mock):
        getpid_mock.return_value = 0
        assert 0 == main(["run", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with("foobar.0.out")

    def test_run_override_output(self, getpid_mock, runpy_mock, tracker_mock):
        assert 0 == main(["run", "--output", "my_output", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with("my_output")
