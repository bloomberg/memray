import re
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from bloomberg.pensieve.commands import main


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
        assert "json/tool.py" in output_file.read_text()

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
        assert "json/tool.py" in output_file.read_text()

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
        assert "json/tool.py" in output_file.read_text()

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
        assert "json/tool.py" in output_file.read_text()


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
        assert "json/tool.py" in output_file.read_text()

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
        assert "json/tool.py" in output_file.read_text()
