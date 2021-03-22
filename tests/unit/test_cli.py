import argparse
from unittest.mock import patch

import pytest

from bloomberg.pensieve.__main__ import main
from bloomberg.pensieve.commands import flamegraph


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
        assert "usage: pensieve run [-m module | file] [args]" in captured.err

    def test_run_default_output(self, getpid_mock, runpy_mock, tracker_mock):
        getpid_mock.return_value = 0
        assert 0 == main(["run", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with("foobar.0.bin")

    def test_run_override_output(self, getpid_mock, runpy_mock, tracker_mock):
        assert 0 == main(["run", "--output", "my_output", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with("my_output")

    def test_run_module(self, getpid_mock, runpy_mock, tracker_mock):
        assert 0 == main(["run", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )

    def test_run_file(self, getpid_mock, runpy_mock, tracker_mock):
        assert 0 == main(["run", "foobar.py", "arg1", "arg2"])
        runpy_mock.run_path.assert_called_with("foobar.py", run_name="__main__")


class TestFlamegraphSubCommand:
    @staticmethod
    def get_prepared_parser():
        parser = argparse.ArgumentParser()
        command = flamegraph.FlamegraphCommand()
        command.prepare_parser(parser)

        return command, parser

    def test_parser_rejects_no_arguments(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN / THEN
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_parser_rejects_when_no_results_provided(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN / THEN
        with pytest.raises(SystemExit):
            parser.parse_args(["--output", "output.html"])

    def test_parser_accepts_single_argument(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "pensieve-flamegraph.html"

    def test_parser_accepts_short_form_output_1(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "-o", "output.html"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"

    def test_parser_accepts_short_form_output_2(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["-o", "output.html", "results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"

    def test_parser_accepts_long_form_output_1(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "--output", "output.html"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"

    def test_parser_accepts_long_form_output_2(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["--output", "output.html", "results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
