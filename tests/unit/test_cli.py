from unittest.mock import patch

import pytest

from bloomberg.pensieve.__main__ import main


def test_no_args_passed(capsys):
    with pytest.raises(SystemExit):
        main([])

    captured = capsys.readouterr()
    assert "usage:" in captured.err
    assert "error: the following arguments are required:" in captured.err


@patch("bloomberg.pensieve.__main__.Tracker")
@patch("bloomberg.pensieve.__main__.runpy")
@patch("bloomberg.pensieve.__main__.os.getpid")
class TestRunSubCommand:
    def test_run_default_output(self, getpid_mock, runpy_mock, tracker_mock):
        getpid_mock.return_value = 0
        assert 0 == main(["pensieve", "run", "foobar"])
        runpy_mock.run_module.assert_called_with("foobar", run_name="__main__")
        tracker_mock.assert_called_with("foobar.0.out")

    def test_run_override_output(self, getpid_mock, runpy_mock, tracker_mock):
        assert 0 == main(["pensieve", "run", "--output", "my_output", "foobar"])
        runpy_mock.run_module.assert_called_with("foobar", run_name="__main__")
        tracker_mock.assert_called_with("my_output")
