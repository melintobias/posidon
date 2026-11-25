"""Tests for writing track metadata and artwork to MP3 files."""

# cspell:words Åsa Björn Kommentar Låt Søng swe ufeff

from dataclasses import dataclass
import hashlib
import logging
from typing import TYPE_CHECKING

from mutagen import id3
from mutagen.id3 import ID3
from mutagen.id3 import PictureType
from mutagen.mp3 import EasyMP3
from mutagen.mp3 import MP3
from posidon_core.adapters.tagging.mp3 import Mp3TagWriter
from posidon_core.models import TrackMetadata
import pytest

if TYPE_CHECKING:
    from pathlib import Path

MP3_FRAME = bytes((0xFF, 0xFB, 0x90, 0x64)) + bytes(413)
"""Silent 128 kilobits per second, 44.1 kHz MPEG-1 Layer III audio frame."""

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
"""PNG header used to check that the writer embeds the supplied bytes."""

AUDIO = MP3_FRAME * 4
"""MPEG audio stream of the test file, which tagging must leave unchanged."""

ID3V23_MAJOR = 3
"""Major version byte in the header of an ID3v2.3 tag."""

ID3V24_MAJOR = 4
"""Major version byte in the header of an ID3v2.4 tag."""

ID3V1_SIZE = 128
"""Size in bytes of an ID3v1 tag at the end of a file."""

TEXT_CODECS = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}
"""Python codec for each ID3v2 text encoding byte."""


@dataclass(frozen=True, slots=True)
class RawFile:
    """MP3 file contents split without Mutagen, to check bytes on disk.

    Attributes:
        major: ID3v2 major version from the tag header, or `None` without an
            ID3v2 tag.
        frames: Raw frame bodies by frame ID, in file order.
        audio: Bytes between the ID3v2 tag and the ID3v1 tag.
        v1: The ID3v1 tag, or `None` when the file has none.
    """

    major: int | None
    frames: dict[str, list[bytes]]
    audio: bytes
    v1: bytes | None

    def text(self, frame_id: str) -> list[str]:
        """Decode the values of the single text frame with an ID.

        Args:
            frame_id: Four-character text frame ID.

        Returns:
            The NUL-separated values of the frame.
        """
        (body,) = self.frames[frame_id]
        return _decode_text(body)

    def encoding(self, frame_id: str) -> int:
        """Return the text encoding byte of the single frame with an ID.

        Args:
            frame_id: Four-character ID of a frame with an encoding byte.

        Returns:
            ID3v2 text encoding number.
        """
        (body,) = self.frames[frame_id]
        return body[0]


def _decode_text(body: bytes) -> list[str]:
    """Decode a raw text frame body.

    Args:
        body: Frame body starting with the text encoding byte.

    Returns:
        The NUL-separated values of the frame.
    """
    text = body[1:].decode(TEXT_CODECS[body[0]])
    # Each UTF-16 value starts with its own byte order mark.
    return [value.lstrip("\ufeff") for value in text.rstrip("\0").split("\0")]


def _syncsafe(data: bytes) -> int:
    """Decode an ID3v2 syncsafe integer of seven bits per byte.

    Args:
        data: Big-endian syncsafe bytes.

    Returns:
        Decoded integer.
    """
    value = 0
    for byte in data:
        value = (value << 7) | byte
    return value


def read_raw(path: Path) -> RawFile:
    """Split an MP3 file into its ID3v2 frames, audio, and ID3v1 tag.

    The parser handles the unflagged tags Mutagen writes; it does not use
    Mutagen, so tests check the bytes independently of the writer's library.

    Args:
        path: MP3 file to read.

    Returns:
        The file's parts.
    """
    data = path.read_bytes()
    v1 = None
    if data[-ID3V1_SIZE:].startswith(b"TAG"):
        data, v1 = data[:-ID3V1_SIZE], data[-ID3V1_SIZE:]
    if not data.startswith(b"ID3"):
        return RawFile(major=None, frames={}, audio=data, v1=v1)

    major = data[3]
    end = 10 + _syncsafe(data[6:10])
    body = data[10:end]
    frames: dict[str, list[bytes]] = {}
    offset = 0
    while offset + 10 <= len(body) and body[offset] != 0:
        frame_id = body[offset : offset + 4].decode("ascii")
        size_bytes = body[offset + 4 : offset + 8]
        size = (
            _syncsafe(size_bytes)
            if major == ID3V24_MAJOR
            else int.from_bytes(size_bytes, "big")
        )
        start = offset + 10
        frames.setdefault(frame_id, []).append(body[start : start + size])
        offset = start + size
    return RawFile(major=major, frames=frames, audio=data[end:], v1=v1)


