import contextlib
import os
import platform
import pty
import re
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from memray.commands import main

TIMEOUT = 10


@pytest.fixture
def simple_test_file(tmp_path):
    code_file = tmp_path / "code.py"
    program = textwrap.dedent(
        """\
        from memray._test import MemoryAllocator
        print("Allocating some memory!")
        allocator = MemoryAllocator()
        allocator.valloc(1024)
        allocator.free()
        """
    )
    code_file.write_text(program)
    yield code_file


@pytest.fixture
def test_file_returns_from_fork(tmp_path):
    code_file = tmp_path / "code.py"
    program = textwrap.dedent(
        """\
        import os
        os.fork()
        """
    )
    code_file.write_text(program)
    yield code_file


@contextlib.contextmanager
def track_and_wait(output_dir, sleep_after=100):
    """Creates a test script which does some allocations, and upon leaving the context manager,
    it blocks until the allocations have completed."""

    fifo = output_dir / "snapshot_taken.event"
    os.mkfifo(fifo)

    program = textwrap.dedent(
        f"""\
        import time
        from memray._test import MemoryAllocator
        allocator = MemoryAllocator()
        allocator.valloc(1024)
        allocator.free()
        with open("{fifo}", "w") as fifo:
            fifo.write("done")
        time.sleep({sleep_after})
        """
    )
    program_file = output_dir / "file.py"
    program_file.write_text(program)
    yield program_file

    # Wait until we are tracking
    with open(fifo, "r") as f:
        assert f.read() == "done"


def _wait_until_process_blocks(pid: int) -> None:
    if "linux" not in sys.platform:
        time.sleep(1.0)
        return
    # Signal numbers from https://filippo.io/linux-syscall-table/
    arch = platform.machine()
    if arch == "x86_64":
        sleep_syscall = "35"
        connect_syscall = "42"
        accept_syscall = "43"
        clock_nanosleep = "230"
    elif arch == "aarch64":
        sleep_syscall = "101"
        connect_syscall = "203"
        accept_syscall = "202"
        clock_nanosleep = "115"
    else:
        # No idea what syscalls numbers to wait on, so we will just
        # sleep for a long enough period and hope for the best
        time.sleep(1.0)
        return
    syscalls_to_wait = {sleep_syscall, clock_nanosleep, connect_syscall, accept_syscall}
    current_syscall = ""
    while True:
        syscall = Path(f"/proc/{pid}/syscall")
        current_syscall, *_ = syscall.read_text().split()
        if current_syscall.strip() in syscalls_to_wait:
            return
        time.sleep(0.1)


def generate_sample_results(tmp_path, code, *, native=False):
    results_file = tmp_path / "result.bin"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "memray",
            "run",
            *(["--native"] if native else []),
            "--output",
            str(results_file),
            str(code),
        ],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    )
    return results_file, code


