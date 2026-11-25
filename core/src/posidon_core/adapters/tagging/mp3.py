"""Write text tags and front cover artwork to MP3 files using Mutagen."""

from datetime import date
from mimetypes import guess_file_type
import re
from typing import ClassVar, TYPE_CHECKING

from mutagen import id3
from mutagen.mp3 import HeaderNotFoundError
from mutagen.mp3 import MP3

if TYPE_CHECKING:
    from logging import Logger
    from pathlib import Path

    from posidon_core.models import TrackMetadata

_ID3V23 = 3
"""Mutagen's version number for ID3v2.3 tags."""

_ID3V24 = 4
"""Mutagen's version number for ID3v2.4 tags."""

_ID3V2_VERSIONS: dict[str, int] = {"id3v2.3": _ID3V23, "id3v2.4": _ID3V24}
"""Mutagen's minor ID3v2 version number for each accepted tag version name."""

_V23_SEPARATOR = "/"
"""Separator joining multiple values of one text frame in ID3v2.3 tags.

ID3v2.3 has no multi-value text frames, so lists such as artists and genres
are flattened into one value, and values containing a slash become ambiguous.
"""

_V23_DATE_FRAMES = ("TYER", "TDAT", "TIME", "TRDA")
"""ID3v2.3 frames that together describe a recording date."""

_ISO_DATE = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")
"""Full or partial ISO 8601 calendar date: `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`.

The groups are the year, the optional month, and the optional day.
"""

_COMPACT_DATE = re.compile(r"(\d{4})(\d{2})(\d{2})")
"""Compact `YYYYMMDD` date, as yt-dlp reports release and upload dates.

The groups are the year, the month, and the day.
"""

type _DateParts = tuple[int, int | None, int | None]
"""Calendar-valid year, optional month, and optional day of a release date.

A day is only present together with a month.
"""


def _number_pair(number: int | None, total: int | None) -> str | None:
    """Format a track or disc position with its optional total.

    Args:
        number: One-based position on the disc or in the release.
        total: Total number of tracks on the disc or discs in the release.

    Returns:
        The position, a position/total pair with zero for an unknown position,
        or `None` when both are absent.
    """
    if number is None:
        return f"0/{total}" if total is not None else None
    return f"{number}/{total}" if total is not None else str(number)


def _parse_date(text: str) -> _DateParts | None:
    """Parse a full or partial calendar date in ISO or compact form.

    Args:
        text: Date as `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or `YYYYMMDD`.

    Returns:
        The date parts, or `None` if the text has another form or does not
        name a real calendar date.
    """
    match = _COMPACT_DATE.fullmatch(text) or _ISO_DATE.fullmatch(text)
    if match is None:
        return None

    year_text, month_text, day_text = match.groups()
    year = int(year_text)
    month = int(month_text) if month_text is not None else None
    day = int(day_text) if day_text is not None else None
    try:
        # Only an omitted part defaults to 1; an explicit zero stays invalid.
        date(year, 1 if month is None else month, 1 if day is None else day)
    except ValueError:
        return None
    return year, month, day


def _iso_date(parts: _DateParts) -> str:
    """Format date parts as a full or partial ISO 8601 date.

    Args:
        parts: Calendar-valid date parts.

    Returns:
        The date as `YYYY`, `YYYY-MM`, or `YYYY-MM-DD`.
    """
    year, month, day = parts
    text = f"{year:04d}"
    if month is not None:
        text += f"-{month:02d}"
        if day is not None:
            text += f"-{day:02d}"
    return text


def _frame_ids(tags: id3.ID3) -> set[str]:
    """Collect the IDs of the frames in a tag.

    Args:
        tags: Loaded or new ID3 tag.

    Returns:
        Four-character frame IDs, without the per-frame hash key suffixes.
    """
    return {frame.FrameID for frame in tags.values()}


