"""Canonical song document helpers shared by the Python services.

The filesystem name is only a storage key.  Human-facing metadata belongs in
the document so Web, the NetEase bridge, and the Android client do not have to
guess an artist from a filename.
"""

from __future__ import annotations

from copy import deepcopy


SCHEMA_VERSION = 1


def normalize_artists(value):
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = str(value or "").replace("／", "/").split("/")
    result = []
    for item in values:
        artist = str(item or "").strip()
        if artist and artist not in result:
            result.append(artist)
    return result


def artist_text(document):
    artists = document.get("artists") if isinstance(document, dict) else []
    if not artists and isinstance(document, dict):
        artists = document.get("artist", "")
    return " / ".join(normalize_artists(artists))


def infer_legacy_metadata(storage_name):
    """Best-effort metadata for the old ``artist - title`` filenames."""
    value = str(storage_name or "").strip()
    if " - " not in value:
        return {"title": value, "artists": [], "artist": ""}
    artist, title = value.rsplit(" - ", 1)
    artist = artist.strip()
    title = title.strip()
    if not artist or not title:
        return {"title": value, "artists": [], "artist": ""}
    artists = normalize_artists(artist)
    return {"title": title, "artists": artists, "artist": " / ".join(artists)}


def normalize_document(value, *, title="", artists=None, artist="", album="", source=None, lyrics=None):
    """Return a canonical document while accepting the old bare-array format."""
    if isinstance(value, list):
        document = {"lyrics": deepcopy(value)}
    elif isinstance(value, dict):
        document = deepcopy(value)
    else:
        document = {}

    existing_artists = document.get("artists")
    if existing_artists is None:
        existing_artists = document.get("artist", "")
    normalized_artists = normalize_artists(artists if artists is not None else (existing_artists or artist))
    existing_title = str(document.get("title") or document.get("song_name") or title or "").strip()
    existing_album = str(document.get("album") or album or "").strip()
    existing_source = document.get("source") if isinstance(document.get("source"), dict) else {}
    if source:
        existing_source = deepcopy(source)
    existing_lyrics = document.get("lyrics")
    if not isinstance(existing_lyrics, list):
        existing_lyrics = deepcopy(lyrics) if isinstance(lyrics, list) else []

    # Keep only the canonical top-level fields.  Practice settings remain in
    # song_db.json and are intentionally not duplicated here.
    return {
        "schema_version": SCHEMA_VERSION,
        "title": existing_title,
        "artists": normalized_artists,
        "album": existing_album,
        "source": existing_source,
        "lyrics": existing_lyrics,
    }


def lyrics_from_document(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("lyrics"), list):
        return value["lyrics"]
    return []


def document_metadata(value):
    document = normalize_document(value)
    return {
        "title": document["title"],
        "artists": document["artists"],
        "artist": artist_text(document),
        "album": document["album"],
        "source": document["source"],
        "schema_version": document["schema_version"],
    }
