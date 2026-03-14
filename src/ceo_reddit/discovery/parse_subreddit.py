"""Parse subreddit metadata JSON records."""

import json


def extract_record(line: str) -> tuple | None:
    """Parse a JSON line and return a 14-field tuple, or None if unparseable."""
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    meta = obj.get("_meta", {})

    return (
        obj.get("display_name"),
        obj.get("description"),
        obj.get("public_description"),
        obj.get("title"),
        obj.get("subscribers"),
        obj.get("advertiser_category"),
        obj.get("over18"),
        obj.get("created_utc"),
        obj.get("subreddit_type"),
        obj.get("lang"),
        meta.get("num_comments"),
        meta.get("num_posts"),
        meta.get("earliest_post_at"),
        meta.get("earliest_comment_at"),
    )
