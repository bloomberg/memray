import contextlib
import os
import re
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bloomberg.pensieve.commands import main


@contextlib.contextmanager
def track_and_wait(output_dir, sleep_after=100):
    """Creates a test script which does some allocations, and upon leaving the context manager,
    it blocks until the allocations have completed."""

    fifo = output_dir / "snapshot_taken.event"
    os.mkfifo(fifo)

    program = textwrap.dedent(
        f"""\
        import time
        from bloomberg.pensieve._pensieve import MemoryAllocator
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
    # Signal numbers from https://filippo.io/linux-syscall-table/
    sleep_syscall = "35"
    connect_syscall = "42"
    accept_syscall = "43"
    syscalls_to_wait = {sleep_syscall, connect_syscall, accept_syscall}
    current_syscall = ""
    while True:
        syscall = Path(f"/proc/{pid}/syscall")
        current_syscall, *_ = syscall.read_text().split()
        if current_syscall.strip() in syscalls_to_wait:
            return
        time.sleep(0.1)


def generate_sample_results(tmp_path, *, native=False):
    results_file = tmp_path / "result.bin"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "bloomberg.pensieve",
            "run",
            *(["--native"] if native else []),
            "--output",
            str(results_file),
            "-m",
            "json.tool",
            "-h",
        ],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    )
    return results_file


class TestRunSubcommand:
    def test_run(self, tmp_path):
        # GIVEN / WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "run",
                "-m",
                "json.tool",
                "-h",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        # THEN
        assert "usage: python -m json.tool" in proc.stdout
        assert proc.returncode == 0
        assert "example commands" in proc.stdout

        out_file = re.search("Writing profile results into (.*)", proc.stdout).group(1)
        assert (tmp_path / out_file).exists()

    def test_run_override_output(self, tmp_path):
        # GIVEN
        out_file = tmp_path / "result.bin"

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "run",
                "--output",
                str(out_file),
                "-m",
                "json.tool",
                "-h",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert "usage: python -m json.tool" in proc.stdout
        assert proc.returncode == 0
        assert out_file.exists()

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
                "bloomberg.pensieve",
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

    @patch("bloomberg.pensieve.commands.run.os.getpid")
    def test_run_file_exists(self, getpid, tmp_path, monkeypatch, capsys):
        # GIVEN / WHEN
        getpid.return_value = 0
        (tmp_path / "pensieve-json.tool.0.bin").touch()
        monkeypatch.chdir(tmp_path)

        # THEN
        assert main(["run", "-m", "json.tool", "-h"]) == 1
        captured = capsys.readouterr()
        assert (
            captured.err.strip()
            == "Could not create output file pensieve-json.tool.0.bin: File exists"
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
    def test_quiet(self, quiet, tmp_path):
        # GIVEN
        out_file = tmp_path / "result.bin"

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "run",
                *(["-q"] if quiet else []),
                "--output",
                str(out_file),
                "-m",
                "json.tool",
                "-h",
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


class TestFlamegraphSubCommand:
    def test_reads_from_correct_file(self, tmp_path):
        # GIVEN
        results_file = generate_sample_results(tmp_path)

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "flamegraph",
                str(results_file),
            ],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        output_file = tmp_path / "pensieve-flamegraph-result.html"
        assert output_file.exists()
        assert "json.tool" in output_file.read_text()

    def test_can_generate_reports_with_native_traces(self, tmp_path):
        # GIVEN
        results_file = generate_sample_results(tmp_path, native=True)

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "flamegraph",
                str(results_file),
            ],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        output_file = tmp_path / "pensieve-flamegraph-result.html"
        assert output_file.exists()
        assert "json.tool" in output_file.read_text()

    def test_writes_to_correct_file(self, tmp_path):
        # GIVEN
        results_file = generate_sample_results(tmp_path)
        output_file = tmp_path / "output.html"

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
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
        assert "json.tool" in output_file.read_text()

    def test_output_file_already_exists(self, tmp_path, monkeypatch):
        """Check that when the output file is derived form the input name, we fail when there is
        already a file with the same name as the output."""

        # GIVEN
        monkeypatch.chdir(tmp_path)
        # This will generate "result.bin"
        results_file = generate_sample_results(tmp_path)
        output_file = tmp_path / "pensieve-flamegraph-result.html"
        output_file.touch()

        # WHEN
        ret = main(["flamegraph", str(results_file)])

        # THEN
        assert ret != 0

    def test_split_threads_subcommand(self, tmp_path):
        # GIVEN
        results_file = generate_sample_results(tmp_path)
        output_file = tmp_path / "output.html"

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
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
        assert "json.tool" in output_file.read_text()


class TestTableSubCommand:
    def test_reads_from_correct_file(self, tmp_path):
        # GIVEN
        results_file = generate_sample_results(tmp_path)

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "table",
                str(results_file),
            ],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        output_file = tmp_path / "pensieve-table-result.html"
        assert output_file.exists()
        assert "json.tool" in output_file.read_text()

    def test_no_split_threads(self, tmp_path):
        # GIVEN/WHEN/THEN
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bloomberg.pensieve",
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
                "bloomberg.pensieve",
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
                "bloomberg.pensieve",
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
    def test_report_leaks_argument(self, tmp_path, report):
        results_file = generate_sample_results(tmp_path)
        output_file = tmp_path / "output.html"

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                report,
                "--leaks",
                str(results_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        output_file = tmp_path / f"pensieve-{report}-result.html"
        assert output_file.exists()
        assert "json.tool" in output_file.read_text()


class TestLiveRemoteSubcommand:
    def test_live_tracking(self, free_port):

        # GIVEN
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "run",
                "--live-remote",
                "--live-port",
                str(free_port),
                "-m",
                "json.tool",
                "--help",
            ],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        client = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "live",
                str(free_port),
            ],
            stdin=subprocess.PIPE,
        )

        # WHEN

        try:
            server.communicate(timeout=3)
            client.communicate(b"q", timeout=3)
        except subprocess.TimeoutExpired:
            server.terminate()
            client.terminate()
            server.wait(timeout=3)
            client.wait(timeout=3)
            raise

        server.communicate()

        # THEN
        assert server.returncode == 0
        assert client.returncode == 0

    def test_live_tracking_waits_for_client(self):
        # GIVEN/WHEN
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "run",
                "--live-remote",
                "-m",
                "json.tool",
                "--help",
            ],
            env={"PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # THEN
        assert b"another shell to see live results\n" in server.stdout.readline()
        server.terminate()
        server.wait(timeout=3)

    @pytest.mark.parametrize("port", [0, 2 ** 16, 1000000])
    def test_run_live_tracking_invalid_port(self, port):
        # GIVEN/WHEN
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "run",
                "--live-remote",
                "--live-port",
                str(port),
                "-m",
                "json.tool",
                "--help",
            ],
            env={"PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # THEN
        assert "Invalid port" in server.stderr.readline()
        server.terminate()
        server.wait(timeout=3)

    @pytest.mark.parametrize("port", [0, 2 ** 16, 1000000])
    def test_live_tracking_invalid_port(self, port):
        # GIVEN/WHEN
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
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
        server.wait(timeout=3)

    def test_live_tracking_server_when_client_disconnects(self, free_port, tmp_path):
        # GIVEN
        test_file = tmp_path / "test.py"
        test_file.write_text("import time; time.sleep(3)")

        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
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
        client = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "live",
                str(free_port),
            ],
            stdin=subprocess.PIPE,
        )

        # WHEN
        try:
            client.communicate(b"q", timeout=10)
        except subprocess.TimeoutExpired:
            client.terminate()
            client.wait(timeout=3)
            raise

        try:
            _, stderr = server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.terminate()
            server.wait(timeout=3)
            raise

        # THEN
        assert "Failed to write output, deactivating tracking" in stderr
        assert "Encountered error in 'send' call:" not in stderr

    def test_live_tracking_server_exits_properly_on_sigint(self):
        # GIVEN
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "run",
                "--live-remote",
                "-m",
                "json.tool",
                "--help",
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
            _, stderr = server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=3)
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
                "bloomberg.pensieve",
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
            client.wait(timeout=5)
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
                    "bloomberg.pensieve",
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
            server.communicate(b"q", timeout=3)
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
                    "bloomberg.pensieve",
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
            _, stderr = server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            raise

        # THEN
        assert server.returncode == 0
        assert not stderr
        assert b"Exception ignored" not in stderr
        assert b"KeyboardInterrupt" not in stderr