class TestRunSubcommand:
    def test_run(self, tmp_path, simple_test_file):
        # GIVEN / WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                str(simple_test_file),
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        # THEN
        assert "Allocating some memory!" in proc.stdout
        assert proc.returncode == 0
        assert "example commands" in proc.stdout

        out_file = re.search("Writing profile results into (.*)", proc.stdout).group(1)
        assert (tmp_path / out_file).exists()

    def test_run_override_output(self, tmp_path, simple_test_file):
        # GIVEN
        out_file = tmp_path / "result.bin"

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--output",
                str(out_file),
                str(simple_test_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert "Allocating some memory!" in proc.stdout
        assert proc.returncode == 0
        assert out_file.exists()

    def test_run_overwrite_output_file(self, tmp_path, simple_test_file):
        # GIVEN
        out_file = tmp_path / "result.bin"
        out_file.write_bytes(b"oops" * 1024 * 1024)
        assert out_file.stat().st_size == 4 * 1024 * 1024
        assert out_file.read_bytes()[:4] == b"oops"

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--force",
                "--output",
                str(out_file),
                str(simple_test_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert "Allocating some memory!" in proc.stdout
        assert proc.returncode == 0
        assert 0 < out_file.stat().st_size < 4 * 1024 * 1024
        assert out_file.read_bytes()[:4] != b"oops"

    def test_run_file_with_args(self, tmp_path):
        """Execute a Python script and make sure the arguments in the script
        are correctly forwarded."""

        # GIVEN
        out_file = tmp_path / "result.bin"
        target_file = tmp_path / "test.py"
        target_file.write_text(
            textwrap.dedent(
                """\
        import sys
        print(f"Command: {sys.argv[0]}")
        print(f"Arg: {sys.argv[1]}")
        """
            )
        )

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--output",
                str(out_file),
                str(target_file),
                "arg1",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert proc.returncode == 0
        assert re.search(r"Command: (.*)test\.py", proc.stdout)
        assert "Arg: arg1" in proc.stdout
        assert out_file.exists()

    def test_sys_manipulations_when_running_script(self, tmp_path):
        # GIVEN
        out_file = tmp_path / "result.bin"
        target_file = tmp_path / "test.py"
        target_file.write_text("import some_adjacent_module")
        other_file = tmp_path / "some_adjacent_module.py"
        other_file.write_text("import sys; print(sys.argv); print(sys.path[0])")

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--quiet",
                "--output",
                str(out_file),
                str(target_file),
                "some",
                "provided args",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert proc.returncode == 0
        argv, path0 = proc.stdout.splitlines()
        assert argv == repr([str(target_file), "some", "provided args"])
        assert path0 == str(tmp_path)
        assert out_file.exists()

    def test_sys_manipulations_when_running_module(self, tmp_path):
        # GIVEN
        out_file = tmp_path / "result.bin"
        target_file = tmp_path / "test.py"
        target_file.write_text("import some_adjacent_module")
        other_file = tmp_path / "some_adjacent_module.py"
        other_file.write_text("import sys; print(sys.argv); print(sys.path[0])")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(tmp_path) + ":" + os.environ.get("PYTHONPATH", "")

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--quiet",
                "--output",
                str(out_file),
                "-m",
                "test",
                "some",
                "provided args",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

        # THEN
        assert proc.returncode == 0
        argv, path0 = proc.stdout.splitlines()
        assert argv == repr([str(target_file), "some", "provided args"])
        assert path0 == os.getcwd()
        assert out_file.exists()

    def test_sys_manipulations_when_running_cmd(self, tmp_path):
        # GIVEN
        out_file = tmp_path / "result.bin"
        other_file = tmp_path / "some_adjacent_module.py"
        other_file.write_text("import sys; print(sys.argv); print(sys.path[0])")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(tmp_path) + ":" + os.environ.get("PYTHONPATH", "")

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--quiet",
                "--output",
                str(out_file),
                "-c",
                "import some_adjacent_module",
                "some",
                "provided args",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

        # THEN
        assert proc.returncode == 0
        argv, path0 = proc.stdout.splitlines()
        assert argv == repr(["-c", "some", "provided args"])
        assert path0 == ""
        assert out_file.exists()

    @pytest.mark.parametrize("option", [None, "--live", "--live-remote"])
    def test_run_file_that_is_not_python(self, capsys, option):
        """Execute a non-Python script and make sure that we raise a good error"""

        # GIVEN / WHEN
        assert main(["run", *([option] if option else ()), sys.executable]) == 1

        # THEN
        captured = capsys.readouterr()
        assert (
            captured.err.strip()
            == "Only valid Python files or commands can be executed under memray"
        )

    @patch("memray.commands.run.os.getpid")
    def test_run_file_exists(self, getpid, tmp_path, monkeypatch, capsys):
        # GIVEN / WHEN
        getpid.return_value = 0
        (tmp_path / "memray-json.tool.0.bin").touch()
        monkeypatch.chdir(tmp_path)

        # THEN
        assert main(["run", "-m", "json.tool", "-h"]) == 1
        captured = capsys.readouterr()
        assert (
            captured.err.strip()
            == "Could not create output file memray-json.tool.0.bin: File exists"
        )

    def test_run_output_file_directory_does_not_exist(self, capsys):
        # GIVEN / WHEN / THEN

        assert main(["run", "--output", "/doesn/t/exist", "-m", "json.tool", "-h"]) == 1
        captured = capsys.readouterr()
        assert (
            captured.err.strip()
            == "Could not create output file /doesn/t/exist: No such file or directory"
        )

    @pytest.mark.parametrize("quiet", [True, False])
    def test_quiet(self, quiet, tmp_path, simple_test_file):
        # GIVEN
        out_file = tmp_path / "result.bin"

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                *(["-q"] if quiet else []),
                "--output",
                str(out_file),
                str(simple_test_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert proc.returncode == 0
        assert out_file.exists()
        if quiet:
            assert str(out_file) not in proc.stdout
        else:
            assert str(out_file) in proc.stdout

    def test_not_quiet_and_fork(self, tmp_path, test_file_returns_from_fork):
        # GIVEN
        out_file = tmp_path / "result.bin"

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--output",
                str(out_file),
                str(test_file_returns_from_fork),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert proc.returncode == 0
        assert out_file.exists()
        assert proc.stdout.count("Some example commands to generate reports") == 1


class TestParseSubcommand:
    def test_successful_parse(self, tmp_path):
        # GIVEN
        record_types = [
            "ALLOCATION",
            "FRAME_PUSH",
            "FRAME_POP",
            "FRAME_ID",
            "MEMORY_RECORD",
            "CONTEXT_SWITCH",
            "TRAILER",
        ]
        if "linux" in sys.platform:
            record_types.extend(
                [
                    "MEMORY_MAP_START",
                    "SEGMENT_HEADER",
                    "SEGMENT",
                    "NATIVE_FRAME_ID",
                    "ALLOCATION_WITH_NATIVE",
                ]
            )

        code_file = tmp_path / "code.py"
        program = textwrap.dedent(
            """\
            import time
            from memray._test import MemoryAllocator
            print("Allocating some memory!")
            allocator = MemoryAllocator()
            allocator.valloc(1024)
            allocator.free()
            # Give it time to generate some memory records
            time.sleep(0.1)
            """
        )
        code_file.write_text(program)
        record_count_by_type = dict.fromkeys(record_types, 0)
        results_file, _ = generate_sample_results(
            tmp_path, code_file, native=(sys.platform != "darwin")
        )

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "parse",
                str(results_file),
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        # THEN
        _, *records = proc.stdout.splitlines()

        for record in records:
            record_count_by_type[record.partition(" ")[0]] += 1

        for _, count in record_count_by_type.items():
            assert count > 0

    def test_error_when_stdout_is_a_tty(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=(sys.platform != "darwin")
        )
        _, controlled = pty.openpty()

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "parse",
                str(results_file),
            ],
            stdout=controlled,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(tmp_path),
        )

        # THEN
        assert "You must redirect stdout" in proc.stderr
        assert proc.returncode == 1

    def test_error_when_input_file_does_not_exist(self, tmp_path):
        # GIVEN
        results_file = tmp_path / "does/not/exist"

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "parse",
                results_file,
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        # THEN
        assert "Reason: No such file" in proc.stderr
        assert proc.returncode == 1


class TestFlamegraphSubCommand:
    def test_reads_from_correct_file(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=(sys.platform != "darwin")
        )

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "flamegraph",
                str(results_file),
            ],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        output_file = tmp_path / "memray-flamegraph-result.html"
        assert output_file.exists()
        assert str(source_file) in output_file.read_text()

    def test_can_generate_reports_with_native_traces(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=(sys.platform != "darwin")
        )

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "flamegraph",
                str(results_file),
            ],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        output_file = tmp_path / "memray-flamegraph-result.html"
        assert output_file.exists()
        assert str(source_file) in output_file.read_text()

    def test_writes_to_correct_file(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=(sys.platform != "darwin")
        )
        output_file = tmp_path / "output.html"

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "flamegraph",
                str(results_file),
                "--output",
                str(output_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert output_file.exists()
        assert str(source_file) in output_file.read_text()

    def test_output_file_already_exists(self, tmp_path, simple_test_file, monkeypatch):
        """Check that when the output file is derived form the input name, we
        fail when there is already a file with the same name as the output."""

        # GIVEN
        monkeypatch.chdir(tmp_path)
        # This will generate "result.bin"
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=(sys.platform != "darwin")
        )
        output_file = tmp_path / "memray-flamegraph-result.html"
        output_file.touch()

        # WHEN
        ret = main(["flamegraph", str(results_file)])

        # THEN
        assert ret != 0

    def test_split_threads_subcommand(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=(sys.platform != "darwin")
        )
        output_file = tmp_path / "output.html"

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "flamegraph",
                "--split-threads",
                str(results_file),
                "--output",
                str(output_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert output_file.exists()
        assert str(source_file) in output_file.read_text()


class TestTableSubCommand:
    def test_reads_from_correct_file(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=(sys.platform != "darwin")
        )

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "table",
                str(results_file),
            ],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        output_file = tmp_path / "memray-table-result.html"
        assert output_file.exists()
        assert str(source_file) in output_file.read_text()

    def test_no_split_threads(self, tmp_path):
        # GIVEN/WHEN/THEN
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "memray",
                    "table",
                    "--split-threads",
                    "somefile",
                ],
                cwd=str(tmp_path),
                check=True,
                capture_output=True,
                text=True,
            )


