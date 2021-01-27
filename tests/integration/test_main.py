import re
import subprocess
import sys


class TestRunSubcommand:
    def test_run(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, "-m", "bloomberg.pensieve", "run", "json.tool", "-h"],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert "usage: python -m json.tool" in proc.stdout
        assert proc.returncode == 0
        out_file = re.search("Writing profile results into (.*)", proc.stdout).group(1)
        assert (tmp_path / out_file).exists()

    def test_run_override_output(self, tmp_path):
        out_file = tmp_path / "result.out"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "bloomberg.pensieve",
                "run",
                "--output",
                str(out_file),
                "json.tool",
                "-h",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "usage: python -m json.tool" in proc.stdout
        assert proc.returncode == 0
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
