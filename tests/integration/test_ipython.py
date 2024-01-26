import os

import pytest
from IPython.core.displaypub import CapturingDisplayPublisher
from IPython.core.interactiveshell import InteractiveShell


def run_in_ipython_shell(tmpdir, cells):
    """Run the given cells in an IPython shell and return the HTML output."""
    InteractiveShell.clear_instance()

    shell = InteractiveShell.instance(display_pub_class=CapturingDisplayPublisher)
    prev_running_dir = os.getcwd()
    try:
        os.chdir(tmpdir)
        for cell in cells:
            shell.run_cell(cell)
    finally:
        os.chdir(prev_running_dir)

    InteractiveShell.clear_instance()
    try:
        html = shell.display_pub.outputs[-1]["data"]["text/html"]
        return html
    except IndexError:
        return None


@pytest.mark.filterwarnings("ignore")
class TestIPython:
    def test_ipython_profiling(self, tmpdir):
        """Test that the IPython extension works."""
        # GIVEN
        code = [
            "%load_ext memray",
            """
            %%memray_flamegraph
            x = "a" * 10000
            """,
        ]

        # WHEN

        html = run_in_ipython_shell(tmpdir, code)

        # THEN

        assert html is not None
        assert "<iframe" in html
        assert "flamegraph.html" in html

    def test_exception_while_ipython_profiling(self, tmpdir):
        """Test that the IPython extension works even if an exception
        is raised."""
        # GIVEN

        code = [
            "%load_ext memray",
            """
            %%memray_flamegraph
            x = "a" * 10000
            1/0
            """,
        ]

        # WHEN

        html = run_in_ipython_shell(tmpdir, code)

        # THEN

        assert html is not None
        assert "<iframe" in html
        assert "flamegraph.html" in html

    def test_passing_help_argument(self, tmpdir, capsys):
        # GIVEN

        code = [
            "%load_ext memray",
            """
            %%memray_flamegraph -h
            """,
        ]

        # WHEN

        html = run_in_ipython_shell(tmpdir, code)

        # THEN

        assert html is None
        stdout, stderr = capsys.readouterr()
        assert "show this help message" in stdout
        assert "" == stderr

    def test_passing_invalid_argument(self, tmpdir, capsys):
        # GIVEN

        code = [
            "%load_ext memray",
            """
            %%memray_flamegraph --oopsie
            """,
        ]

        # WHEN

        html = run_in_ipython_shell(tmpdir, code)

        # THEN

        assert html is None
        stdout, stderr = capsys.readouterr()
        assert "" == stdout
        assert "usage:" in stderr

    def test_passing_valid_arguments(self, tmpdir, capsys):
        # GIVEN

        code = [
            "%load_ext memray",
            """
            %%memray_flamegraph --leaks --max-memory-records 5
            x = "a" * 10000
            """,
        ]

        # WHEN

        html = run_in_ipython_shell(tmpdir, code)

        # THEN

        assert html is not None
        stdout, _ = capsys.readouterr()
        assert "<iframe" in html
        assert "flamegraph.html" in html
        assert "Results saved to" in stdout

    @pytest.mark.parametrize(
        "args,title",
        [
            ("--temporary-allocation-threshold=2", "flamegraph report"),
            ("--leaks", "flamegraph report (memory leaks)"),
            ("--temporal", "temporal flamegraph report"),
            ("--leaks --temporal", "temporal flamegraph report (memory leaks)"),
        ],
    )
    def test_report_title_by_report_type(self, tmpdir, capsys, args, title):
        # GIVEN
        code = [
            "%load_ext memray",
            f"""
            %%memray_flamegraph {args}
            x = "a" * 10000
            """,
        ]

        # WHEN
        html = run_in_ipython_shell(tmpdir, code)

        # THEN
        assert html is not None
        stdout, _ = capsys.readouterr()
        assert "<iframe" in html
        assert "flamegraph.html" in html
        assert "Results saved to" in stdout

        title_tag = f"<title>memray - {title}</title>"
        assert title_tag in next(tmpdir.visit("**/flamegraph.html")).read()

    def test_passing_temporal_and_temporary_allocations(self, tmpdir, capsys):
        # GIVEN
        code = [
            "%load_ext memray",
            """
            %%memray_flamegraph --temporal --temporary-allocation-threshold=2
            """,
        ]

        # WHEN
        html = run_in_ipython_shell(tmpdir, code)

        # THEN
        assert html is None
        stdout, stderr = capsys.readouterr()
        assert "" == stdout
        assert "Can't create a temporal flame graph of temporary allocations" in stderr
