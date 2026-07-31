"""Structured ownership matching for direct-download URL prefixes."""
from __future__ import annotations

from urllib.parse import SplitResult, urlsplit

from .io import InventoryError


def _split_https_url(value: str, *, marker: bool) -> SplitResult:
    """Parse an HTTPS URL and reject authority fields that could spoof ownership."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise InventoryError(f"invalid download URL {'marker' if marker else 'source'}: {value!r}") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise InventoryError(f"download URL {'marker' if marker else 'source'} must use HTTPS: {value!r}")
    if marker and (parsed.username is not None or parsed.password is not None):
        raise InventoryError(f"download URL {'marker' if marker else 'source'} must not contain userinfo: {value!r}")
    if marker and (parsed.query or parsed.fragment):
        raise InventoryError(
            f"download URL {'marker' if marker else 'source'} must not contain a query or fragment: {value!r}"
        )
    if marker and not parsed.path.startswith("/"):
        raise InventoryError(f"download URL marker must contain an absolute path: {value!r}")
    # Accessing port above validates malformed authorities; retain it through the parsed result.
    _ = port
    return parsed


def validate_download_marker(marker: str) -> None:
    """Validate one inventory marker before it participates in ownership checks."""
    _split_https_url(marker, marker=True)


def download_marker_matches(marker: str, url: str) -> bool:
    """Match one HTTPS origin and path prefix using an explicit path boundary."""
    marker_url = _split_https_url(marker, marker=True)
    source_url = _split_https_url(url, marker=False)
    if source_url.username is not None or source_url.password is not None or source_url.query or source_url.fragment:
        return False
    if marker_url.hostname.lower() != source_url.hostname.lower() or marker_url.port != source_url.port:
        return False
    marker_path = marker_url.path.rstrip("/")
    return source_url.path == marker_path or source_url.path.startswith(marker_path + "/")