def id3v1_tag(title: str) -> bytes:
    """Build an ID3v1 tag with a title and blank other fields.

    Args:
        title: Latin-1 title of at most 30 characters.

    Returns:
        The 128-byte tag.
    """

    def field(text: str, size: int) -> bytes:
        """Encode one fixed-size, NUL-padded tag field.

        Args:
            text: Field value.
            size: Field size in bytes.

        Returns:
            Padded field bytes.
        """
        return text.encode("latin-1").ljust(size, b"\0")

    return (
        b"TAG"
        + field(title, 30)
        + field("", 30)
        + field("", 30)
        + field("", 4)
        + field("", 30)
        + bytes([255])
    )


def save_existing_tag(
    path: Path, frames: list[id3.Frame], v2_version: int
) -> None:
    """Save a tag with the given frames into an untagged test MP3.

    Args:
        path: Untagged MP3 file.
        frames: Frames to save unchanged.
        v2_version: ID3v2 minor version to save, 3 or 4.
    """
    tags = ID3()
    for frame in frames:
        tags.add(frame)
    tags.save(path, v1=id3.ID3v1SaveOptions.REMOVE, v2_version=v2_version)


@pytest.fixture
def writer() -> Mp3TagWriter:
    """Create an MP3 tag writer that logs to pytest's capture.

    Returns:
        Writer using a propagating test logger.
    """
    return Mp3TagWriter(logging.getLogger(__name__))


@pytest.fixture
def media_path(tmp_path: Path) -> Path:
    """Create an untagged MP3 file.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        Path to the MP3 file.
    """
    path = tmp_path / "track.mp3"
    path.write_bytes(AUDIO)
    return path


@pytest.fixture
def artwork_path(tmp_path: Path) -> Path:
    """Create a PNG artwork file.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        Path to the artwork file.
    """
    path = tmp_path / "track.png"
    path.write_bytes(PNG_SIGNATURE)
    return path


def read_tags(media_path: Path) -> dict[str, list[str]]:
    """Read the easy tags saved in an MP3 file.

    Args:
        media_path: MP3 file to read.

    Returns:
        Easy tag values by key.
    """
    return dict(EasyMP3(media_path))


def test_write_applies_text_and_cover(
    writer: Mp3TagWriter, media_path: Path, artwork_path: Path
) -> None:
    """Update text and cover art across retries while preserving other tags."""
    original = EasyMP3(media_path)
    original["copyright"] = ["Example Records"]
    original.save()
    metadata = TrackMetadata(
        title="Song",
        artists=("Artist", "Featured Artist"),
        album="Album",
        album_artist="Album Artist",
        composers=("Composer",),
        track_number=3,
        track_total=12,
        disc_number=1,
        disc_total=2,
        release_date="20240115",
        genres=("Pop", "Rock"),
    )

    writer.write(media_path, metadata, artwork_path)
    writer.write(media_path, metadata, artwork_path)

    assert read_tags(media_path) == {
        "title": ["Song"],
        "artist": ["Artist", "Featured Artist"],
        "album": ["Album"],
        "albumartist": ["Album Artist"],
        "composer": ["Composer"],
        "tracknumber": ["3/12"],
        "discnumber": ["1/2"],
        "date": ["2024-01-15"],
        "genre": ["Pop", "Rock"],
        "copyright": ["Example Records"],
    }
    (cover,) = ID3(media_path).getall("APIC")
    assert cover.type == PictureType.COVER_FRONT
    assert cover.mime == "image/png"
    assert cover.data == PNG_SIGNATURE


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (TrackMetadata(track_number=3, track_total=12), ["3/12"]),
        (TrackMetadata(track_number=3), ["3"]),
        (TrackMetadata(track_total=12), ["0/12"]),
    ],
)
def test_write_formats_track_position(
    writer: Mp3TagWriter,
    media_path: Path,
    artwork_path: Path,
    metadata: TrackMetadata,
    expected: list[str],
) -> None:
    """Combine the track position and total into one tag value."""
    writer.write(media_path, metadata, artwork_path)

    assert read_tags(media_path)["tracknumber"] == expected


