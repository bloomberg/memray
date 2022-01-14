import argparse
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bloomberg.pensieve import FileDestination
from bloomberg.pensieve import SocketDestination
from bloomberg.pensieve.__main__ import main
from bloomberg.pensieve.commands.flamegraph import FlamegraphCommand
from bloomberg.pensieve.commands.table import TableCommand
from bloomberg.pensieve.commands.tree import TreeCommand


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
        tracker_mock.assert_called_with(
            destination=FileDestination("pensieve-foobar.0.bin", exist_ok=False),
            native_traces=False,
        )

    def test_run_with_native_mode(self, getpid_mock, runpy_mock, tracker_mock):
        getpid_mock.return_value = 0
        assert 0 == main(["run", "--native", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with(
            destination=FileDestination("pensieve-foobar.0.bin", exist_ok=False),
            native_traces=True,
        )

    def test_run_override_output(self, getpid_mock, runpy_mock, tracker_mock):
        assert 0 == main(["run", "--output", "my_output", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with(
            destination=FileDestination("my_output", exist_ok=False),
            native_traces=False,
        )

    def test_run_overwrite_output_file(self, getpid_mock, runpy_mock, tracker_mock):
        assert 0 == main(["run", "-o", "my_output", "-f", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with(
            destination=FileDestination("my_output", exist_ok=True),
            native_traces=False,
        )

    def test_run_module(self, getpid_mock, runpy_mock, tracker_mock):
        assert 0 == main(["run", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )

    def test_run_file(self, getpid_mock, runpy_mock, tracker_mock):
        assert 0 == main(["run", "foobar.py", "arg1", "arg2"])
        runpy_mock.run_path.assert_called_with("foobar.py", run_name="__main__")

    def test_run_relative_file(self, getpid_mock, runpy_mock, tracker_mock):
        getpid_mock.return_value = 0
        assert 0 == main(["run", "./directory/foobar.py", "arg1", "arg2"])
        runpy_mock.run_path.assert_called_with(
            "./directory/foobar.py",
            run_name="__main__",
        )
        tracker_mock.assert_called_with(
            destination=FileDestination(
                "./directory/pensieve-foobar.py.0.bin", exist_ok=False
            ),
            native_traces=False,
        )

    @patch("bloomberg.pensieve.commands.run.subprocess.Popen")
    @patch("bloomberg.pensieve.commands.run.LiveCommand")
    def test_run_with_live(
        self, live_command_mock, popen_mock, getpid_mock, runpy_mock, tracker_mock
    ):
        getpid_mock.return_value = 0
        popen_mock().__enter__().returncode = 0
        with patch("bloomberg.pensieve.commands.run._get_free_port", return_value=1234):
            assert 0 == main(["run", "--live", "./directory/foobar.py", "arg1", "arg2"])
        popen_mock.assert_called_with(
            [
                sys.executable,
                "-c",
                "from bloomberg.pensieve.commands.run import _child_process;"
                '_child_process(1234,False,False,False,"./directory/foobar.py",'
                "['arg1', 'arg2'])",
            ],
            stderr=-1,
            stdout=-3,
            text=True,
        )
        live_command_mock().start_live_interface.assert_called_with(1234)

    def test_run_with_live_remote(self, getpid_mock, runpy_mock, tracker_mock):
        getpid_mock.return_value = 0
        with patch("bloomberg.pensieve.commands.run._get_free_port", return_value=1234):
            assert 0 == main(
                ["run", "--live-remote", "./directory/foobar.py", "arg1", "arg2"]
            )
        runpy_mock.run_path.assert_called_with(
            "./directory/foobar.py",
            run_name="__main__",
        )
        tracker_mock.assert_called_with(
            destination=SocketDestination(port=1234, host="127.0.0.1"),
            native_traces=False,
        )

    def test_run_with_live_remote_and_live_port(
        self, getpid_mock, runpy_mock, tracker_mock
    ):
        getpid_mock.return_value = 0
        assert 0 == main(
            [
                "run",
                "--live-remote",
                "--live-port=1111",
                "./directory/foobar.py",
                "arg1",
                "arg2",
            ]
        )
        runpy_mock.run_path.assert_called_with(
            "./directory/foobar.py",
            run_name="__main__",
        )
        tracker_mock.assert_called_with(
            destination=SocketDestination(port=1111, host="127.0.0.1"),
            native_traces=False,
        )

    def test_run_with_live_port_but_not_live_remote(
        self, getpid_mock, runpy_mock, tracker_mock, capsys
    ):
        with pytest.raises(SystemExit):
            main(["run", "--live-port", "1234", "./directory/foobar.py"])

        captured = capsys.readouterr()
        assert "The --live-port argument requires --live-remote" in captured.err


class TestFlamegraphSubCommand:
    @staticmethod
    def get_prepared_parser():
        parser = argparse.ArgumentParser()
        command = FlamegraphCommand()
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
        assert namespace.output is None
        assert namespace.show_memory_leaks is False

    def test_parser_accepts_short_form_output_1(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "-o", "output.html"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False

    def test_parser_accepts_short_form_output_2(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["-o", "output.html", "results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False

    def test_parser_accepts_long_form_output_1(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "--output", "output.html"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False

    def test_parser_accepts_long_form_output_2(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["--output", "output.html", "results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False

    def test_parser_takes_memory_leaks_as_a_flag(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(
            ["results.txt", "--leaks", "--output", "output.html"]
        )

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is True

    def test_parser_takes_force_flag(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(
            ["results.txt", "--force", "--output", "output.html"]
        )

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.force is True


@pytest.mark.parametrize(
    "input, expected, factory",
    (
        ("result.bin", "pensieve-flamegraph-result.html", FlamegraphCommand),
        ("/tmp/result.bin", "/tmp/pensieve-flamegraph-result.html", FlamegraphCommand),
        ("../result.bin", "../pensieve-flamegraph-result.html", FlamegraphCommand),
        (
            "pensieve-json.tool.0.bin",
            "pensieve-flamegraph-json.tool.0.html",
            FlamegraphCommand,
        ),
        (
            "/tmp/pensieve-json.tool.0.bin",
            "/tmp/pensieve-flamegraph-json.tool.0.html",
            FlamegraphCommand,
        ),
        (
            "../pensieve-json.tool.0.bin",
            "../pensieve-flamegraph-json.tool.0.html",
            FlamegraphCommand,
        ),
        ("pensieve-json.tool.0.bin", "pensieve-table-json.tool.0.html", TableCommand),
        ("my-result.bin", "pensieve-table-my-result.html", TableCommand),
        ("../my-result.bin", "../pensieve-table-my-result.html", TableCommand),
    ),
)
def test_determine_output(input, expected, factory):
    # GIVEN
    command = factory()

    # WHEN/THEN
    assert command.determine_output_filename(Path(input)) == Path(expected)


class TestTreeSubCommand:
    @staticmethod
    def get_prepared_parser():
        parser = argparse.ArgumentParser()
        command = TreeCommand()
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
            parser.parse_args(["--biggest_allocs", "5"])

    def test_parser_accepts_single_argument(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.biggest_allocs == 10

    def test_parser_acceps_biggest_allocs_short_form(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "-b", "5"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.biggest_allocs == 5

    def test_parser_acceps_biggest_allocs_long_form(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "--biggest-allocs", "5"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.biggest_allocs == 5


class TestTableSubCommand:
    @staticmethod
    def get_prepared_parser():
        parser = argparse.ArgumentParser()
        command = TableCommand()
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
            parser.parse_args(["--leaks"])

    def test_parser_accepts_single_argument(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.show_memory_leaks is False

    def test_parser_accepts_short_form_output_1(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "-o", "output.html"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False

    def test_parser_accepts_short_form_output_2(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["-o", "output.html", "results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False

    def test_parser_accepts_long_form_output_1(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "--output", "output.html"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False

    def test_parser_accepts_long_form_output_2(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["--output", "output.html", "results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False

    def test_parser_takes_memory_leaks_as_a_flag(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(
            ["results.txt", "--leaks", "--output", "output.html"]
        )

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is True

    def test_parser_takes_force_flag(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(
            ["results.txt", "--force", "--output", "output.html"]
        )

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.force is True
