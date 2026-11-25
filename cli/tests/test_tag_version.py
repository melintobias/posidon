"""Tests for choosing and validating the written metadata tag version."""

from posidon_cli.main import app
from posidon_cli.options import OutputFormat
from posidon_cli.pipeline.tagging import check_tag_version
from posidon_cli.pipeline.types import StageOrchestrator
from posidon_core.adapters.tagging.mp3 import Mp3TagWriter
import pytest
from typer.testing import CliRunner

USAGE_ERROR_EXIT_CODE = 2
"""Exit code of a command-line usage error."""


def run_cli(
    args: list[str], monkeypatch: pytest.MonkeyPatch
) -> tuple[int, str, list[str | None]]:
    """Invoke the CLI and record the tag version passed to the pipeline.

    Args:
        args: Command-line arguments.
        monkeypatch: Fixture for intercepting the pipeline before retrieval.

    Returns:
        The exit code, the output with box drawing and line wrapping removed,
        and the tag versions of each pipeline run.
    """
    versions: list[str | None] = []

    def capture_version(orchestrator: StageOrchestrator) -> None:
        """Record the tag version without running the stages.

        Args:
            orchestrator: Pipeline configured by the command.
        """
        versions.append(orchestrator.storage.options.tag_version)

    monkeypatch.setattr(StageOrchestrator, "run", capture_version)

    result = CliRunner().invoke(app, args)

    output = " ".join(
        result.output.translate(str.maketrans("│╭╮╰╯─", "      ")).split()
    )
    return result.exit_code, output, versions


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], None),
        (["--tag-version", "id3v2.4"], "id3v2.4"),
        (["--tag-version", "id3v2.3", "--output-format", "mp3"], "id3v2.3"),
        (["--output-format", "mp3", "--tag-version", "id3v2.3"], "id3v2.3"),
    ],
)
def test_cli_configures_tag_version(
    args: list[str], expected: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pass the requested tag version, or none, to the pipeline.

    Args:
        args: Command-line options for this run.
        expected: Tag version the pipeline should receive.
        monkeypatch: Fixture for intercepting the pipeline before retrieval.
    """
    exit_code, output, versions = run_cli(args, monkeypatch)

    assert exit_code == 0, output
    assert versions == [expected]


@pytest.mark.parametrize(
    "args",
    [
        ["--tag-version", "id3v2.2", "--output-format", "mp3"],
        ["--output-format", "mp3", "--tag-version", "id3v2.2"],
        ["--tag-version", "id3v2.2"],
    ],
)
def test_cli_rejects_unsupported_tag_version(
    args: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report a usage error naming the flag, format, and supported versions.

    The error comes before the pipeline starts, whatever the flag order.

    Args:
        args: Command-line options for this run.
        monkeypatch: Fixture for intercepting the pipeline before retrieval.
    """
    exit_code, output, versions = run_cli([*args, "--no-prompt"], monkeypatch)

    assert exit_code == USAGE_ERROR_EXIT_CODE
    assert versions == []
    assert "Invalid value for '--tag-version'" in output
    assert "'id3v2.2' is not supported for output format 'mp3'" in output
    assert "Supported versions: id3v2.3, id3v2.4." in output


def test_check_tag_version_reads_declarations_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check versions against the writer's declarations without building it.

    Args:
        monkeypatch: Fixture for making writer construction fail.
    """

    def fail(*args: object) -> None:
        """Fail if the check builds a writer.

        Args:
            args: Ignored constructor arguments.

        Raises:
            AssertionError: Always.
        """
        raise AssertionError(args)

    monkeypatch.setattr(Mp3TagWriter, "__init__", fail)

    check_tag_version(OutputFormat.MP3, None)
    check_tag_version(OutputFormat.MP3, "id3v2.3")
    with pytest.raises(ValueError, match="Supported versions"):
        check_tag_version(OutputFormat.MP3, "id3v1")
