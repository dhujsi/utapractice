#!/usr/bin/env python3
"""Backfill missing song metadata from the first NetEase search result.

This is a maintenance tool for libraries saved before the unified
SongDocument format.  It searches NetEase by the song's title, takes the
first result, and fills in only the fields that are still empty
(``artists`` / ``album`` / ``source``); an existing title or artist is never
overwritten.

The candidate is checked against what the library already knows:

* when the song has artists, the first result must share an artist name,
  otherwise a cover would be linked to the original recording;
* when the song has lyrics, the candidate's NetEase lyrics are compared
  with the local lines (furigana/romaji tags and credit lines ignored).

Anything that fails both checks is reported for review instead of edited.

Run it inside the ``netease-bridge`` container, which has both the NetEase
client helpers and the ``/data/songs`` volume mounted::

    docker exec -i utapractice-netease-bridge python - < scripts/backfill_netease_metadata.py
    docker exec -i utapractice-netease-bridge python - --apply < scripts/backfill_netease_metadata.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "/app")
import netease_bridge as nb  # noqa: E402

SCHEMA_VERSION = 1
SONG_DIR = Path(os.environ.get("SONG_DIR", "/data/songs"))
LYRIC_SCORE_THRESHOLD = 0.35
SEARCH_ATTEMPTS = 3

RUBY_RE = re.compile(r"<(rt|rp)\b[^>]*>.*?</\1>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
LRC_TAG_RE = re.compile(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")
BRACKET_RE = re.compile(r"^\[[^\]]*\]")
SPACE_RE = re.compile(r"\s+")
CREDIT_RE = re.compile(r"^(作词|作曲|编曲|制作人|作詞|OP|ED|主题歌|歌：|読み：)")


def normalize_text(value):
    text = RUBY_RE.sub("", str(value or ""))
    text = TAG_RE.sub("", text)
    return SPACE_RE.sub("", text).strip()


def infer_from_name(stem):
    if " - " in stem:
        artist, title = stem.rsplit(" - ", 1)
        if artist.strip() and title.strip():
            return title.strip(), [part.strip() for part in artist.split("/") if part.strip()]
    return stem.strip(), []


def document_fields(raw, stem):
    if isinstance(raw, dict):
        title = str(raw.get("title") or raw.get("song_name") or "").strip()
        artists = raw.get("artists")
        if not artists:
            artists = raw.get("artist") or []
        if isinstance(artists, str):
            artists = [part.strip() for part in artists.replace("／", "/").split("/") if part.strip()]
        album = str(raw.get("album") or "").strip()
        source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    else:
        title, artists, album, source = "", [], "", {}
    if not title:
        inferred_title, inferred_artists = infer_from_name(stem)
        title = inferred_title
        artists = artists or inferred_artists
    return title, [str(a).strip() for a in artists if str(a).strip()], album, source


def lyrics_items(raw):
    if isinstance(raw, dict) and isinstance(raw.get("lyrics"), list):
        return raw["lyrics"]
    if isinstance(raw, list):
        return raw
    return []


def local_lyric_lines(raw):
    lines = []
    for item in lyrics_items(raw):
        if not isinstance(item, dict):
            continue
        text = normalize_text(item.get("original") or item.get("original_html") or "")
        if text and not CREDIT_RE.match(text):
            lines.append(text)
    return lines


def netease_lyric_lines(lrc_text):
    lines = []
    for raw_line in str(lrc_text or "").splitlines():
        text = LRC_TAG_RE.sub("", raw_line).strip()
        if not text:
            continue
        if text.startswith("{"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            text = "".join(
                str(segment.get("tx") or "")
                for segment in payload.get("c") or []
                if isinstance(segment, dict)
            )
        else:
            text = BRACKET_RE.sub("", text)
        text = normalize_text(text)
        if text and not CREDIT_RE.match(text):
            lines.append(text)
    return lines


def lyric_score(local_lines, candidate_lines, sample=15):
    sample_lines = local_lines[:sample]
    if not sample_lines:
        return 0.0
    candidate = set(candidate_lines)
    return sum(1 for line in sample_lines if line in candidate) / len(sample_lines)


def same_artist(left, right):
    left = normalize_text(left).lower()
    right = normalize_text(right).lower()
    return bool(left) and bool(right) and (left in right or right in left)


def artist_overlap(local_artists, candidate_artists):
    return any(same_artist(a, b) for a in local_artists for b in candidate_artists)


def title_matches(local_title, candidate_title):
    left = normalize_text(local_title).lower()
    right = normalize_text(candidate_title).lower()
    if not left or not right:
        return False
    return left == right or left in right or right in left


def search_first(keyword):
    last_error = None
    for attempt in range(SEARCH_ATTEMPTS):
        try:
            payload = nb.ncm_request(
                "/cloudsearch",
                {"keywords": keyword, "type": "1", "limit": "5", "offset": "0"},
            )
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            songs = result.get("songs") if isinstance(result, dict) else []
            for song in songs or []:
                if isinstance(song, dict):
                    return nb.normalize_search_song(song)
            return None
        except Exception as exc:  # retry transient timeouts
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error


def write_document(path, document):
    original = path.stat()
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    try:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.close()
        os.chmod(handle.name, original.st_mode & 0o7777)
        try:
            os.chown(handle.name, original.st_uid, original.st_gid)
        except PermissionError:
            pass
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def build_document(raw, title, artists, album, source):
    return {
        "schema_version": SCHEMA_VERSION,
        "title": title,
        "artists": artists,
        "album": album,
        "source": source,
        "lyrics": lyrics_items(raw),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the metadata back to disk")
    parser.add_argument("--dir", default=str(SONG_DIR), help="song directory (default: %(default)s)")
    args = parser.parse_args()

    song_dir = Path(args.dir)
    targets = sorted(
        path for path in song_dir.glob("*.json") if not path.name.endswith(".lyrics_source.json")
    )

    filled = reviewed = unchanged = failed = 0
    for path in targets:
        stem = path.name[: -len(".json")]
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[error] {stem}: cannot read ({exc})")
            failed += 1
            continue

        title, artists, album, source = document_fields(raw, stem)
        if not title:
            print(f"[error] {stem}: no title to search with")
            failed += 1
            continue
        if artists and album and source:
            unchanged += 1
            print(f"[skip ] {stem}: already has artists/album/source")
            continue

        try:
            first = search_first(title)
        except Exception as exc:  # network / API failure
            print(f"[error] {stem}: search failed ({exc})")
            failed += 1
            continue
        if not first:
            print(f"[error] {stem}: no NetEase result for {title!r}")
            failed += 1
            continue

        score = None
        local_lines = local_lyric_lines(raw)
        if local_lines:
            try:
                candidate_lrc, _, _ = nb.lyrics_data(first["id"])
                score = lyric_score(local_lines, netease_lyric_lines(candidate_lrc))
            except Exception:
                score = None

        artist_ok = True
        if artists:
            artist_ok = artist_overlap(artists, first["artists"])
        # A strong lyric match can vouch for a result even when the stored
        # artist name uses a different script (e.g. 铃木木乃美 / 鈴木このみ).
        strong_lyrics = score is not None and score >= 0.60
        confident = (artist_ok or strong_lyrics) and (
            title_matches(title, first["title"])
            or (score is not None and score >= LYRIC_SCORE_THRESHOLD)
        )
        action = "fill" if confident else "review"
        score_text = "n/a" if score is None else f"{score:.2f}"
        print(
            f"[{action}] {stem}\n"
            f"         local : title={title!r} artists={artists} album={album!r} source={source}\n"
            f"         netease: title={first['title']!r} artists={first['artists']} "
            f"album={first['album']!r} id={first['id']} lyric_score={score_text} artist_ok={artist_ok}"
        )

        if action != "fill":
            reviewed += 1
            continue

        new_artists = artists or list(first["artists"])
        new_album = album or str(first["album"] or "")
        new_source = source or {"provider": "netease", "song_id": str(first["id"])}
        if new_artists == artists and new_album == album and new_source == source:
            unchanged += 1
            continue

        document = build_document(raw, title or first["title"], new_artists, new_album, new_source)
        if args.apply:
            write_document(path, document)
        filled += 1

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(
        f"\n{mode}: {len(targets)} songs -> fill={filled} review={reviewed} "
        f"unchanged={unchanged} failed={failed}"
    )


if __name__ == "__main__":
    main()
