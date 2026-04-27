import json
import mimetypes
import os
import re
import shutil
from pathlib import Path

import librosa
import soundfile as sf
from flask import Flask, jsonify, render_template, request, send_file
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
SONG_DIR = BASE_DIR / "songs"
ARCHIVE_DIR = BASE_DIR / "songs_archived"
DB_PATH = BASE_DIR / "song_db.json"
GENERATED_DIR = BASE_DIR / "generated"
SETTINGS_PATH = BASE_DIR / "settings.local.json"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a"}
LYRICS_EXTENSIONS = {".json", ".lrc"}

SONG_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(exist_ok=True)
GENERATED_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="web_static", template_folder="templates")


def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "_", filename)


def load_db():
    if DB_PATH.exists():
        with DB_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_db(db_data):
    with DB_PATH.open("w", encoding="utf-8") as f:
        json.dump(db_data, f, indent=2, ensure_ascii=False)


def load_settings():
    if SETTINGS_PATH.exists():
        with SETTINGS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {"base_url": "", "api_key": "", "model": "gpt-4.1-mini"}


def save_settings(settings):
    with SETTINGS_PATH.open("w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def find_available_songs():
    songs = {}
    for path in sorted(SONG_DIR.iterdir(), key=lambda p: p.name.lower()):
        suffix = path.suffix.lower()
        if suffix not in AUDIO_EXTENSIONS | LYRICS_EXTENSIONS:
            continue
        if path.stem.startswith("temp_"):
            continue
        item = songs.setdefault(path.stem, {"name": path.stem, "audio_path": None, "lyrics_path": None})
        if suffix in AUDIO_EXTENSIONS:
            item["audio_path"] = path
        elif suffix == ".json":
            item["lyrics_path"] = path
        elif suffix == ".lrc" and item["lyrics_path"] is None:
            item["lyrics_path"] = path
    return songs


def get_song_or_404(name):
    songs = find_available_songs()
    if name not in songs:
        return None
    return songs[name]


def read_lyrics(path):
    if not path:
        return []
    if path.suffix.lower() == ".lrc":
        return parse_lrc(path.read_text(encoding="utf-8-sig"))
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_lrc(text):
    lines = []
    pattern = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
    for raw_line in text.splitlines():
        matches = list(pattern.finditer(raw_line))
        if not matches:
            continue
        lyric = pattern.sub("", raw_line).strip()
        for match in matches:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            fraction = match.group(3) or "0"
            fraction_seconds = int(fraction) / (1000 if len(fraction) == 3 else 100)
            lines.append(
                {
                    "time": round(minutes * 60 + seconds + fraction_seconds, 3),
                    "original_html": lyric,
                    "translation": "",
                }
            )
    return sorted(lines, key=lambda line: line["time"])


def parse_lrc_timestamps(text):
    rows = []
    pattern = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
    for raw_line in text.splitlines():
        matches = list(pattern.finditer(raw_line))
        lyric = pattern.sub("", raw_line).strip()
        for match in matches:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            fraction = match.group(3) or "0"
            fraction_seconds = int(fraction) / (1000 if len(fraction) == 3 else 100)
            rows.append({"time": round(minutes * 60 + seconds + fraction_seconds, 3), "text": lyric})
    return sorted(rows, key=lambda row: row["time"])


def shifted_audio_path(audio_path, key_shift):
    safe_base = sanitize_filename(audio_path.stem)
    target = GENERATED_DIR / f"{safe_base}_{key_shift:+}.wav"
    if target.exists():
        return target

    y, sr = librosa.load(str(audio_path), sr=None)
    y_shifted = librosa.effects.pitch_shift(y=y, sr=sr, n_steps=float(key_shift))
    sf.write(target, y_shifted, sr)
    return target


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/songs")
def api_songs():
    db = load_db()
    songs = find_available_songs()
    payload = []
    for name in songs:
        info = db.get(name, {})
        song = songs[name]
        payload.append(
            {
                "name": name,
                "has_audio": song["audio_path"] is not None,
                "has_lyrics": song["lyrics_path"] is not None,
                "lyrics_type": song["lyrics_path"].suffix.lower()[1:] if song["lyrics_path"] else None,
                "learned": bool(info.get("learned", False)),
                "range": info.get("range", ""),
                "saved_key": int(info.get("saved_key", 0)),
            }
        )
    return jsonify(payload)


@app.get("/api/songs/<path:name>")
def api_song(name):
    song = get_song_or_404(name)
    if not song:
        return jsonify({"error": "Song not found"}), 404

    db = load_db()
    info = db.setdefault(name, {})
    return jsonify(
            {
                "name": name,
                "has_audio": song["audio_path"] is not None,
                "has_lyrics": song["lyrics_path"] is not None,
                "lyrics_type": song["lyrics_path"].suffix.lower()[1:] if song["lyrics_path"] else None,
                "lyrics": read_lyrics(song["lyrics_path"]),
                "learned": bool(info.get("learned", False)),
                "range": info.get("range", ""),
            "saved_key": int(info.get("saved_key", 0)),
        }
    )


@app.get("/api/songs/<path:name>/audio")
def api_audio(name):
    song = get_song_or_404(name)
    if not song:
        return jsonify({"error": "Song not found"}), 404
    if not song["audio_path"]:
        return jsonify({"error": "No audio for this song"}), 404

    key_shift = int(request.args.get("key", 0))
    audio_path = song["audio_path"] if key_shift == 0 else shifted_audio_path(song["audio_path"], key_shift)
    mime_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    return send_file(audio_path, mimetype=mime_type, conditional=True)


@app.post("/api/songs/<path:name>/meta")
def api_save_meta(name):
    if not get_song_or_404(name):
        return jsonify({"error": "Song not found"}), 404

    payload = request.get_json(force=True)
    db = load_db()
    info = db.setdefault(name, {})

    if "saved_key" in payload:
        info["saved_key"] = int(payload["saved_key"])
    if "range" in payload:
        info["range"] = str(payload["range"])
    if "learned" in payload:
        info["learned"] = bool(payload["learned"])

    save_db(db)
    return jsonify({"ok": True, "info": info})


@app.post("/api/songs/<path:name>/lyrics")
def api_save_lyrics(name):
    payload = request.get_json(force=True)
    if not isinstance(payload, list):
        return jsonify({"error": "Lyrics must be a JSON array"}), 400

    lyrics_path = SONG_DIR / f"{sanitize_filename(name)}.json"
    with lyrics_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return jsonify({"ok": True})


@app.post("/api/songs/<path:name>/delete")
def api_delete_song(name):
    song = get_song_or_404(name)
    if not song:
        return jsonify({"error": "Song not found"}), 404

    for key in ("audio_path", "lyrics_path"):
        source = song[key]
        if not source:
            continue
        target = ARCHIVE_DIR / source.name
        if target.exists():
            target = ARCHIVE_DIR / f"{source.stem}_{os.getpid()}{source.suffix}"
        shutil.move(str(source), str(target))

    db = load_db()
    db.pop(name, None)
    save_db(db)
    return jsonify({"ok": True})


@app.post("/api/upload/audio")
def api_upload_audio():
    files = request.files.getlist("audio")
    saved = []
    for file in files:
        if not file.filename:
            continue
        filename = sanitize_filename(file.filename)
        if Path(filename).suffix.lower() not in AUDIO_EXTENSIONS:
            return jsonify({"error": f"Unsupported audio file: {filename}"}), 400
        target = SONG_DIR / filename
        file.save(target)
        saved.append(filename)
    return jsonify({"ok": True, "saved": saved})


@app.post("/api/upload/lyrics")
def api_upload_lyrics():
    files = request.files.getlist("lyrics")
    saved = []
    for file in files:
        if not file.filename:
            continue
        filename = sanitize_filename(file.filename)
        if Path(filename).suffix.lower() not in LYRICS_EXTENSIONS:
            return jsonify({"error": f"Unsupported lyrics file: {filename}"}), 400
        target = SONG_DIR / filename
        file.save(target)
        saved.append(filename)
    return jsonify({"ok": True, "saved": saved})


@app.get("/api/settings")
def api_get_settings():
    settings = load_settings()
    return jsonify(
        {
            "base_url": settings.get("base_url", ""),
            "model": settings.get("model", "gpt-4.1-mini"),
            "has_api_key": bool(settings.get("api_key")),
        }
    )


@app.post("/api/settings")
def api_save_settings():
    payload = request.get_json(force=True)
    current = load_settings()
    current["base_url"] = str(payload.get("base_url", current.get("base_url", ""))).strip()
    current["model"] = str(payload.get("model", current.get("model", "gpt-4.1-mini"))).strip()
    if "api_key" in payload and payload["api_key"]:
        current["api_key"] = str(payload["api_key"]).strip()
    save_settings(current)
    return jsonify({"ok": True})


@app.post("/api/convert-lyrics")
def api_convert_lyrics():
    payload = request.get_json(force=True)
    song_name = sanitize_filename(str(payload.get("song_name", "")).strip())
    lrc_text = str(payload.get("lrc_text", "")).strip()
    annotated_text = str(payload.get("annotated_text", "")).strip()
    if not song_name:
        return jsonify({"error": "Song name is required"}), 400
    if not lrc_text or not annotated_text:
        return jsonify({"error": "LRC and annotated text are required"}), 400

    settings = load_settings()
    if not settings.get("api_key"):
        return jsonify({"error": "API key is not configured"}), 400

    rows = parse_lrc_timestamps(lrc_text)
    if not rows:
        return jsonify({"error": "No timestamps found in LRC"}), 400

    client = OpenAI(api_key=settings["api_key"], base_url=settings.get("base_url") or None)
    prompt = {
        "task": "Create karaoke lyric JSON. Return JSON only.",
        "schema": [{"time": 12.34, "original_html": "text with <ruby>字<rt>注音</rt></ruby>", "translation": ""}],
        "lrc_rows": rows,
        "annotated_text": annotated_text,
        "rules": [
            "Keep the same number and order of rows as lrc_rows.",
            "Use each lrc_rows time value exactly.",
            "Put ruby/furigana/jyutping markup in original_html.",
            "Put translations in translation only if the LRC line contains translation text; otherwise use an empty string.",
            "Do not wrap the answer in markdown.",
        ],
    }
    completion = client.chat.completions.create(
        model=settings.get("model") or "gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "You are a precise lyrics conversion engine. Output valid JSON only."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        temperature=0,
    )
    content = completion.choices[0].message.content or ""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        converted = json.loads(content)
    except json.JSONDecodeError as exc:
        return jsonify({"error": f"Model returned invalid JSON: {exc}", "raw": content}), 502
    if not isinstance(converted, list):
        return jsonify({"error": "Model response must be a JSON array", "raw": content}), 502

    target = SONG_DIR / f"{song_name}.json"
    with target.open("w", encoding="utf-8") as f:
        json.dump(converted, f, indent=2, ensure_ascii=False)
    return jsonify({"ok": True, "song_name": song_name, "lyrics": converted})


@app.get("/manifest.webmanifest")
def manifest():
    return send_file(BASE_DIR / "web_static" / "manifest.webmanifest", mimetype="application/manifest+json")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8501")), threaded=True)
