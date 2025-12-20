"""Shared constants and utilities for the unhook package."""

# Bluesky record types
BSKY_POST_TYPE = "app.bsky.feed.post"
BSKY_REPOST_TYPE = "app.bsky.feed.repost"
BSKY_REASON_REPOST = "reasonRepost"

# Bluesky facet types
BSKY_LINK_FACET = "app.bsky.richtext.facet#link"

# Bluesky embed types
BSKY_EMBED_RECORD_VIEW_BLOCKED = "app.bsky.embed.record#viewBlocked"
BSKY_EMBED_RECORD_VIEW_NOT_FOUND = "app.bsky.embed.record#viewNotFound"
BSKY_EMBED_RECORD_VIEW_DETACHED = "app.bsky.embed.record#viewDetached"


def get_type_field(obj: dict) -> str:
    """Return the $type or py_type field from an object.

    Bluesky API responses may use either '$type' (JSON format) or 'py_type'
    (atproto model dump format) to indicate the type of a record.

    Args:
        obj: A dictionary that may contain a type field.

    Returns:
        The type string if present, otherwise an empty string.
    """
    if not isinstance(obj, dict):
        return ""
    return obj.get("$type") or obj.get("py_type") or ""
