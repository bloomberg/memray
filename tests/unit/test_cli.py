import argparse
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from memray import FileDestination
from memray import SocketDestination
from memray.commands import main
from memray.commands.flamegraph import FlamegraphCommand
from memray.commands.run import RunCommand
from memray.commands.stats import StatsCommand
from memray.commands.summary import SummaryCommand
from memray.commands.table import TableCommand
from memray.commands.transform import TransformCommand
from memray.commands.tree import TreeCommand


def test_no_args_passed(capsys):
    with pytest.raises(SystemExit):
        main([])

    captured = capsys.readouterr()
    assert "usage:" in captured.err
    assert "error: the following arguments are required:" in captured.err


@patch.object(RunCommand, "validate_target_file")
@patch("memray.commands.run.Tracker")
@patch("memray.commands.run.runpy")
@patch("memray.commands.run.os.getpid")
class TestRunSubCommand:
    def test_run_without_arguments(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock, capsys
    ):
        with pytest.raises(SystemExit):
            main(["run"])

        captured = capsys.readouterr()
        assert "usage: memray run [-m module | -c cmd | file] [args]" in captured.err

    def test_run_default_output(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock
    ):
        getpid_mock.return_value = 0
        assert 0 == main(["run", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with(
            destination=FileDestination("memray-foobar.0.bin", overwrite=False),
            native_traces=False,
        )

    def test_run_with_native_mode(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock
    ):
        getpid_mock.return_value = 0
        assert 0 == main(["run", "--native", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with(
            destination=FileDestination("memray-foobar.0.bin", overwrite=False),
            native_traces=True,
        )

    def test_run_with_pymalloc_tracing(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock
    ):
        getpid_mock.return_value = 0
        assert 0 == main(["run", "--trace-python-allocators", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with(
            destination=FileDestination("memray-foobar.0.bin", overwrite=False),
            native_traces=False,
            trace_python_allocators=True,
        )

    def test_run_override_output(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock
    ):
        assert 0 == main(["run", "--output", "my_output", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with(
            destination=FileDestination("my_output", overwrite=False),
            native_traces=False,
        )

    def test_run_overwrite_output_file(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock
    ):
        assert 0 == main(["run", "-o", "my_output", "-f", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with(
            destination=FileDestination("my_output", overwrite=True),
            native_traces=False,
        )

    def test_run_module(self, getpid_mock, runpy_mock, tracker_mock, validate_mock):
        assert 0 == main(["run", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )

    def test_run_cmd_is_validated(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock
    ):
        with patch.object(RunCommand, "validate_target_file"):
            assert 0 == main(["run", "-c", "x = [i for i in range(10)]"])
            with pytest.raises(SyntaxError):
                main(["run", "-c", "[i for i in range(10)"])

    def test_run_cmd(self, getpid_mock, runpy_mock, tracker_mock, validate_mock):
        with patch("memray.commands.run.exec") as mock_exec:
            assert 0 == main(["run", "-c", "x = 10; y = abs(-10)"])
            assert not runpy_mock.called
            mock_exec.assert_called_with(
                "x = 10; y = abs(-10)", {"__name__": "__main__"}
            )

    def test_run_file(self, getpid_mock, runpy_mock, tracker_mock, validate_mock):
        with patch.object(RunCommand, "validate_target_file"):
            assert 0 == main(["run", "foobar.py", "arg1", "arg2"])
        runpy_mock.run_path.assert_called_with("foobar.py", run_name="__main__")

    def test_run_relative_file(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock
    ):
        getpid_mock.return_value = 0
        with patch.object(RunCommand, "validate_target_file"):
            assert 0 == main(["run", "./directory/foobar.py", "arg1", "arg2"])
        runpy_mock.run_path.assert_called_with(
            "./directory/foobar.py",
            run_name="__main__",
        )
        tracker_mock.assert_called_with(
            destination=FileDestination(
                "./directory/memray-foobar.py.0.bin", overwrite=False
            ),
            native_traces=False,
        )

    @patch("memray.commands.run.subprocess.Popen")
    @patch("memray.commands.run.LiveCommand")
    def test_run_with_live(
        self,
        live_command_mock,
        popen_mock,
        getpid_mock,
        runpy_mock,
        tracker_mock,
        validate_mock,
    ):
        getpid_mock.return_value = 0
        popen_mock().__enter__().returncode = 0
        with patch("memray.commands.run._get_free_port", return_value=1234):
            assert 0 == main(["run", "--live", "./directory/foobar.py", "arg1", "arg2"])
        popen_mock.assert_called_with(
            [
                sys.executable,
                "-c",
                "from memray.commands.run import _child_process;"
                "_child_process(1234,False,False,False,False,False,"
                "'./directory/foobar.py',['arg1', 'arg2'])",
            ],
            stderr=-1,
            stdout=-3,
            text=True,
        )
        live_command_mock().start_live_interface.assert_called_with(
            1234,
            cmdline_override="./directory/foobar.py arg1 arg2",
        )

    @patch("memray.commands.run.subprocess.Popen")
    @patch("memray.commands.run.LiveCommand")
    def test_run_with_live_and_trace_python_allocators(
        self,
        live_command_mock,
        popen_mock,
        getpid_mock,
        runpy_mock,
        tracker_mock,
        validate_mock,
    ):
        getpid_mock.return_value = 0
        popen_mock().__enter__().returncode = 0
        with patch("memray.commands.run._get_free_port", return_value=1234):
            assert 0 == main(
                [
                    "run",
                    "--live",
                    "--trace-python-allocators",
                    "./directory/foobar.py",
                    "arg1",
                    "arg2",
                ]
            )
        popen_mock.assert_called_with(
            [
                sys.executable,
                "-c",
                "from memray.commands.run import _child_process;"
                "_child_process(1234,False,True,False,False,False,"
                "'./directory/foobar.py',['arg1', 'arg2'])",
            ],
            stderr=-1,
            stdout=-3,
            text=True,
        )
        live_command_mock().start_live_interface.assert_called_with(
            1234,
            cmdline_override="./directory/foobar.py arg1 arg2",
        )

    def test_run_with_live_remote(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock
    ):
        getpid_mock.return_value = 0
        with patch("memray.commands.run._get_free_port", return_value=1234):
            assert 0 == main(
                ["run", "--live-remote", "./directory/foobar.py", "arg1", "arg2"]
            )
        runpy_mock.run_path.assert_called_with(
            "./directory/foobar.py",
            run_name="__main__",
        )
        tracker_mock.assert_called_with(
            destination=SocketDestination(server_port=1234, address="127.0.0.1"),
            native_traces=False,
        )

    def test_run_with_live_remote_and_live_port(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock
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
            destination=SocketDestination(server_port=1111, address="127.0.0.1"),
            native_traces=False,
        )

    def test_run_with_live_port_but_not_live_remote(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock, capsys
    ):
        with pytest.raises(SystemExit):
            main(["run", "--live-port", "1234", "./directory/foobar.py"])

        captured = capsys.readouterr()
        assert "The --live-port argument requires --live-remote" in captured.err

    def test_run_with_follow_fork(
        self,
        getpid_mock,
        runpy_mock,
        tracker_mock,
        validate_mock,
    ):
        getpid_mock.return_value = 0
        assert 0 == main(["run", "--follow-fork", "-m", "foobar"])
        runpy_mock.run_module.assert_called_with(
            "foobar", run_name="__main__", alter_sys=True
        )
        tracker_mock.assert_called_with(
            destination=FileDestination("memray-foobar.0.bin", overwrite=False),
            native_traces=False,
            follow_fork=True,
        )

    def test_run_with_follow_fork_and_live_mode(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock, capsys
    ):
        with pytest.raises(SystemExit):
            main(["run", "--live", "--follow-fork", "./directory/foobar.py"])

        captured = capsys.readouterr()
        assert "--follow-fork cannot be used with" in captured.err

    def test_run_with_follow_fork_and_live_remote_mode(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock, capsys
    ):
        with pytest.raises(SystemExit):
            main(["run", "--live-remote", "--follow-fork", "./directory/foobar.py"])

        captured = capsys.readouterr()
        assert "--follow-fork cannot be used with" in captured.err

    def test_run_with_trace_python_allocators_and_live_remote_mode(
        self, getpid_mock, runpy_mock, tracker_mock, validate_mock, capsys
    ):
        getpid_mock.return_value = 0
        with patch("memray.commands.run._get_free_port", return_value=1234):
            assert 0 == main(
                [
                    "run",
                    "--live-remote",
                    "--trace-python-allocators",
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
            destination=SocketDestination(server_port=1234, address="127.0.0.1"),
            native_traces=False,
            trace_python_allocators=True,
        )


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
        ("result.bin", "memray-flamegraph-result.html", FlamegraphCommand),
        ("/tmp/result.bin", "/tmp/memray-flamegraph-result.html", FlamegraphCommand),
        ("../result.bin", "../memray-flamegraph-result.html", FlamegraphCommand),
        (
            "memray-json.tool.0.bin",
            "memray-flamegraph-json.tool.0.html",
            FlamegraphCommand,
        ),
        (
            "/tmp/memray-json.tool.0.bin",
            "/tmp/memray-flamegraph-json.tool.0.html",
            FlamegraphCommand,
        ),
        (
            "../memray-json.tool.0.bin",
            "../memray-flamegraph-json.tool.0.html",
            FlamegraphCommand,
        ),
        ("memray-json.tool.0.bin", "memray-table-json.tool.0.html", TableCommand),
        ("my-result.bin", "memray-table-my-result.html", TableCommand),
        ("../my-result.bin", "../memray-table-my-result.html", TableCommand),
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
        assert namespace.biggest_allocs == 200

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


class TestSummarySubCommand:
    @staticmethod
    def get_prepared_parser():
        parser = argparse.ArgumentParser()
        command = SummaryCommand()
        command.prepare_parser(parser)

        return command, parser

    def test_parser_rejects_no_arguments(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN / THEN
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_parser_accepts_single_argument(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.sort_column == 1
        assert namespace.max_rows is None

    def test_parser_accepts_sort_column_long_form(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "--sort-column", "2"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.sort_column == 2
        assert namespace.max_rows is None

    def test_parser_accepts_sort_column_sort_form(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "-s", "2"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.sort_column == 2
        assert namespace.max_rows is None

    @pytest.mark.parametrize("column", [0, 12])
    def test_parser_rejects_sort_column_incorrect_values(self, column):
        # GIVEN
        command, parser = self.get_prepared_parser()

        # WHEN
        args = parser.parse_args(["results.txt", "--sort-column", str(column)])
        # THEN
        with pytest.raises(SystemExit):
            command.run(args, parser)

    def test_parser_accepts_max_rows_long_form(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "--max-rows", "2"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.sort_column == 1
        assert namespace.max_rows == 2

    def test_parser_accepts_max_rows_sort_form(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt", "-r", "2"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.sort_column == 1
        assert namespace.max_rows == 2


class TestStatsSubCommand:
    @staticmethod
    def get_prepared_parser():
        parser = argparse.ArgumentParser()
        command = StatsCommand()
        command.prepare_parser(parser)

        return command, parser

    def test_parser_rejects_no_arguments(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN / THEN
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_parser_accepts_single_argument(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.num_largest == 5

    def test_parser_accepts_valid_num_largest_allocators(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["-n", "3", "results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.num_largest == 3

    def test_parser_rejects_invalid_num_largest_allocators(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN / THEN
        with pytest.raises(SystemExit):
            parser.parse_args(["-n", "-1", "results.txt"])


class TestTransformSubCommand:
    @staticmethod
    def get_prepared_parser():
        parser = argparse.ArgumentParser()
        command = TransformCommand()
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
            parser.parse_args(["gprof2dot", "--leaks"])

    def test_parser_invalid_format(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN / THEN
        with pytest.raises(SystemExit):
            parser.parse_args(["blech"])

    def test_parser_accepts_single_argument_with_format(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["gprof2dot", "results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.format == "gprof2dot"
        assert namespace.show_memory_leaks is False

    def test_parser_accepts_short_form_output_1(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["gprof2dot", "results.txt", "-o", "output.html"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False
        assert namespace.format == "gprof2dot"

    def test_parser_accepts_short_form_output_2(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(["gprof2dot", "-o", "output.html", "results.txt"])

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False
        assert namespace.format == "gprof2dot"

    def test_parser_accepts_long_form_output_1(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(
            ["gprof2dot", "results.txt", "--output", "output.html"]
        )

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False
        assert namespace.format == "gprof2dot"

    def test_parser_accepts_long_form_output_2(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(
            ["gprof2dot", "--output", "output.html", "results.txt"]
        )

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is False
        assert namespace.format == "gprof2dot"

    def test_parser_takes_memory_leaks_as_a_flag(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(
            ["gprof2dot", "results.txt", "--leaks", "--output", "output.html"]
        )

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.show_memory_leaks is True
        assert namespace.format == "gprof2dot"

    def test_parser_takes_force_flag(self):
        # GIVEN
        _, parser = self.get_prepared_parser()

        # WHEN
        namespace = parser.parse_args(
            ["gprof2dot", "results.txt", "--force", "--output", "output.html"]
        )

        # THEN
        assert namespace.results == "results.txt"
        assert namespace.output == "output.html"
        assert namespace.force is True
        assert namespace.format == "gprof2dot"
