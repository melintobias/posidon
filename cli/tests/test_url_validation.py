"""Tests for the URL schemes accepted by the CLI intake stage."""

import logging

from posidon_cli.options import CliOptions
from posidon_cli.pipeline.intake import UrlValidationSubStage
from posidon_cli.pipeline.types import PipelineSharedStorage
import pytest

ACCEPTED_URLS = {
    "https": "https://example.com/track",
    "http": "http://example.com/track",
    "ftp": "ftp://example.com/track.mp3",
    "data": "data:audio/mpeg;base64,AAAA",
}
"""Inputs with a scheme yt-dlp downloads by default, keyed by test ID."""

REJECTED_URLS = {
    "file": "file:///home/user/track.mp3",
    "mailto": "mailto:user@example.com",
    "rtmp": "rtmp://example.com/live/track",
    "search": "ytsearch1:some song",
}
"""Inputs that Pydantic parses but the CLI rejects, keyed by test ID."""


def validate(*urls: str) -> PipelineSharedStorage:
    """Run URL validation on the given command-line URLs.

    Args:
        *urls: Raw URLs as supplied on the command line.

    Returns:
        Pipeline storage holding the accepted URLs.
    """
    storage = PipelineSharedStorage(
        options=CliOptions(urls=list(urls)), logger=logging.getLogger(__name__)
    )
    UrlValidationSubStage.run(storage)
    return storage


@pytest.mark.parametrize(
    "url", ACCEPTED_URLS.values(), ids=ACCEPTED_URLS.keys()
)
def test_supported_scheme_is_accepted(url: str) -> None:
    """Accept a URL whose scheme yt-dlp downloads with Posidon's options.

    Args:
        url: URL with a supported scheme.
    """
    storage = validate(url)

    assert [str(item) for item in storage.urls] == [url]


@pytest.mark.parametrize(
    "url", REJECTED_URLS.values(), ids=REJECTED_URLS.keys()
)
def test_unsupported_scheme_is_skipped(
    url: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Skip an unsupported URL with an error and keep the supported one.

    Args:
        url: Well-formed URL with an unsupported scheme.
        caplog: Fixture holding the captured log records.
    """
    supported = ACCEPTED_URLS["https"]

    storage = validate(url, supported)

    assert [str(item) for item in storage.urls] == [supported]
    assert f"1/2 Invalid or unsupported URL skipped: {url}" in [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.ERROR
    ]


def test_only_unsupported_schemes_exit() -> None:
    """Exit with an error status when no URL has a supported scheme."""
    with pytest.raises(SystemExit) as exit_info:
        validate(*REJECTED_URLS.values())

    assert exit_info.value.code == 1
