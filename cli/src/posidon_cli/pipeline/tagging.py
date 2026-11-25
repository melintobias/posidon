"""Apply downloaded source metadata to audio files."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from posidon_core.adapters.tagging.mp3 import Mp3TagWriter
from posidon_core.models import TrackMetadata
from pydantic import ValidationError
from rich import progress

from posidon_cli.logger import CONSOLE
from posidon_cli.logger import log_stage_completion
from posidon_cli.options import OutputFormat
from posidon_cli.pipeline.types import PipelineStage

if TYPE_CHECKING:
    from posidon_core.models import Track
    from posidon_core.ports import TagWriterFactory

    from posidon_cli.pipeline.types import PipelineSharedStorage


_TAG_WRITERS: dict[OutputFormat, TagWriterFactory] = {
    # Write ID3 metadata and artwork into MP3 files.
    OutputFormat.MP3: Mp3TagWriter
}
"""Factories that build tag writers for the supported output formats.

Each factory also declares the tag versions its writers accept.
"""


def check_tag_version(
    output_format: OutputFormat, tag_version: str | None
) -> None:
    """Check a requested tag version against the output format's writer.

    The check reads the writer's declarations and does not build a writer.

    Args:
        output_format: Output format whose tag writer would apply the tags.
        tag_version: Requested tag version, or `None` for the writer's
            default.

    Raises:
        ValueError: If the writer does not support the tag version. The
            message names the format and the supported versions.
    """
    factory = _TAG_WRITERS[output_format]
    if tag_version is None or tag_version in factory.supported_tag_versions:
        return

    supported = ", ".join(factory.supported_tag_versions)
    msg = (
        f"{tag_version!r} is not supported for output format "
        f"{output_format.value!r}. Supported versions: {supported}."
    )
    raise ValueError(msg)


class TaggingStage(PipelineStage):
    """Apply metadata and artwork with the writer for the output format."""

    @classmethod
    def run(cls, storage: PipelineSharedStorage) -> None:
        """Run all tagging steps against shared pipeline storage.

        Args:
            storage: Existing pipeline storage.
        """
        logger = storage.logger
        tracks = storage.tracks

        tracked_tracks = progress.track(
            tracks, description="Track tagging", console=CONSOLE
        )

        for index, track in enumerate(tracked_tracks, start=1):
            logger.info(
                "Tagging track %d/%d: %s", index, len(tracks), track.url
            )

            cls.add_file_metadata(storage, track)

        log_stage_completion(logger, logging.INFO, "Track tagging completed.")

    @staticmethod
    def add_file_metadata(storage: PipelineSharedStorage, track: Track) -> None:
        """Read downloaded metadata and tag the track's media file.

        Log invalid metadata and skip tagging the track when parsing fails.

        Args:
            storage: Existing pipeline storage.
            track: Track with downloaded media, metadata, and thumbnail paths.

        Raises:
            ValueError: If a downloaded artifact path is missing or the writer
                rejects the media file or thumbnail type.
        """
        media_path = track.artifacts.tmp_media_path
        metadata_path = track.artifacts.tmp_metadata_path
        thumbnail_path = track.artifacts.tmp_thumbnail_path

        if (
            media_path is None
            or metadata_path is None
            or thumbnail_path is None
        ):
            # TODO: Enhance error msg
            msg = f"Track has no valid download artifact: {track.url}"
            raise ValueError(msg)

        try:
            metadata = TrackMetadata.read_metadata_file(metadata_path)
        except ValidationError:
            storage.logger.exception("Applying metadata failed: %s", track.url)
            return

        options = storage.options
        tag_writer = _TAG_WRITERS[options.output_format](
            storage.logger, options.tag_version
        )
        tag_writer.write(media_path, metadata, thumbnail_path)
        track.metadata = metadata
