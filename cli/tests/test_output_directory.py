"""Tests for choosing the directory that receives finished audio files."""

from contextlib import suppress
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from posidon_cli.main import app
from posidon_cli.options import CliOptions
from posidon_cli.pipeline.intake import IntakeStage
from posidon_cli.pipeline.intake import OutputDirectorySubStage
from posidon_cli.pipeline.types import PipelineSharedStorage
from posidon_cli.pipeline.types import StageOrchestrator
import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Use a temporary home directory whose music folder doesn't exist yet.

    `Path.home` reads `USERPROFILE` on Windows and `HOME` elsewhere, so both
    variables are replaced, and `XDG_MUSIC_DIR` is cleared. The music
    directory is then `Music` in the returned path on every platform.

    Args:
        tmp_path: Per-test temporary directory containing the home directory.
        monkeypatch: Fixture restoring the environment after the test.

    Returns:
        The temporary home directory.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("XDG_MUSIC_DIR", raising=False)
    return home


@pytest.fixture
def working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the test from a temporary working directory used as the fallback.

    Args:
        tmp_path: Per-test temporary directory containing the working
            directory.
        monkeypatch: Fixture restoring the working directory after the test.

    Returns:
        The current working directory as reported by `Path.cwd`.
    """
    directory = tmp_path / "working"
    directory.mkdir()
    monkeypatch.chdir(directory)
    return Path.cwd()


@pytest.fixture
def read_only_directory(tmp_path: Path) -> Iterator[Path]:
    """Provide a directory in which no new file can be created.

    The test is skipped where permission bits don't stop the current user from
    writing, such as for the root user or on Windows.

    Args:
        tmp_path: Per-test temporary directory containing the directory.

    Yields:
        The read-only directory. Its permissions are restored afterwards so
        pytest can remove it.
    """
    directory = tmp_path / "read-only"
    directory.mkdir()
    directory.chmod(0o500)
    try:
        probe = directory / "probe"
        with suppress(PermissionError):
            probe.touch()
        if probe.exists():
            pytest.skip("The current user can write to read-only directories")
        yield directory
    finally:
        directory.chmod(0o700)


def select_output_directory(output_dir: Path | None) -> PipelineSharedStorage:
    """Run output directory selection for an optional chosen directory.

    Args:
        output_dir: Directory chosen on the command line, or `None` to use the
            music directory.

    Returns:
        Pipeline storage holding the selected output directory.
    """
    storage = PipelineSharedStorage(
        options=CliOptions(output_dir=output_dir),
        logger=logging.getLogger(__name__),
    )
    OutputDirectorySubStage.run(storage)
    return storage


def warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the formatted warning messages captured during a test.

    Args:
        caplog: Fixture holding the captured log records.

    Returns:
        Messages of the captured records at the `WARNING` level.
    """
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], None),
        (["--output-dir", "tracks"], Path("tracks")),
        (["-o", "tracks"], Path("tracks")),
    ],
)
def test_cli_configures_output_directory(
    args: list[str], expected: Path | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pass the chosen directory as a path, or `None` without the option."""
    directories: list[Path | None] = []

    def capture_directory(orchestrator: StageOrchestrator) -> None:
        """Record the directory passed by the CLI without running the stages.

        Args:
            orchestrator: Orchestrator holding the parsed command options.
        """
        directories.append(orchestrator.storage.options.output_dir)

    monkeypatch.setattr(StageOrchestrator, "run", capture_directory)

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert directories == [expected]


def test_cli_rejects_file_as_output_directory(tmp_path: Path) -> None:
    """Reject an existing file during command-line parsing."""
    file_path = tmp_path / "track.mp3"
    file_path.touch()

    result = CliRunner().invoke(
        app, ["--output-dir", str(file_path), "--no-prompt"]
    )

    assert result.exit_code != 0
    assert "Invalid value" in result.output


def test_existing_chosen_directory_is_used(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Use an existing chosen directory without a warning."""
    storage = select_output_directory(tmp_path)

    assert storage.output_directory == tmp_path
    assert warnings(caplog) == []


def test_missing_chosen_directory_falls_back_to_working_directory(
    tmp_path: Path, working_directory: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Warn about a missing chosen directory and use the working directory."""
    missing = tmp_path / "missing"

    storage = select_output_directory(missing)

    assert storage.output_directory == working_directory
    assert warnings(caplog) == [
        (
            f"Output directory {str(missing)!r} does not exist; saving tracks "
            f"to the current directory {str(working_directory)!r} instead. "
            "Pass an existing directory with --output-dir."
        )
    ]


def test_existing_music_directory_is_default(
    home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Use the music directory without a warning when no directory is chosen."""
    music = home / "Music"
    music.mkdir()

    storage = select_output_directory(None)

    assert storage.output_directory == music
    assert warnings(caplog) == []


def test_missing_music_directory_falls_back_to_working_directory(
    home: Path, working_directory: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Warn about a missing music directory and use the working directory."""
    storage = select_output_directory(None)

    assert storage.output_directory == working_directory
    assert warnings(caplog) == [
        (
            f"Music directory {str(home / 'Music')!r} was not found; saving "
            f"tracks to the current directory {str(working_directory)!r} "
            "instead. Choose a directory with --output-dir."
        )
    ]


def test_read_only_chosen_directory_exits(
    read_only_directory: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Exit with an error naming a chosen directory that isn't writable."""
    with pytest.raises(SystemExit) as exit_info:
        select_output_directory(read_only_directory)

    assert exit_info.value.code == 1
    assert [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.CRITICAL
    ] == [
        (
            f"Cannot save tracks to {str(read_only_directory)!r} because the "
            "directory is not writable. Choose a writable directory with "
            "--output-dir."
        )
    ]


def test_read_only_fallback_directory_exits(
    tmp_path: Path, read_only_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit when the fallback for a missing directory isn't writable."""
    monkeypatch.chdir(read_only_directory)

    with pytest.raises(SystemExit) as exit_info:
        select_output_directory(tmp_path / "missing")

    assert exit_info.value.code == 1


def test_intake_selects_output_directory(tmp_path: Path) -> None:
    """Select the output directory as part of the intake stage."""
    storage = PipelineSharedStorage(
        options=CliOptions(
            urls=["https://example.com/track"], output_dir=tmp_path
        ),
        logger=logging.getLogger(__name__),
    )

    IntakeStage.run(storage)

    assert storage.output_directory == tmp_path