class Mp3TagWriter:
    """Apply populated metadata fields and artwork in one ID3 save.

    Attributes:
        supported_tag_versions: ID3v2 versions the writer can save.
        default_tag_version: ID3v2 version saved when none is requested.
        logger: Logger that receives diagnostic tag assignments.
        tag_version: ID3v2 version name this writer saves.
    """

    supported_tag_versions: ClassVar[tuple[str, ...]] = tuple(_ID3V2_VERSIONS)
    """ID3v2 versions the writer can save, oldest first."""

    default_tag_version: ClassVar[str] = "id3v2.4"
    """ID3v2 version saved when none is requested.

    Posidon chooses it explicitly instead of relying on Mutagen's default.
    """

    def __init__(self, logger: Logger, tag_version: str | None = None) -> None:
        """Configure logging and the ID3v2 version the writer saves.

        Args:
            logger: Application logger that receives tag assignments.
            tag_version: One of `supported_tag_versions`, or `None` to save
                `default_tag_version`.

        Raises:
            ValueError: If the tag version is not supported.
        """
        self.logger = logger
        self.tag_version = (
            tag_version if tag_version is not None else self.default_tag_version
        )
        if self.tag_version not in _ID3V2_VERSIONS:
            msg = f"Unsupported MP3 tag version: {self.tag_version}"
            raise ValueError(msg)
        self._v2_version = _ID3V2_VERSIONS[self.tag_version]

    def write(
        self, media_path: Path, metadata: TrackMetadata, artwork_path: Path
    ) -> None:
        """Update the MP3's ID3 tags in place.

        Existing frames are converted to the writer's ID3v2 version before the
        new metadata and cover are applied. An existing ID3v1 tag is updated,
        but none is added.

        Args:
            media_path: Existing MP3 file to update.
            metadata: Track metadata whose populated fields are applied.
            artwork_path: Image file to embed as the front cover.

        Raises:
            ValueError: If the media has no MPEG audio header or the artwork
                filename has an unrecognized image type.
            OSError: If reading the artwork file fails.
            mutagen.MutagenError: If opening or saving the media file fails.
        """
        mime_type = guess_file_type(artwork_path)[0]
        if mime_type is None or not mime_type.startswith("image/"):
            msg = f"Unsupported thumbnail image type: {artwork_path}"
            raise ValueError(msg)

        # ID3v2.3 only allows Latin-1 and UTF-16 text.
        encoding = (
            id3.Encoding.UTF16
            if self._v2_version == _ID3V23
            else id3.Encoding.UTF8
        )
        artwork = id3.APIC(
            encoding=encoding,
            mime=mime_type,
            type=id3.PictureType.COVER_FRONT,
            desc="",  # TODO: Weigh desc options
            data=artwork_path.read_bytes(),
        )
        try:
            # Keep the raw frames so the conversion below can repair them first.
            audio = MP3(
                media_path,
                translate=False,
                load_v1=True,
                v2_version=self._v2_version,
            )
        except HeaderNotFoundError as error:
            msg = f"Unsupported media format: {media_path}"
            raise ValueError(msg) from error

        tags = audio.tags if audio.tags is not None else id3.ID3()
        if audio.tags is None:
            self.logger.debug("Input MP3 has no ID3 tag")
        else:
            self.logger.debug(
                "Input ID3 tag version is ID3v%d.%d", *tags.version[:2]
            )
        self._repair_compact_dates(tags)
        self._convert(tags)

        text_frames = {
            # track title
            id3.TIT2: metadata.title,
            # artists (ordered!)
            id3.TPE1: list(metadata.artists),
            # media title, NOT necessarily album
            id3.TALB: metadata.album,
            # album artist(s)
            id3.TPE2: metadata.album_artist,
            # composers (ordered!)
            id3.TCOM: list(metadata.composers),
            # track number + total number of tracks in the release
            id3.TRCK: _number_pair(metadata.track_number, metadata.track_total),
            # disc number + total number of disks in the release
            id3.TPOS: _number_pair(metadata.disc_number, metadata.disc_total),
            # genres (ordered!)
            id3.TCON: list(metadata.genres),
        }
        for frame, value in text_frames.items():
            if value:
                self._add_text(tags, frame, value, encoding)
        if metadata.release_date:
            self._set_release_date(tags, metadata.release_date, encoding)

        tags.add(artwork)
        tags.save(
            media_path,
            v1=id3.ID3v1SaveOptions.UPDATE,
            v2_version=self._v2_version,
            v23_sep=_V23_SEPARATOR,
        )
        self.logger.debug("Saved ID3 tag as %s", self.tag_version)

    def _repair_compact_dates(self, tags: id3.ID3) -> None:
        """Rewrite compact recording dates as ISO dates before conversion.

        Earlier Posidon versions saved yt-dlp's `YYYYMMDD` dates unchanged in
        TDRC. Mutagen would read the whole value as a year and, for ID3v2.3,
        convert it to an eight-digit TYER. Values that are not calendar-valid
        compact dates are left unchanged.

        Args:
            tags: Raw, untranslated tag loaded from the media file.
        """
        for frame in tags.getall("TDRC"):
            texts = [str(stamp) for stamp in frame.text]
            repaired = []
            for text in texts:
                parts = (
                    _parse_date(text) if _COMPACT_DATE.fullmatch(text) else None
                )
                repaired.append(_iso_date(parts) if parts else text)
            if repaired != texts:
                self.logger.debug(
                    "Repaired compact TDRC dates %r to %r", texts, repaired
                )
                frame.text = repaired

    def _convert(self, tags: id3.ID3) -> None:
        """Convert every existing frame to the writer's ID3v2 version.

        Frames that the target version cannot represent are translated or
        removed by Mutagen; for example, downgrading to ID3v2.3 turns TDRC into
        TYER and TDAT and drops frames that exist only in ID3v2.4.

        Args:
            tags: Raw tag whose frames are converted in place.
        """
        before = _frame_ids(tags)
        if self._v2_version == _ID3V23:
            tags.update_to_v23()
        else:
            tags.update_to_v24()
        after = _frame_ids(tags)

        self.logger.debug(
            "Converted ID3 frames to %s; removed %s; added %s",
            self.tag_version,
            sorted(before - after),
            sorted(after - before),
        )

    def _add_text(
        self,
        tags: id3.ID3,
        frame: type[id3.TextFrame],
        value: str | list[str],
        encoding: int,
    ) -> None:
        """Replace one text frame and log the assignment.

        Args:
            tags: Tag receiving the frame.
            frame: Text frame class to add.
            value: Single value or ordered values of the frame.
            encoding: `mutagen.id3.Encoding` value allowed by the target
                version.
        """
        self.logger.debug("Set ID3 frame %s to %r", frame.__name__, value)
        tags.add(frame(encoding=encoding, text=value))

    def _set_release_date(
        self, tags: id3.ID3, release_date: str, encoding: int
    ) -> None:
        """Replace the recording date frames with a valid release date.

        ID3v2.4 stores the date in TDRC. ID3v2.3 stores the year in TYER and,
        for full dates, the day and month in TDAT, so a year and month keeps
        only the year. Every converted ID3v2.3 date frame is cleared first so
        a stale time or date range never attaches to the new date. An invalid
        date is ignored and the existing date is kept.

        Args:
            tags: Converted tag receiving the date.
            release_date: Date as `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or
                `YYYYMMDD`.
            encoding: `mutagen.id3.Encoding` value allowed by the target
                version.
        """
        parts = _parse_date(release_date)
        if parts is None:
            self.logger.warning(
                "Ignoring invalid release date %r; keeping the existing date",
                release_date,
            )
            return

        if self._v2_version == _ID3V24:
            self._add_text(tags, id3.TDRC, _iso_date(parts), encoding)
            return

        year, month, day = parts
        for frame_id in _V23_DATE_FRAMES:
            tags.delall(frame_id)
        self._add_text(tags, id3.TYER, f"{year:04d}", encoding)
        if month is not None and day is not None:
            self._add_text(tags, id3.TDAT, f"{day:02d}{month:02d}", encoding)
