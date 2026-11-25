"""Contract for writing resolved track metadata into a media file."""

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from pathlib import Path

    from posidon_core.models import TrackMetadata


class TagWriter(Protocol):
    """Write track metadata and artwork in the target file's native format."""

    def write(
        self, media_path: Path, metadata: TrackMetadata, artwork_path: Path
    ) -> None:
        """Apply track metadata and artwork to the supplied media file in place.

        Args:
            media_path: Existing media file to update.
            metadata: Track metadata whose populated fields should be applied.
            artwork_path: Local image to embed as front cover artwork.

        Raises:
            ValueError: If the writer rejects the media format or artwork type.
        """
        ...


class TagWriterFactory(Protocol):
    """Build a tag writer and declare the tag versions it can write.

    Writer classes satisfy this protocol directly, so callers can check a
    requested version against the declarations without building a writer.

    Attributes:
        supported_tag_versions: Tag version names the writer accepts, such as
            `id3v2.4` for MP3.
        default_tag_version: Version written when none is requested. It is one
            of `supported_tag_versions`.
    """

    @property
    def supported_tag_versions(self) -> tuple[str, ...]:
        """Return the tag version names the writer accepts."""
        ...

    @property
    def default_tag_version(self) -> str:
        """Return the version written when no version is requested."""
        ...

    def __call__(self, logger: Logger, tag_version: str | None) -> TagWriter:
        """Build a writer for one tag version.

        Args:
            logger: Application logger that receives diagnostic records.
            tag_version: One of `supported_tag_versions`, or `None` to write
                `default_tag_version`.

        Returns:
            Writer that saves tags in the resolved version.

        Raises:
            ValueError: If the tag version is not supported.
        """
        ...