def test_write_skips_unpopulated_fields(
    writer: Mp3TagWriter, media_path: Path, artwork_path: Path
) -> None:
    """Leave tags absent for metadata fields without a value."""
    writer.write(media_path, TrackMetadata(title="Song"), artwork_path)

    assert read_tags(media_path) == {"title": ["Song"]}


def test_write_rejects_unsupported_media(
    writer: Mp3TagWriter, tmp_path: Path, artwork_path: Path
) -> None:
    """Reject an unsupported media file before writing ID3 tags into it."""
    media_path = tmp_path / "track.txt"
    media_path.write_bytes(b"not audio")

    with pytest.raises(ValueError, match="Unsupported media format"):
        writer.write(media_path, TrackMetadata(title="Song"), artwork_path)

    assert media_path.read_bytes() == b"not audio"


def test_writer_declares_id3v2_versions() -> None:
    """Declare both ID3v2 versions and default to ID3v2.4."""
    assert Mp3TagWriter.supported_tag_versions == ("id3v2.3", "id3v2.4")
    assert Mp3TagWriter.default_tag_version == "id3v2.4"


@pytest.mark.parametrize("tag_version", ["id3v2.2", "ID3v2.3", "2.4", ""])
def test_writer_rejects_unsupported_tag_version(tag_version: str) -> None:
    """Reject a tag version the writer cannot save.

    Args:
        tag_version: Unsupported version name.
    """
    with pytest.raises(ValueError, match="Unsupported MP3 tag version"):
        Mp3TagWriter(logging.getLogger(__name__), tag_version)


@pytest.mark.parametrize(
    ("tag_version", "major", "encoding"),
    [(None, 4, 3), ("id3v2.4", 4, 3), ("id3v2.3", 3, 1)],
)
def test_write_saves_requested_version_on_disk(
    media_path: Path,
    artwork_path: Path,
    tag_version: str | None,
    major: int,
    encoding: int,
) -> None:
    """Save the requested or default version with its text encoding.

    Args:
        media_path: Untagged MP3 file.
        artwork_path: PNG artwork file.
        tag_version: Requested version, or `None` for the default.
        major: Expected major version in the tag header.
        encoding: Expected text encoding byte: UTF-8 or UTF-16.
    """
    writer = Mp3TagWriter(logging.getLogger(__name__), tag_version)

    writer.write(media_path, TrackMetadata(title="Søng ♪"), artwork_path)

    raw = read_raw(media_path)
    assert raw.major == major
    assert raw.text("TIT2") == ["Søng ♪"]
    assert raw.encoding("TIT2") == encoding
    assert raw.encoding("APIC") == encoding
    (cover,) = raw.frames["APIC"]
    assert cover.endswith(PNG_SIGNATURE)
    assert hashlib.sha256(raw.audio).digest() == hashlib.sha256(AUDIO).digest()
    assert raw.v1 is None
    info = MP3(media_path).info
    assert info is not None
    assert info.length > 0


@pytest.mark.parametrize(
    ("tag_version", "expected"),
    [("id3v2.3", ["Artist/Feat/Two"]), ("id3v2.4", ["Artist", "Feat/Two"])],
)
def test_write_flattens_lists_only_for_v23(
    media_path: Path, artwork_path: Path, tag_version: str, expected: list[str]
) -> None:
    """Join list values with a slash in ID3v2.3 and keep them in ID3v2.4.

    A slash inside one value becomes indistinguishable from the separator.

    Args:
        media_path: Untagged MP3 file.
        artwork_path: PNG artwork file.
        tag_version: Version to save.
        expected: Raw TPE1 values on disk.
    """
    writer = Mp3TagWriter(logging.getLogger(__name__), tag_version)
    metadata = TrackMetadata(
        artists=("Artist", "Feat/Two"),
        composers=("Ann", "Bo"),
        genres=("Pop", "Rock"),
    )

    writer.write(media_path, metadata, artwork_path)

    raw = read_raw(media_path)
    assert raw.text("TPE1") == expected
    flat = tag_version == "id3v2.3"
    assert raw.text("TCOM") == (["Ann/Bo"] if flat else ["Ann", "Bo"])
    assert raw.text("TCON") == (["Pop/Rock"] if flat else ["Pop", "Rock"])