class TestReporterSubCommands:
    @pytest.mark.parametrize("report", ["flamegraph", "table"])
    def test_report_detects_missing_input(self, report):
        # GIVEN / WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                report,
                "nosuchfile",
            ],
            capture_output=True,
            text=True,
        )

        # THEN
        assert proc.returncode == 1
        assert "No such file: nosuchfile" in proc.stderr

    @pytest.mark.parametrize("report", ["flamegraph", "table"])
    def test_report_detects_corrupt_input(self, tmp_path, report):
        # GIVEN
        bad_file = Path(tmp_path) / "badfile.bin"
        bad_file.write_text("This is some garbage")

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                report,
                str(bad_file),
            ],
            capture_output=True,
            text=True,
        )

        # THEN
        assert proc.returncode == 1
        assert re.match(
            r"Failed to parse allocation records in .*badfile\.bin", proc.stderr
        )

    @pytest.mark.parametrize("report", ["flamegraph", "table"])
    def test_report_leaks_argument(self, tmp_path, simple_test_file, report):
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=(sys.platform != "darwin")
        )
        output_file = tmp_path / "output.html"

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                report,
                "--leaks",
                str(results_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        output_file = tmp_path / f"memray-{report}-result.html"
        assert output_file.exists()
        assert str(source_file) in output_file.read_text()


class TestLiveRemoteSubcommand:
    def test_live_tracking(self, tmp_path, simple_test_file, free_port):

        # GIVEN
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--live-remote",
                "--live-port",
                str(free_port),
                str(simple_test_file),
            ],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        _wait_until_process_blocks(server.pid)

        client = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "memray",
                "live",
                str(free_port),
            ],
            stdin=subprocess.PIPE,
        )

        # WHEN

        try:
            server.communicate(timeout=TIMEOUT)
            client.communicate(b"q", timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            server.terminate()
            client.terminate()
            server.wait(timeout=TIMEOUT)
            client.wait(timeout=TIMEOUT)
            raise

        server.communicate()

        # THEN
        assert server.returncode == 0
        assert client.returncode == 0

    def test_live_tracking_waits_for_client(self, simple_test_file):
        # GIVEN/WHEN
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--live-remote",
                str(simple_test_file),
            ],
            env={"PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # THEN
        assert b"another shell to see live results\n" in server.stdout.readline()
        server.terminate()
        server.wait(timeout=TIMEOUT)

    @pytest.mark.parametrize("port", [0, 2**16, 1000000])
    def test_run_live_tracking_invalid_port(self, simple_test_file, port):
        # GIVEN/WHEN
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--live-remote",
                "--live-port",
                str(port),
                str(simple_test_file),
            ],
            env={"PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # THEN
        assert "Invalid port" in server.stderr.readline()
        server.terminate()
        server.wait(timeout=TIMEOUT)

    @pytest.mark.parametrize("port", [0, 2**16, 1000000])
    def test_live_tracking_invalid_port(self, port):
        # GIVEN/WHEN
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "memray",
                "live",
                str(port),
            ],
            env={"PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # THEN
        assert "Invalid port" in server.stderr.readline()
        server.terminate()
        server.wait(timeout=TIMEOUT)

    def test_live_tracking_server_when_client_disconnects(self, free_port, tmp_path):
        # GIVEN
        test_file = tmp_path / "test.py"
        test_file.write_text("import time; time.sleep(3)")

        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--live-port",
                str(free_port),
                "--live-remote",
                str(test_file),
            ],
            env={"PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        _wait_until_process_blocks(server.pid)

        client = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "memray",
                "live",
                str(free_port),
            ],
            stdin=subprocess.PIPE,
        )

        # WHEN
        try:
            client.communicate(b"q", timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            client.terminate()
            client.wait(timeout=TIMEOUT)
            raise

        try:
            _, stderr = server.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            server.terminate()
            server.wait(timeout=TIMEOUT)
            raise

        # THEN
        assert "Encountered error in 'send' call:" not in stderr

    def test_live_tracking_server_exits_properly_on_sigint(self, simple_test_file):
        # GIVEN
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "memray",
                "run",
                "--live-remote",
                str(simple_test_file),
            ],
            env={"PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Explicitly reset the signal handler for SIGINT to work around any signal
            # masking that might happen on Jenkins.
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.default_int_handler),
        )

        # WHEN
        server.stdout.readline()  # wait for the startup message
        # Ensure that it's waiting on the socket
        _wait_until_process_blocks(server.pid)

        server.send_signal(signal.SIGINT)
        try:
            _, stderr = server.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=TIMEOUT)
            raise

        # THEN
        assert server.returncode == 0
        assert b"Exception ignored" not in stderr
        assert b"Traceback (most recent call last):" not in stderr
        assert b"Interrupted system call" not in stderr

    def test_live_client_exits_properly_on_sigint_before_connecting(self, free_port):

        # GIVEN
        client = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "memray",
                "live",
                str(free_port),
            ],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # Explicitly reset the signal handler for SIGINT to work around any signal
            # masking that might happen on Jenkins.
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.default_int_handler),
        )

        # Ensure that it's waiting on the socket
        _wait_until_process_blocks(client.pid)

        # WHEN
        client.send_signal(signal.SIGINT)
        try:
            client.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            client.terminate()

        # THEN
        assert client.returncode == 0


class TestLiveSubcommand:
    def test_live_tracking(self, tmp_path):
        # GIVEN
        with track_and_wait(tmp_path) as program_file:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "memray",
                    "run",
                    "--live",
                    str(program_file),
                ],
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )

        # WHEN
        try:
            server.communicate(b"q", timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            server.kill()
            raise

        # THEN
        assert server.returncode == 0

    def test_live_tracking_server_exits_properly_on_sigint(self, tmp_path):
        # GIVEN
        with track_and_wait(tmp_path) as program_file:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "memray",
                    "run",
                    "--live",
                    str(program_file),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={"PYTHONUNBUFFERED": "1"},
                # Explicitly reset the signal handler for SIGINT to work around any signal
                # masking that might happen on Jenkins.
                preexec_fn=lambda: signal.signal(
                    signal.SIGINT, signal.default_int_handler
                ),
            )

        # WHEN

        server.send_signal(signal.SIGINT)
        try:
            _, stderr = server.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            server.kill()
            raise

        # THEN
        assert server.returncode == 0
        assert not stderr
        assert b"Exception ignored" not in stderr
        assert b"KeyboardInterrupt" not in stderr
