"""URL helpers with no domain knowledge."""


def normalize_url(url: str) -> str:
    """Comparison form of a URL: trimmed, no trailing slash, lowercase."""
    return url.strip().rstrip("/").lower()