@pytest.mark.parametrize(
    ("release_date", "v23", "v24"),
    [
        ("2024", {"TYER": ["2024"]}, {"TDRC": ["2024"]}),
        ("2024-01", {"TYER": ["2024"]}, {"TDRC": ["2024-01"]}),
        (
            "2024-01-15",
            {"TYER": ["2024"], "TDAT": ["1501"]},
            {"TDRC": ["2024-01-15"]},
        ),
        (
            "20240229",
            {"TYER": ["2024"], "TDAT": ["2902"]},
            {"TDRC": ["2024-02-29"]},
        ),
        ("20230229", {}, {}),
        ("2024-13", {}, {}),
        ("2024-00", {}, {}),
        ("2024-01-00", {}, {}),
        ("20240015", {}, {}),
        ("20240100", {}, {}),
        ("2024-02-30", {}, {}),
        ("202401", {}, {}),
        ("15/01/2024", {}, {}),
        ("0000", {}, {}),
    ],
)
def test_write_maps_release_date_per_version(
    media_path: Path,
    artwork_path: Path,
    release_date: str,
    v23: dict[str, list[str]],
    v24: dict[str, list[str]],
) -> None:
    """Write valid full or partial dates and skip invalid ones.

    Args:
        media_path: Untagged MP3 file.
        artwork_path: PNG artwork file.
        release_date: Release date supplied by the provider.
        v23: Expected ID3v2.3 date frames and values.
        v24: Expected ID3v2.4 date frames and values.
    """
    date_ids = {"TYER", "TDAT", "TIME", "TRDA", "TDRC"}
    for tag_version, expected in (("id3v2.3", v23), ("id3v2.4", v24)):
        media_path.write_bytes(AUDIO)
        writer = Mp3TagWriter(logging.getLogger(__name__), tag_version)

        writer.write(
            media_path, TrackMetadata(release_date=release_date), artwork_path
        )

        raw = read_raw(media_path)
        actual = {
            frame_id: raw.text(frame_id)
            for frame_id in raw.frames
            if frame_id in date_ids
        }
        assert actual == expected, tag_version


