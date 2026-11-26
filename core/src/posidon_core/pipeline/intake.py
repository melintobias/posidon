"""Validate source URLs before they enter the media pipeline."""

from typing import TYPE_CHECKING

from pydantic import AnyUrl

if TYPE_CHECKING:
    from collections.abc import Collection


def validate_url(url: str, schemes: Collection[str]) -> AnyUrl | None:
    """Parse a source URL whose scheme the caller can retrieve.

    The caller supplies the schemes because they depend on the tool that
    downloads the media. Pydantic normalizes the scheme to lowercase before it
    is compared, so `HTTPS://example.com` matches `https`.

    Args:
        url: Raw source URL supplied by the caller.
        schemes: Lowercase URL schemes to accept, such as `https`.

    Returns:
        The parsed URL, or `None` if Pydantic rejects the input or its scheme
        is not in `schemes`.
    """
    try:
        parsed = AnyUrl(url)
    except ValueError:
        return None
    return parsed if parsed.scheme in schemes else None
