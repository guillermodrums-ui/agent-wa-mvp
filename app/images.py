"""Image registry: filesystem + JSON for product images."""

import json
import os
import re
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path


IMAGES_DIR = Path("data/images")
REGISTRY_PATH = IMAGES_DIR / "registry.json"


def _slugify(text: str) -> str:
    """Normalize text to a filesystem-safe slug."""
    # Decompose unicode, remove accents
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")


def _load_registry() -> list[dict]:
    if not REGISTRY_PATH.exists():
        return []
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_registry(entries: list[dict]):
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def add_image(
    file_bytes: bytes,
    original_filename: str,
    title: str,
    description: str = "",
    tags: str = "",
) -> dict:
    """Save image file and add entry to registry. Returns the new entry."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    image_id = str(uuid.uuid4())[:8]
    slug = _slugify(title)
    ext = Path(original_filename).suffix.lower() or ".jpg"
    filename = f"{slug}-{image_id}{ext}"

    filepath = IMAGES_DIR / filename
    filepath.write_bytes(file_bytes)

    entry = {
        "id": image_id,
        "title": title,
        "slug": slug,
        "description": description,
        "tags": tags,
        "filename": filename,
        "created_at": datetime.now().isoformat(),
    }

    registry = _load_registry()
    registry.append(entry)
    _save_registry(registry)

    return entry


def list_images() -> list[dict]:
    return _load_registry()


def get_image_by_title(title: str) -> dict | None:
    """Fuzzy match by slug: exact match first, then partial/contains."""
    registry = _load_registry()
    if not registry:
        return None

    query_slug = _slugify(title)
    if not query_slug:
        return None

    # Exact slug match
    for entry in registry:
        if entry["slug"] == query_slug:
            return entry

    # Partial match: query contained in slug or slug contained in query
    for entry in registry:
        if query_slug in entry["slug"] or entry["slug"] in query_slug:
            return entry

    # Word overlap: at least one word matches
    query_words = set(query_slug.split("-"))
    best = None
    best_overlap = 0
    for entry in registry:
        entry_words = set(entry["slug"].split("-"))
        overlap = len(query_words & entry_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best = entry

    return best if best_overlap > 0 else None


def get_image_url(entry: dict) -> str:
    return f"/images/{entry['filename']}"


def delete_image(image_id: str) -> dict | None:
    """Delete image file and registry entry. Returns deleted entry or None."""
    registry = _load_registry()
    entry = next((e for e in registry if e["id"] == image_id), None)
    if not entry:
        return None

    # Remove file
    filepath = IMAGES_DIR / entry["filename"]
    if filepath.exists():
        filepath.unlink()

    # Remove from registry
    registry = [e for e in registry if e["id"] != image_id]
    _save_registry(registry)

    return entry
