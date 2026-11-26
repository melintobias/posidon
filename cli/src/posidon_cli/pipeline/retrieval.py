"""Retrieve and process downloaded media and metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging
from pathlib import Path
from typing import cast, TYPE_CHECKING

from rich import progress
from yt_dlp import YoutubeDL

# Pyright's bundled yt-dlp stubs omit the FFmpeg post-processors.
from yt_dlp.postprocessor import (
    FFmpegPostProcessor,  # pyright: ignore[reportAttributeAccessIssue]
)
from yt_dlp.postprocessor import get_postprocessor

from posidon_cli.logger import CONSOLE
from posidon_cli.logger import log_stage_completion
from posidon_cli.models.yt_dlp import DownloadArtifact
from posidon_cli.options import ThumbnailFormat
from posidon_cli.pipeline.types import PipelineStage

if TYPE_CHECKING:
    from posidon_core.models import Track
    from pydantic import AnyUrl

    from posidon_cli.pipeline.types import PipelineSharedStorage

URL_SCHEMES = frozenset({"http", "https", "ftp", "data"})
"""URL schemes that yt-dlp downloads with the options used by this stage.

yt-dlp's built-in request handler fetches these schemes. It refuses `file`
URLs unless the `enable_file_urls` option is set, which this stage doesn't do.
Inputs that only some yt-dlp extractors accept, such as `ytsearch1:query` or
`rtmp://` URLs, are left out.
"""

_MISSING_FFMPEG = (
    "FFmpeg was not found, but it is required to convert the downloaded "
    "media to the selected formats. Install FFmpeg and make sure the "
    "'ffmpeg' command is on PATH."
)
"""Error logged before any download when the converter is missing."""


class RetrievalStage(PipelineStage):
    """Retrieve and process downloaded media and metadata."""

    @classmethod
    def run(cls, storage: PipelineSharedStorage) -> None:
        """Run all retrieval steps against shared pipeline storage.

        Args:
            storage: Existing pipeline storage.

        Raises:
            SystemExit: If the converter needed for the selected formats is
                missing. Nothing is downloaded in that case.
        """
        cls.check_converter(storage)

        logger = storage.logger
        tracks = storage.tracks

        tracked_tracks = progress.track(
            tracks, description="Track retrieval", console=CONSOLE
        )

        for index, track in enumerate(tracked_tracks, start=1):
            logger.info(
                "Retrieving track %d/%d: %s", index, len(tracks), track.url
            )

            options = cls.get_ytdlp_options(storage, track)
            with YoutubeDL(options) as ydl:
                download_artifact = cls.download_track(ydl, track.url)
                track.apply_download_artifact(download_artifact)

                logger.debug(
                    "Downloaded media to %r, metadata to %r, "
                    "and thumbnail to %r",
                    str(download_artifact.media_path),
                    str(download_artifact.metadata_path),
                    str(download_artifact.thumbnail_path),
                )

        log_stage_completion(logger, logging.INFO, "Track retrieval completed")

    @staticmethod
    def check_converter(storage: PipelineSharedStorage) -> None:
        """Exit before any download if the selected formats lack a converter.

        yt-dlp runs post-processors only after a download finishes, so without
        this check a missing FFmpeg would surface after the first download.
        FFmpeg is found the same way yt-dlp finds it when converting.

        Args:
            storage: Pipeline storage containing the requested formats and the
                logger that reports a missing converter.

        Raises:
            SystemExit: If a configured post-processor needs FFmpeg and FFmpeg
                cannot be found.
        """
        post_processors = RetrievalStage.get_postprocessors(storage)
        needs_ffmpeg = any(
            issubclass(get_postprocessor(item["key"]), FFmpegPostProcessor)
            for item in post_processors
        )
        if needs_ffmpeg and not FFmpegPostProcessor().available:
            storage.logger.critical(_MISSING_FFMPEG)
            raise SystemExit(1)

    @staticmethod
    def download_track(ydl: YoutubeDL, url: AnyUrl) -> DownloadArtifact:
        """Download one URL and collect its media, metadata, and thumbnail.

        Args:
            ydl: Configured yt-dlp downloader used for this track.
            url: Source URL to download.

        Returns:
            Artifact containing the downloaded media, metadata, and thumbnail
            paths.

        Raises:
            TypeError: If yt-dlp does not return an information mapping.
        """
        info = ydl.extract_info(str(url), download=True)
        if not isinstance(info, Mapping):
            msg = f"yt-dlp returned no item information for {url}"
            raise TypeError(msg)

        return DownloadArtifact(
            metadata_path=RetrievalStage.get_metadata_path(ydl, info),
            thumbnail_path=RetrievalStage.get_thumbnail_path(ydl, info),
            media_path=RetrievalStage.get_media_path(info),
        )

    @staticmethod
    def get_metadata_path(ydl: YoutubeDL, info: Mapping[str, object]) -> Path:
        """Return the metadata JSON path.

        Raises:
            ValueError: If yt-dlp provides no metadata path.
        """
        filepath = info.get("infojson_filename") or ydl.prepare_filename(
            info, "infojson"
        )
        if not isinstance(filepath, str) or not filepath:
            raise ValueError("yt-dlp returned no metadata filepath")
        return Path(filepath)

    @staticmethod
    def get_thumbnail_path(ydl: YoutubeDL, info: Mapping[str, object]) -> Path:
        """Return the thumbnail path after yt-dlp conversion and file moves.

        Args:
            ydl: Configured downloader, used to resolve a moved thumbnail.
            info: yt-dlp result for the downloaded item.

        Raises:
            TypeError: If yt-dlp provides no thumbnail filepath.
        """
        thumbnails = cast(
            "Sequence[Mapping[str, object]]", info.get("thumbnails", ())
        )
        path = next(
            filter(None, (item.get("filepath") for item in thumbnails)), None
        )
        if not isinstance(path, str):
            raise TypeError("yt-dlp returned no downloaded thumbnail filepath")
        path = Path(path)
        if path.exists():
            return path
        return Path(ydl.prepare_filename(info, "thumbnail")).with_suffix(
            path.suffix
        )

    @staticmethod
    def get_media_path(info: Mapping[str, object]) -> Path:
        """Return the post-processed media path, falling back to the download.

        Raises:
            ValueError: If no media path is available.
        """
        requested = cast(
            "Sequence[Mapping[str, object]]",
            info.get("requested_downloads") or (),
        )
        filepath = info.get("filepath") or next(
            filter(None, (item.get("filepath") for item in requested)), None
        )
        filepath = filepath or info.get("_filename")
        if not isinstance(filepath, str) or not filepath:
            raise ValueError("yt-dlp returned no downloaded media filepath")
        return Path(filepath)

    @staticmethod
    def get_postprocessors(
        storage: PipelineSharedStorage,
    ) -> list[dict[str, str]]:
        """Build the yt-dlp post-processors for the requested formats.

        Args:
            storage: Shared pipeline storage containing the requested formats
                and logger.

        Returns:
            yt-dlp post-processor definitions, each naming its class with the
            `key` entry.
        """
        logger = storage.logger
        output_format = storage.options.output_format
        thumbnail_format = storage.options.thumbnail_format

        post_processors = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": output_format.value,  # Target audio format.
            }
        ]

        if thumbnail_format is not ThumbnailFormat.ORIGINAL:
            logger.debug(
                "Converting thumbnail to format %r", thumbnail_format.value
            )
            post_processors.append({
                "key": "FFmpegThumbnailsConvertor",
                "format": thumbnail_format.value,
                "when": "before_dl",  # Thumbnail is already downloaded.
            })

        return post_processors

    @staticmethod
    def get_ytdlp_options(
        storage: PipelineSharedStorage, track: Track
    ) -> dict[str, object]:
        """Build yt-dlp options for the requested audio format and sidecars.

        Args:
            storage: Shared pipeline storage containing the requested formats
                and logger.
            track: Track whose temporary directory receives the outputs.

        Returns:
            Python API options for the requested outputs.
        """
        post_processors = RetrievalStage.get_postprocessors(storage)

        return {
            "postprocessors": post_processors,  # Convert the audio and artwork.
            "writeinfojson": True,  # Write metadata JSON.
            "writethumbnail": True,  # Download thumbnail.
            "format": "bestaudio/best",  # Prefer audio, allow combined media.
            "outtmpl": "%(title)s.%(ext)s",  # Template for media filename.
            "noplaylist": True,  # Treat one URL as one track.
            "quiet": True,  # Suppress routine output.
            "no_warnings": True,  # Suppress warning output.
            "paths": {"home": str(track.tmp_directory)},  # Track output dir.
        }
