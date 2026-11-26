"""Tests for validating source URLs against the schemes a caller allows."""

from posidon_core.pipeline.intake import validate_url
import pytest

HTTP_SCHEMES = frozenset({"http", "https"})
"""Schemes allowed by the tests that don't depend on a specific scheme set."""


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/track", "https://example.com/track"),
        ("http://example.com/track", "http://example.com/track"),
        ("HTTPS://Example.com/track", "https://example.com/track"),
    ],
    ids=["https", "http", "uppercase"],
)
def test_allowed_scheme_is_parsed(url: str, expected: str) -> None:
    """Return the normalized URL when its scheme is allowed.

    Args:
        url: Raw source URL with an allowed scheme.
        expected: URL after Pydantic's normalization.
    """
    parsed = validate_url(url, HTTP_SCHEMES)

    assert parsed is not None
    assert str(parsed) == expected


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/track.mp3",
        "file:///home/user/track.mp3",
        "mailto:user@example.com",
        "ytsearch1:some song",
    ],
    ids=["ftp", "file", "mailto", "pseudo-scheme"],
)
def test_other_scheme_is_rejected(url: str) -> None:
    """Return `None` for a well-formed URL whose scheme isn't allowed.

    Args:
        url: URL that Pydantic parses but whose scheme isn't allowed.
    """
    assert validate_url(url, HTTP_SCHEMES) is None


@pytest.mark.parametrize(
    "url",
    ["", "example.com/track", "https://"],
    ids=["empty", "no-scheme", "no-host"],
)
def test_malformed_url_is_rejected(url: str) -> None:
    """Return `None` for input that Pydantic can't parse as a URL.

    Args:
        url: Input that isn't an absolute URL.
    """
    assert validate_url(url, HTTP_SCHEMES) is None


def test_caller_chooses_allowed_schemes() -> None:
    """Accept a non-HTTP scheme only when the caller allows it."""
    url = "ftp://example.com/track.mp3"

    assert validate_url(url, {"ftp"}) is not None
    assert validate_url(url, set()) is None
