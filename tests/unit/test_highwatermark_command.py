import os
import sys
from pathlib import Path
from unittest.mock import ANY
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import call
from unittest.mock import patch

import pytest

from memray._errors import MemrayCommandError
from memray._memray import FileFormat
from memray.commands.common import HighWatermarkCommand


class TestFilenameValidation:
    def test_fails_when_results_does_not_exist(self, tmp_path):
        # GIVEN
        command = HighWatermarkCommand(Mock(), reporter_name="reporter")
        results = tmp_path / "results.bin"

        # WHEN / THEN
        with pytest.raises(MemrayCommandError, match="No such file"):
            command.validate_filenames(
                output=None,
                results=os.fspath(results),
            )

    def test_generates_output_name_when_none(self, tmp_path):
        # GIVEN
        command = HighWatermarkCommand(Mock(), reporter_name="reporter")
        results = tmp_path / "results.bin"
        results.touch()

        # WHEN
        results_file, output_file = command.validate_filenames(
            output=None,
            results=os.fspath(results),
        )

        # THEN
        assert results_file == results
        assert output_file == tmp_path / "memray-reporter-results.html"

    def test_uses_determine_output_filename_when_output_is_none(self, tmp_path):
        # GIVEN
        command = HighWatermarkCommand(Mock(), reporter_name="reporter")
        results = tmp_path / "results.bin"
        results.touch()
        command.determine_output_filename = MagicMock(return_value="patched.html")

        # WHEN
        results_file, output_file = command.validate_filenames(
            output=None,
            results=os.fspath(results),
        )

        # THEN
        assert results_file == results
        assert output_file == Path("patched.html")
        command.determine_output_filename.assert_called_once_with(results_file)

    def test_uses_output_name_as_given(self, tmp_path):
        # GIVEN
        command = HighWatermarkCommand(Mock(), reporter_name="reporter")
        output = tmp_path / "output.html"
        results = tmp_path / "results.bin"
        results.touch()

        # WHEN
        results_file, output_file = command.validate_filenames(
            output=os.fspath(output),
            results=os.fspath(results),
        )

        # THEN
        assert results_file == results
        assert output_file == output

    def test_fails_when_fallback_output_exists(self, tmp_path):
        # GIVEN
        command = HighWatermarkCommand(Mock(), reporter_name="reporter")
        results = tmp_path / "results.bin"
        results.touch()
        (tmp_path / "memray-reporter-results.html").touch()

        # WHEN / THEN
        with pytest.raises(MemrayCommandError, match="File already exists"):
            command.validate_filenames(
                output=None,
                results=os.fspath(results),
            )

    def test_succeeds_when_fallback_output_exists_but_can_overwrite(self, tmp_path):
        # GIVEN
        command = HighWatermarkCommand(Mock(), reporter_name="reporter")
        results = tmp_path / "results.bin"
        results.touch()
        (tmp_path / "memray-reporter-results.html").touch()

        # WHEN / THEN
        results_file, output_file = command.validate_filenames(
            output=None,
            results=os.fspath(results),
            overwrite=True,
        )

        # THEN
        assert results_file == results
        assert output_file is not None

    def test_fails_when_given_output_exists(self, tmp_path):
        # GIVEN
        command = HighWatermarkCommand(Mock(), reporter_name="reporter")
        results = tmp_path / "results.bin"
        results.touch()
        output = tmp_path / "output.html"
        output.touch()

        # WHEN / THEN
        with pytest.raises(MemrayCommandError, match="File already exists"):
            command.validate_filenames(
                output=output,
                results=os.fspath(results),
            )

    def test_succeeds_when_given_output_exists_but_can_overwrite(self, tmp_path):
        # GIVEN
        command = HighWatermarkCommand(Mock(), reporter_name="reporter")
        results = tmp_path / "results.bin"
        results.touch()
        output = tmp_path / "output.html"
        output.touch()

        # WHEN / THEN
        results_file, output_file = command.validate_filenames(
            output=output,
            results=os.fspath(results),
            overwrite=True,
        )

        # THEN
        assert results_file == results
        assert output_file == output


class TestReportGeneration:
    @pytest.mark.parametrize("merge_threads", [True, False])
    def test_tracker_and_reporter_interactions_for_peak(self, tmp_path, merge_threads):
        # GIVEN
        reporter_factory_mock = Mock()
        command = HighWatermarkCommand(reporter_factory_mock, reporter_name="reporter")
        result_path = tmp_path / "results.bin"
        output_file = tmp_path / "output.txt"

        # WHEN
        with patch("memray.commands.common.FileReader") as reader_mock:
            command.write_report(
                result_path=result_path,
                output_file=output_file,
                show_memory_leaks=False,
                temporary_allocation_threshold=-1,
                merge_threads=merge_threads,
            )

        # THEN
        calls = [
            call(os.fspath(result_path), report_progress=True),
            call().metadata.has_native_traces.__bool__(),
            call().metadata.file_format.__eq__(FileFormat.ALL_ALLOCATIONS)
            if sys.version_info >= (3, 8, 0)
            else ANY,
            call().get_high_watermark_allocation_records(merge_threads=merge_threads),
            call().get_memory_snapshots(),
        ]
        reader_mock.assert_has_calls(calls)

        reporter_factory_mock.assert_called_once()
        reporter_factory_mock().render.assert_called_once()

    @pytest.mark.parametrize("merge_threads", [True, False])
    def test_tracker_and_reporter_interactions_for_leak(self, tmp_path, merge_threads):
        # GIVEN
        reporter_factory_mock = Mock()
        command = HighWatermarkCommand(reporter_factory_mock, reporter_name="reporter")
        result_path = tmp_path / "results.bin"
        output_file = tmp_path / "output.txt"

        # WHEN
        with patch("memray.commands.common.FileReader") as reader_mock:
            command.write_report(
                result_path=result_path,
                output_file=output_file,
                show_memory_leaks=True,
                temporary_allocation_threshold=-1,
                merge_threads=merge_threads,
            )

        # THEN
        calls = [
            call(os.fspath(result_path), report_progress=True),
            call().metadata.has_native_traces.__bool__(),
            call().metadata.file_format.__eq__(FileFormat.ALL_ALLOCATIONS)
            if sys.version_info >= (3, 8, 0)
            else ANY,
            call().get_leaked_allocation_records(merge_threads=merge_threads),
            call().get_memory_snapshots(),
        ]
        reader_mock.assert_has_calls(calls)

        reporter_factory_mock.assert_called_once()
        reporter_factory_mock().render.assert_called_once()

    @pytest.mark.parametrize("merge_threads", [True, False])
    def test_tracker_and_reporter_interactions_for_temporary_allocations(
        self, tmp_path, merge_threads
    ):
        # GIVEN
        reporter_factory_mock = Mock()
        command = HighWatermarkCommand(reporter_factory_mock, reporter_name="reporter")
        result_path = tmp_path / "results.bin"
        output_file = tmp_path / "output.txt"

        # WHEN
        with patch("memray.commands.common.FileReader") as reader_mock:
            command.write_report(
                result_path=result_path,
                output_file=output_file,
                show_memory_leaks=False,
                temporary_allocation_threshold=3,
                merge_threads=merge_threads,
            )

        # THEN
        calls = [
            call(os.fspath(result_path), report_progress=True),
            call().metadata.has_native_traces.__bool__(),
            call().get_temporary_allocation_records(
                threshold=3, merge_threads=merge_threads
            ),
            call().get_memory_snapshots(),
        ]
        reader_mock.assert_has_calls(calls)

        reporter_factory_mock.assert_called_once()
        reporter_factory_mock().render.assert_called_once()
