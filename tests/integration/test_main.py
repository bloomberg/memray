import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


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
        out_file = re.search("Writing profile results into (.*)", proc.stdout).group(1)
        assert (tmp_path / out_file).exists()

    def test_run_override_output(self, tmp_path):
        # GIVEN
        out_file = tmp_path / "result.out"

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
        out_file = tmp_path / "result.out"
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


class TestFlamegraphSubCommand:
    @staticmethod
    def generate_sample_results(tmp_path):
        results_file = tmp_path / "result.out"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "run",
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

    def test_reads_from_correct_file(self, tmp_path):
        # GIVEN
        results_file = self.generate_sample_results(tmp_path)

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
        output_file = tmp_path / "pensieve-flamegraph.html"
        assert output_file.exists()
        assert "json/tool.py" in output_file.read_text()

    def test_writes_to_correct_file(self, tmp_path):
        # GIVEN
        results_file = self.generate_sample_results(tmp_path)
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
        bad_file = Path(tmp_path) / "badfile.out"
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
            r"Failed to parse allocation records in .*badfile\.out$", proc.stderr
        )
