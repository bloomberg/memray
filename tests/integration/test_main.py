import contextlib
import json
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

from memray import FileFormat
from memray import Tracker
from memray._test import MemoryAllocator
from memray._test import set_thread_name
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


def generate_sample_results(
    tmp_path,
    code,
    *,
    native=False,
    trace_python_allocators=False,
    disable_pymalloc=False,
):
    results_file = tmp_path / "result.bin"
    env = os.environ.copy()
    env["PYTHONMALLOC"] = "malloc" if disable_pymalloc else "pymalloc"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "memray",
            "run",
            *(["--native"] if native else []),
            *(["--trace-python-allocators"] if trace_python_allocators else []),
            "--output",
            str(results_file),
            str(code),
        ],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
        text=True,
        env=env,
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
        target_file.write_text("import json, sys; print(json.dumps(sys.path))")

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
        assert out_file.exists()
        assert proc.returncode == 0
        # Running `python -m` put cwd in sys.path; ensure we replaced it.
        path = json.loads(proc.stdout)
        assert os.getcwd() not in path
        assert str(tmp_path) in path

    @pytest.mark.parametrize(
        "isolation_flag", ["-I"] + (["-P"] if sys.version_info > (3, 11) else [])
    )
    def test_suppressing_sys_manipulations_when_running_script(
        self, tmp_path, isolation_flag
    ):
        # GIVEN
        out_file = tmp_path / "result.bin"
        target_file = tmp_path / "test.py"
        target_file.write_text("import json, sys; print(json.dumps(sys.path))")

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                isolation_flag,
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
        assert out_file.exists()
        assert proc.returncode == 0
        # Running `python -m` did not put cwd in sys.path; ensure it isn't
        # there, and neither is the tmp_path we would have replaced it with.
        path = json.loads(proc.stdout)
        assert os.getcwd() not in path
        assert str(tmp_path) not in path

    def test_sys_manipulations_when_running_module(self, tmp_path):
        # GIVEN
        out_file = tmp_path / "result.bin"

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from memray.commands import main; sys.exit(main())",
                "run",
                "--quiet",
                "--output",
                str(out_file),
                "-m",
                "site",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert out_file.exists()
        assert proc.returncode == 0
        # Running `python -c` put "" in sys.path; ensure we replaced it.
        path = eval(
            " ".join(line for line in proc.stdout.splitlines() if line.startswith(" "))
        )
        assert "" not in path
        assert os.getcwd() in path

    @pytest.mark.parametrize(
        "isolation_flag", ["-I"] + (["-P"] if sys.version_info > (3, 11) else [])
    )
    def test_suppressing_sys_manipulations_when_running_module(
        self, tmp_path, isolation_flag
    ):
        # GIVEN
        out_file = tmp_path / "result.bin"

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                isolation_flag,
                "-c",
                "import sys; from memray.commands import main; sys.exit(main())",
                "run",
                "--quiet",
                "--output",
                str(out_file),
                "-m",
                "site",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert out_file.exists()
        assert proc.returncode == 0
        # Running `python -c` did not put "" in sys.path; ensure it isn't
        # there, and neither is the os.getcwd() we would have replaced it with.
        path = eval(
            " ".join(line for line in proc.stdout.splitlines() if line.startswith(" "))
        )
        assert "" not in path
        assert os.getcwd() not in path

    def test_sys_manipulations_when_running_cmd(self, tmp_path):
        # GIVEN
        out_file = tmp_path / "result.bin"

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
                "import json, sys; print(json.dumps(sys.path))",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert out_file.exists()
        assert proc.returncode == 0
        # Running `python -m` put cwd in sys.path; ensure we replaced it.
        path = json.loads(proc.stdout)
        assert os.getcwd() not in path
        assert "" in path

    @pytest.mark.parametrize(
        "isolation_flag", ["-I"] + (["-P"] if sys.version_info > (3, 11) else [])
    )
    def test_suppressing_sys_manipulations_when_running_cmd(
        self, tmp_path, isolation_flag
    ):
        # GIVEN
        out_file = tmp_path / "result.bin"

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                isolation_flag,
                "-m",
                "memray",
                "run",
                "--quiet",
                "--output",
                str(out_file),
                "-c",
                "import json, sys; print(json.dumps(sys.path))",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        assert out_file.exists()
        assert proc.returncode == 0
        # Running `python -m` did not put cwd in sys.path; ensure it isn't
        # there, and neither is the "" we would have replaced it with.
        path = json.loads(proc.stdout)
        assert os.getcwd() not in path
        assert "" not in path

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
            "ALLOCATION_WITH_NATIVE",
            "MEMORY_MAP_START",
            "SEGMENT_HEADER",
            "SEGMENT",
            "NATIVE_FRAME_ID",
            "FRAME_PUSH",
            "FRAME_POP",
            "FRAME_ID",
            "MEMORY_RECORD",
            "CONTEXT_SWITCH",
            "TRAILER",
        ]

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
        results_file, _ = generate_sample_results(tmp_path, code_file, native=True)

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

        for count in record_count_by_type.values():
            assert count > 0

    def test_successful_parse_of_aggregated_capture_file(self, tmp_path):
        # GIVEN
        results_file = tmp_path / "result.bin"
        record_types = [
            "MEMORY_SNAPSHOT",
            "AGGREGATED_ALLOCATION",
            "PYTHON_TRACE_INDEX",
            "PYTHON_FRAME_INDEX",
            "NATIVE_TRACE_INDEX",
            "MEMORY_MAP_START",
            "SEGMENT_HEADER",
            "SEGMENT",
            "AGGREGATED_TRAILER",
        ]

        with Tracker(
            results_file,
            native_traces=True,
            file_format=FileFormat.AGGREGATED_ALLOCATIONS,
        ):
            if set_thread_name("main") == 0:
                # We should get CONTEXT_SWITCH and THREAD_RECORD records only
                # if we can set the thread name. On macOS, we won't get these.
                record_types.append("CONTEXT_SWITCH")
                record_types.append("THREAD_RECORD")

            allocator = MemoryAllocator()
            allocator.valloc(1024)
            allocator.free()
            # Give it time to generate some memory records
            time.sleep(0.1)

        record_count_by_type = dict.fromkeys(record_types, 0)

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
        print(records)

        for record in records:
            record_count_by_type[record.partition(" ")[0]] += 1

        for count in record_count_by_type.values():
            assert count > 0

    def test_error_when_stdout_is_a_tty(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=True
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
            tmp_path, simple_test_file, native=True
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
            tmp_path, simple_test_file, native=True
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
            tmp_path, simple_test_file, native=True
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
            tmp_path, simple_test_file, native=True
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
            tmp_path, simple_test_file, native=True
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

    @pytest.mark.parametrize("trace_python_allocators", [True, False])
    @pytest.mark.parametrize("disable_pymalloc", [True, False])
    def test_leaks_with_pymalloc_warning(
        self,
        tmp_path,
        simple_test_file,
        trace_python_allocators,
        disable_pymalloc,
    ):
        results_file, _ = generate_sample_results(
            tmp_path,
            simple_test_file,
            native=True,
            trace_python_allocators=trace_python_allocators,
            disable_pymalloc=disable_pymalloc,
        )
        output_file = tmp_path / "output.html"
        warning_expected = not trace_python_allocators and not disable_pymalloc

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "flamegraph",
                "--leaks",
                str(results_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        output_file = tmp_path / "memray-flamegraph-result.html"
        assert output_file.exists()
        assert warning_expected == (
            'Report generated using "--leaks" using pymalloc allocator'
            in output_file.read_text()
        )


class TestSummarySubCommand:
    def test_summary_generated(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, _ = generate_sample_results(
            tmp_path, simple_test_file, native=True
        )

        # WHEN
        output = subprocess.check_output(
            [
                sys.executable,
                "-m",
                "memray",
                "summary",
                str(results_file),
            ],
            cwd=str(tmp_path),
            text=True,
        )

        # THEN
        assert output

    def test_temporary_allocations_summary(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, _ = generate_sample_results(tmp_path, simple_test_file)

        # WHEN
        output = subprocess.check_output(
            [
                sys.executable,
                "-m",
                "memray",
                "summary",
                "--temporary-allocations",
                str(results_file),
            ],
            cwd=str(tmp_path),
            text=True,
        )

        # THEN
        assert output


class TestTreeSubCommand:
    def test_tree_generated(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, _ = generate_sample_results(
            tmp_path, simple_test_file, native=True
        )
        env = os.environ.copy()
        env["TEXTUAL_PRESS"] = "q"

        # WHEN
        output = subprocess.check_output(
            [
                sys.executable,
                "-m",
                "memray",
                "tree",
                str(results_file),
            ],
            cwd=str(tmp_path),
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
        )

        # THEN
        assert output

    def test_temporary_allocations_tree(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, _ = generate_sample_results(tmp_path, simple_test_file)
        env = os.environ.copy()
        env["TEXTUAL_PRESS"] = "q"

        # WHEN
        output = subprocess.check_output(
            [
                sys.executable,
                "-m",
                "memray",
                "tree",
                "--temporary-allocations",
                str(results_file),
            ],
            cwd=str(tmp_path),
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
        )

        # THEN
        assert output


class TestStatsSubCommand:
    def test_report_generated(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, _ = generate_sample_results(
            tmp_path, simple_test_file, native=True
        )

        # WHEN
        output = subprocess.check_output(
            [
                sys.executable,
                "-m",
                "memray",
                "stats",
                str(results_file),
            ],
            cwd=str(tmp_path),
            text=True,
        )

        # THEN
        assert "VALLOC" in output

    def test_json_generated(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, _ = generate_sample_results(tmp_path, simple_test_file)
        json_file = tmp_path / "memray-stats-result.bin.json"

        # WHEN
        subprocess.check_output(
            [
                sys.executable,
                "-m",
                "memray",
                "stats",
                "--json",
                str(results_file),
            ],
            cwd=str(tmp_path),
            text=True,
        )

        # THEN
        assert json_file.exists()
        assert isinstance(json.loads(json_file.read_text()), dict)

    def test_json_generated_to_pretty_file_name(self, tmp_path, simple_test_file):
        # GIVEN
        orig_results_file, _ = generate_sample_results(tmp_path, simple_test_file)
        results_file = orig_results_file.with_name("memray-foobar.bin")
        orig_results_file.rename(results_file)
        json_file = tmp_path / "memray-stats-foobar.bin.json"

        # WHEN
        subprocess.check_output(
            [
                sys.executable,
                "-m",
                "memray",
                "stats",
                "--json",
                str(results_file),
            ],
            cwd=str(tmp_path),
            text=True,
        )

        # THEN
        assert json_file.exists()
        assert isinstance(json.loads(json_file.read_text()), dict)

    def test_json_generated_to_known_file(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, _ = generate_sample_results(tmp_path, simple_test_file)
        json_file = tmp_path / "output.json"

        # WHEN
        subprocess.check_output(
            [
                sys.executable,
                "-m",
                "memray",
                "stats",
                "--json",
                "-o",
                str(json_file),
                str(results_file),
            ],
            cwd=str(tmp_path),
            text=True,
        )

        # THEN
        assert json_file.exists()
        assert isinstance(json.loads(json_file.read_text()), dict)

    def test_json_generated_to_existing_known_file(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, _ = generate_sample_results(tmp_path, simple_test_file)
        json_file = tmp_path / "output.json"
        json_file.write_text("oops")

        # WHEN
        try:
            exc = None
            subprocess.check_output(
                [
                    sys.executable,
                    "-m",
                    "memray",
                    "stats",
                    "--json",
                    "-o",
                    str(json_file),
                    str(results_file),
                ],
                cwd=str(tmp_path),
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            exc = e

        # THEN
        assert exc is not None
        assert "File already exists, will not overwrite" in exc.stderr

    def test_json_overwrites_existing_known_file(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, _ = generate_sample_results(tmp_path, simple_test_file)
        json_file = tmp_path / "output.json"
        json_file.write_text("oops")

        # WHEN
        subprocess.check_output(
            [
                sys.executable,
                "-m",
                "memray",
                "stats",
                "--json",
                "--force",
                "--output",
                str(json_file),
                str(results_file),
            ],
            cwd=str(tmp_path),
            stderr=subprocess.PIPE,
            text=True,
        )

        # THEN
        assert json_file.exists()
        assert isinstance(json.loads(json_file.read_text()), dict)

    def test_report_detects_corrupt_input(self, tmp_path):
        # GIVEN
        bad_file = Path(tmp_path) / "badfile.bin"
        bad_file.write_text("This is some garbage")

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "stats",
                str(bad_file),
            ],
            capture_output=True,
            text=True,
        )

        # THEN
        assert proc.returncode == 1
        assert re.match(r"Failed to compute statistics for .*badfile\.bin", proc.stderr)


class TestTableSubCommand:
    def test_reads_from_correct_file(self, tmp_path, simple_test_file):
        # GIVEN
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=True
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
    @pytest.mark.parametrize(
        "report", ["flamegraph", "table", "summary", "tree", "stats"]
    )
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

    @pytest.mark.parametrize("report", ["flamegraph", "table", "summary", "tree"])
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
            tmp_path, simple_test_file, native=True
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

    @pytest.mark.parametrize("report", ["flamegraph", "table"])
    def test_report_temporary_allocations_argument(
        self, tmp_path, simple_test_file, report
    ):
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=True
        )
        output_file = tmp_path / "output.html"

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                report,
                str(results_file),
                "--temporary-allocations",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        output_file = tmp_path / f"memray-{report}-result.html"
        assert output_file.exists()
        assert str(source_file) in output_file.read_text()

    @pytest.mark.parametrize("report", ["flamegraph", "table"])
    def test_report_incompatible_arguments(self, tmp_path, simple_test_file, report):
        results_file, _ = generate_sample_results(
            tmp_path, simple_test_file, native=True
        )

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                report,
                "--temporary-allocations",
                "--leaks",
                str(results_file),
            ],
            capture_output=True,
            text=True,
        )

        # THEN
        assert proc.returncode != 0
        assert (
            "--leaks: not allowed with argument --temporary-allocations" in proc.stderr
        )

    @pytest.mark.parametrize("report", ["flamegraph", "table", "summary", "tree"])
    def test_report_both_temporary_allocation_arguments(
        self, tmp_path, simple_test_file, report
    ):
        results_file, _ = generate_sample_results(
            tmp_path, simple_test_file, native=True
        )

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                report,
                "--temporary-allocations",
                "--temporary-allocation-threshold=1",
                str(results_file),
            ],
            capture_output=True,
            text=True,
        )

        # THEN
        assert proc.returncode != 0
        assert (
            "--temporary-allocation-threshold: not allowed with"
            " argument --temporary-allocations" in proc.stderr
        )


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
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
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
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
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


class TestTransformSubCommands:
    def test_report_detects_missing_input(self):
        # GIVEN / WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "transform",
                "gprof2dot",
                "nosuchfile",
            ],
            capture_output=True,
            text=True,
        )

        # THEN
        assert proc.returncode == 1
        assert "No such file: nosuchfile" in proc.stderr

    def test_report_detects_corrupt_input(self, tmp_path):
        # GIVEN
        bad_file = Path(tmp_path) / "badfile.bin"
        bad_file.write_text("This is some garbage")

        # WHEN
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "transform",
                "gprof2dot",
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

    def test_report_leaks_argument(self, tmp_path, simple_test_file):
        results_file, source_file = generate_sample_results(
            tmp_path, simple_test_file, native=True
        )
        output_file = tmp_path / "output.html"

        # WHEN
        subprocess.run(
            [
                sys.executable,
                "-m",
                "memray",
                "transform",
                "gprof2dot",
                "--leaks",
                str(results_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # THEN
        output_file = tmp_path / "memray-gprof2dot-result.json"
        assert output_file.exists()
        output_text = output_file.read_text()
        if "<unknown stack>" in output_text:
            pytest.xfail("Hybrid stack generation is not fully working")
        assert str(source_file) in output_text
