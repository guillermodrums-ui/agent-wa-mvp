"""Post-processor for agent replies: parse [IMAGEN: ...] markers and resolve URLs."""

import re

from app.images import get_image_by_title, get_image_url

IMAGE_MARKER_RE = re.compile(r"\[IMAGEN:\s*([^\]]+)\]", re.IGNORECASE)


def process_reply(raw_reply: str) -> dict:
    """Parse image markers from agent reply and resolve to URLs.

    Returns:
        {
            "text": "clean text without markers",
            "images": [{"title": ..., "url": "/images/...", "filename": ...}],
            "unresolved_images": ["title that didn't match"],
            "raw_reply": "original text with markers",
        }
    """
    matches = IMAGE_MARKER_RE.findall(raw_reply)

    if not matches:
        return {
            "text": raw_reply,
            "images": [],
            "unresolved_images": [],
            "raw_reply": raw_reply,
        }

    images = []
    unresolved = []
    seen_ids = set()

    for title in matches:
        title = title.strip()
        entry = get_image_by_title(title)
        if entry and entry["id"] not in seen_ids:
            seen_ids.add(entry["id"])
            images.append({
                "title": entry["title"],
                "url": get_image_url(entry),
                "filename": entry["filename"],
            })
        elif not entry:
            unresolved.append(title)

    # Remove all markers from text
    clean_text = IMAGE_MARKER_RE.sub("", raw_reply).strip()
    # Collapse multiple spaces/newlines left by removal
    clean_text = re.sub(r" {2,}", " ", clean_text)
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)

    return {
        "text": clean_text,
        "images": images,
        "unresolved_images": unresolved,
        "raw_reply": raw_reply,
    }
