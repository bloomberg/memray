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