def test_write_downgrades_v24_tag_to_v23(
    media_path: Path, artwork_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Convert an old Posidon ID3v2.4 tag and keep compatible frames.

    The compact TDRC date is repaired before conversion, Unicode survives in
    converted and preserved frames, and frames that exist only in ID3v2.4
    are dropped.
    """
    utf8 = id3.Encoding.UTF8
    save_existing_tag(
        media_path,
        [
            id3.TPE1(encoding=utf8, text=["Åsa", "Björn"]),
            id3.TDRC(encoding=utf8, text="20240115"),
            id3.TSOP(encoding=utf8, text="Sort"),
            id3.TXXX(encoding=utf8, desc="Mood", text="Glad ☀"),
            id3.COMM(encoding=utf8, lang="swe", desc="", text="Kommentar ✓"),
            id3.APIC(
                encoding=utf8,
                mime="image/jpeg",
                type=id3.PictureType.COVER_FRONT,
                desc="",
                data=b"old cover",
            ),
        ],
        v2_version=4,
    )
    writer = Mp3TagWriter(logging.getLogger(__name__), "id3v2.3")
    caplog.set_level(logging.DEBUG)

    writer.write(media_path, TrackMetadata(title="Låt"), artwork_path)

    raw = read_raw(media_path)
    assert raw.major == ID3V23_MAJOR
    assert set(raw.frames) == {
        "TIT2",
        "TPE1",
        "TYER",
        "TDAT",
        "TXXX",
        "COMM",
        "APIC",
    }
    assert raw.text("TPE1") == ["Åsa/Björn"]
    assert raw.text("TYER") == ["2024"]
    assert raw.text("TDAT") == ["1501"]
    assert raw.text("TXXX") == ["Mood", "Glad ☀"]
    assert raw.encoding("TPE1") == id3.Encoding.UTF16
    assert raw.encoding("TXXX") == id3.Encoding.UTF16
    (comment,) = raw.frames["COMM"]
    assert _decode_text(comment[:1] + comment[4:]) == ["", "Kommentar ✓"]
    (cover,) = raw.frames["APIC"]
    assert cover.endswith(PNG_SIGNATURE)
    assert raw.audio == AUDIO
    messages = [record.getMessage() for record in caplog.records]
    assert "Input ID3 tag version is ID3v2.4" in messages
    assert (
        "Converted ID3 frames to id3v2.3; removed ['TDRC', 'TSOP']; "
        "added ['TDAT', 'TYER']" in messages
    )
    assert "Saved ID3 tag as id3v2.3" in messages


def test_write_repairs_compact_v24_date(
    writer: Mp3TagWriter, media_path: Path, artwork_path: Path
) -> None:
    """Rewrite an old compact TDRC date as an ISO date in ID3v2.4."""
    save_existing_tag(
        media_path,
        [id3.TDRC(encoding=id3.Encoding.UTF8, text="20240115")],
        v2_version=4,
    )

    writer.write(media_path, TrackMetadata(title="Song"), artwork_path)

    assert read_raw(media_path).text("TDRC") == ["2024-01-15"]


@pytest.mark.parametrize(
    ("tag_version", "expected"),
    [("id3v2.3", {"TYER": ["20241345"]}), ("id3v2.4", {"TDRC": ["20241345"]})],
)
def test_write_keeps_malformed_old_date_without_new_date(
    media_path: Path,
    artwork_path: Path,
    tag_version: str,
    expected: dict[str, list[str]],
) -> None:
    """Leave an old compact date that is not a calendar date unchanged.

    Args:
        media_path: Untagged MP3 file.
        artwork_path: PNG artwork file.
        tag_version: Version to save.
        expected: Date frames left after conversion.
    """
    save_existing_tag(
        media_path,
        [id3.TDRC(encoding=id3.Encoding.UTF8, text="20241345")],
        v2_version=4,
    )
    writer = Mp3TagWriter(logging.getLogger(__name__), tag_version)

    writer.write(media_path, TrackMetadata(title="Song"), artwork_path)

    raw = read_raw(media_path)
    dates = {
        key: raw.text(key) for key in raw.frames if key not in {"TIT2", "APIC"}
    }
    assert dates == expected


@pytest.mark.parametrize("old_date", ["20241345", "2020-05-06T10:30:00"])
def test_write_replaces_converted_date_in_v23(
    media_path: Path, artwork_path: Path, old_date: str
) -> None:
    """Clear stale converted date frames before writing a new v2.3 date.

    A converted time must not attach to the new date, and a malformed old
    date must not survive.

    Args:
        media_path: Untagged MP3 file.
        artwork_path: PNG artwork file.
        old_date: Existing TDRC value.
    """
    save_existing_tag(
        media_path,
        [id3.TDRC(encoding=id3.Encoding.UTF8, text=old_date)],
        v2_version=4,
    )
    writer = Mp3TagWriter(logging.getLogger(__name__), "id3v2.3")

    writer.write(
        media_path, TrackMetadata(release_date="2023-05"), artwork_path
    )

    raw = read_raw(media_path)
    assert {"TDAT", "TIME", "TRDA", "TDRC"}.isdisjoint(raw.frames)
    assert raw.text("TYER") == ["2023"]


def _raw_v23_date_frames() -> list[id3.Frame]:
    """Build a complete set of ID3v2.3 date frames for an existing tag.

    Returns:
        TYER, TDAT, TIME, and TRDA frames for 1 February 1999 at noon.
    """
    latin1 = id3.Encoding.LATIN1
    return [
        id3.TYER(encoding=latin1, text="1999"),
        id3.TDAT(encoding=latin1, text="0102"),
        id3.TIME(encoding=latin1, text="1200"),
        id3.TRDA(encoding=latin1, text="1st February 1999"),
    ]


def test_write_replaces_raw_v23_date(
    media_path: Path, artwork_path: Path
) -> None:
    """Replace every date frame of a raw ID3v2.3 tag with a fresh date."""
    save_existing_tag(media_path, _raw_v23_date_frames(), v2_version=3)
    writer = Mp3TagWriter(logging.getLogger(__name__), "id3v2.3")

    writer.write(
        media_path, TrackMetadata(release_date="20240115"), artwork_path
    )

    raw = read_raw(media_path)
    assert raw.major == ID3V23_MAJOR
    assert {"TIME", "TRDA"}.isdisjoint(raw.frames)
    assert raw.text("TYER") == ["2024"]
    assert raw.text("TDAT") == ["1501"]


def test_write_keeps_raw_v23_date_for_invalid_date(
    media_path: Path, artwork_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Keep the existing ID3v2.3 date when the new date is invalid."""
    save_existing_tag(media_path, _raw_v23_date_frames(), v2_version=3)
    writer = Mp3TagWriter(logging.getLogger(__name__), "id3v2.3")

    writer.write(
        media_path, TrackMetadata(release_date="2024-02-30"), artwork_path
    )

    raw = read_raw(media_path)
    assert raw.text("TYER") == ["1999"]
    assert raw.text("TDAT") == ["0102"]
    assert raw.text("TIME") == ["1200"]
    assert raw.text("TRDA") == ["1st February 1999"]
    assert [record.getMessage() for record in caplog.records] == [
        "Ignoring invalid release date '2024-02-30'; keeping the existing date"
    ]


def test_write_upgrades_raw_v23_date_to_v24(
    writer: Mp3TagWriter, media_path: Path, artwork_path: Path
) -> None:
    """Convert the existing ID3v2.3 date to TDRC when no date is supplied."""
    save_existing_tag(media_path, _raw_v23_date_frames(), v2_version=3)

    writer.write(media_path, TrackMetadata(title="Song"), artwork_path)

    raw = read_raw(media_path)
    assert raw.major == ID3V24_MAJOR
    assert {"TYER", "TDAT", "TIME", "TRDA"}.isdisjoint(raw.frames)
    assert raw.text("TDRC") == ["1999-02-01T12:00:00"]


@pytest.mark.parametrize("tag_version", ["id3v2.3", "id3v2.4"])
def test_write_updates_existing_id3v1_tag(
    media_path: Path, artwork_path: Path, tag_version: str
) -> None:
    """Fall back to ID3v1 values and update, but never add, an ID3v1 tag.

    Args:
        media_path: Untagged MP3 file.
        artwork_path: PNG artwork file.
        tag_version: Version to save.
    """
    untagged_path = media_path.with_name("untagged.mp3")
    untagged_path.write_bytes(AUDIO)
    media_path.write_bytes(AUDIO + id3v1_tag("Old Title"))
    writer = Mp3TagWriter(logging.getLogger(__name__), tag_version)
    metadata = TrackMetadata(artists=("New Artist",))

    writer.write(media_path, metadata, artwork_path)
    writer.write(untagged_path, metadata, artwork_path)

    raw = read_raw(media_path)
    assert raw.text("TIT2") == ["Old Title"]
    assert raw.text("TPE1") == ["New Artist"]
    assert raw.audio == AUDIO
    assert raw.v1 is not None
    assert raw.v1[3:33].rstrip(b"\0") == b"Old Title"
    assert raw.v1[33:63].rstrip(b"\0") == b"New Artist"
    assert read_raw(untagged_path).v1 is None


def test_write_is_stable_across_repeated_saves(
    media_path: Path, artwork_path: Path
) -> None:
    """Keep one cover and the same bytes across repeated and mixed saves."""
    metadata = TrackMetadata(
        title="Søng",
        artists=("A", "B"),
        release_date="20240115",
        genres=("Pop",),
    )
    v23 = Mp3TagWriter(logging.getLogger(__name__), "id3v2.3")
    v24 = Mp3TagWriter(logging.getLogger(__name__), "id3v2.4")

    v23.write(media_path, metadata, artwork_path)
    first = media_path.read_bytes()
    v23.write(media_path, metadata, artwork_path)
    assert media_path.read_bytes() == first

    v24.write(media_path, metadata, artwork_path)
    v23.write(media_path, metadata, artwork_path)

    raw = read_raw(media_path)
    assert raw.major == ID3V23_MAJOR
    assert len(raw.frames["APIC"]) == 1
    assert raw.text("TPE1") == ["A/B"]
    assert raw.text("TYER") == ["2024"]
    assert raw.text("TDAT") == ["1501"]
    assert raw.audio == AUDIO
