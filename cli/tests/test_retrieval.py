"""Tests for the retrieval stage's converter check and post-processing."""

# cspell:words IHDR xerror rawvideo

import logging
import re
import shutil
import subprocess  # noqa: S404
from typing import NoReturn, TYPE_CHECKING

from posidon_cli.options import CliOptions
from posidon_cli.options import ThumbnailFormat
from posidon_cli.pipeline.retrieval import RetrievalStage
from posidon_cli.pipeline.types import PipelineSharedStorage
from posidon_core.models import Track
from pydantic import AnyUrl
import pytest
from yt_dlp import YoutubeDL

# Pyright's bundled yt-dlp stubs omit the FFmpeg post-processors.
from yt_dlp.postprocessor import (
    FFmpegPostProcessor,  # pyright: ignore[reportAttributeAccessIssue]
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("thumbnail_format", "expected_header"),
    [
        (ThumbnailFormat.JPG, rb"\xff\xd8\xff"),
        (ThumbnailFormat.PNG, rb"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"),
        (ThumbnailFormat.WEBP, rb"RIFF....WEBP"),
    ],
    ids=["jpeg", "png", "webp"],
)
def test_thumbnail_postprocessor_encodes_requested_format(
    tmp_path: Path, thumbnail_format: ThumbnailFormat, expected_header: bytes
) -> None:
    """Produce a decodable image with the requested format's binary header.

    Args:
        tmp_path: Per-test directory for input and converted thumbnails.
        thumbnail_format: Target encoding configured on the retrieval stage.
        expected_header: Byte pattern at the start of the encoded output.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is required for thumbnail conversion")

    # A 2 by 2 red image in binary PPM forces conversion for every target.
    source = tmp_path / "cover.ppm"
    source.write_bytes(b"P6\n2 2\n255\n" + b"\xff\x00\x00" * 4)
    track = Track(url=AnyUrl("https://example.com/track"))
    track.artifacts.tmp_directory = tmp_path
    storage = PipelineSharedStorage(
        options=CliOptions(thumbnail_format=thumbnail_format)
    )
    info = {
        # Thumbnail records available after download.
        "thumbnails": [
            {
                "url": source.as_uri(),  # Source URL for yt-dlp's reporting.
                "filepath": str(source),  # Local input to the postprocessor.
            }
        ]
    }
    options = RetrievalStage.get_ytdlp_options(storage, track)
    # yt-dlp's stubs narrow the option and info mappings used at runtime.
    with YoutubeDL(options) as ydl:  # pyright: ignore[reportArgumentType]
        processed_info, _ = ydl.pre_process(
            info,  # pyright: ignore[reportArgumentType]
            key="before_dl",
            files_to_move={str(source): str(source)},
        )
        output = RetrievalStage.get_thumbnail_path(ydl, processed_info)

    image = output.read_bytes()
    assert re.match(expected_header, image, re.DOTALL), image[:16].hex(" ")

    # Read from stdin so the decoder cannot infer the format from a filename.
    decoded = subprocess.run(  # noqa: S603
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-i",
            "pipe:0",
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        input=image,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert decoded.returncode == 0, decoded.stderr.decode(errors="replace")
    assert len(decoded.stdout) == 2 * 2 * 3


def retrieval_storage(
    thumbnail_format: ThumbnailFormat,
) -> PipelineSharedStorage:
    """Create pipeline storage holding one track that hasn't been retrieved.

    Args:
        thumbnail_format: Thumbnail format selected for the run.

    Returns:
        Storage with a single track and a test logger.
    """
    storage = PipelineSharedStorage(
        options=CliOptions(thumbnail_format=thumbnail_format),
        logger=logging.getLogger(__name__),
    )
    storage.tracks = (Track(url=AnyUrl("https://example.com/track")),)
    return storage


@pytest.mark.parametrize("thumbnail_format", list(ThumbnailFormat))
def test_missing_ffmpeg_exits_before_download(
    thumbnail_format: ThumbnailFormat,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exit with an actionable error before downloading without FFmpeg.

    Every supported audio format is converted with FFmpeg, so the check
    applies whatever thumbnail format is selected.

    Args:
        thumbnail_format: Thumbnail format selected for the run.
        monkeypatch: Fixture hiding FFmpeg and guarding against downloads.
        caplog: Fixture holding the captured log records.
    """

    def fail_download(*unused_args: object) -> NoReturn:
        """Fail the test if retrieval starts a download.

        Raises:
            AssertionError: Always.
        """
        raise AssertionError("Retrieval started a download without FFmpeg")

    monkeypatch.setattr(FFmpegPostProcessor, "available", False)
    monkeypatch.setattr(RetrievalStage, "download_track", fail_download)
    storage = retrieval_storage(thumbnail_format)

    with pytest.raises(SystemExit) as exit_info:
        RetrievalStage.run(storage)

    assert exit_info.value.code == 1
    assert storage.tracks[0].artifacts.tmp_directory is None
    assert [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.CRITICAL
    ] == [
        (
            "FFmpeg was not found, but it is required to convert the "
            "downloaded media to the selected formats. Install FFmpeg and "
            "make sure the 'ffmpeg' command is on PATH."
        )
    ]


def test_available_ffmpeg_passes_converter_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continue without an error when yt-dlp finds FFmpeg.

    Args:
        monkeypatch: Fixture reporting FFmpeg as available.
    """
    monkeypatch.setattr(FFmpegPostProcessor, "available", True)

    RetrievalStage.check_converter(retrieval_storage(ThumbnailFormat.JPG))
