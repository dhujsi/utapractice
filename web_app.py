import json
import mimetypes
import os
import re
import shutil
import threading
import uuid
from datetime import datetime
from difflib import SequenceMatcher
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
JOBS_PATH = BASE_DIR / "lyrics_jobs.json"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a"}
LYRICS_EXTENSIONS = {".json", ".lrc"}

SONG_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(exist_ok=True)
GENERATED_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="web_static", template_folder="templates")
jobs_lock = threading.Lock()


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


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_jobs():
    if JOBS_PATH.exists():
        with JOBS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_jobs(jobs):
    with JOBS_PATH.open("w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)


def public_job(job):
    public = dict(job)
    public.pop("payload", None)
    return public


def update_job(job_id, **patch):
    with jobs_lock:
        jobs = load_jobs()
        job = jobs.get(job_id)
        if not job:
            return None
        job.update(patch)
        job["updated_at"] = now_iso()
        jobs[job_id] = job
        save_jobs(jobs)
        return public_job(job)


def append_job_step(job_id, message):
    with jobs_lock:
        jobs = load_jobs()
        job = jobs.get(job_id)
        if not job:
            return
        job.setdefault("steps", []).append({"time": now_iso(), "message": message})
        job["message"] = message
        job["updated_at"] = now_iso()
        jobs[job_id] = job
        save_jobs(jobs)


def is_job_stop_requested(job_id):
    if not job_id:
        return False
    with jobs_lock:
        job = load_jobs().get(job_id)
    return bool(job and job.get("stop_requested"))


def raise_if_stopped(job_id):
    if is_job_stop_requested(job_id):
        raise RuntimeError("TASK_STOPPED")


def mark_interrupted_jobs():
    with jobs_lock:
        jobs = load_jobs()
        changed = False
        for job in jobs.values():
            if job.get("status") in {"queued", "running"}:
                job["status"] = "failed"
                job["message"] = "服务重启，任务已中断，请重新提交"
                job["updated_at"] = now_iso()
                job["finished_at"] = now_iso()
                job.setdefault("steps", []).append({"time": now_iso(), "message": "服务重启，任务已中断，请重新提交"})
                changed = True
        if changed:
            save_jobs(jobs)


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
        lyrics = json.load(f)
    return normalize_converted_lyrics(lyrics) if isinstance(lyrics, list) else lyrics


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


def parse_model_json(content):
    content = (content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


def chat_json(client, model, system_prompt, payload, max_tokens=None):
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": 0,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    completion = client.chat.completions.create(**kwargs)
    return parse_model_json(completion.choices[0].message.content)


def chunk_rows(rows, size=12, context=2):
    chunks = []
    for start in range(0, len(rows), size):
        end = min(start + size, len(rows))
        context_start = max(0, start - context)
        context_end = min(len(rows), end + context)
        chunks.append(
            {
                "start": start,
                "end": end,
                "target_rows": rows[start:end],
                "context_rows": rows[context_start:context_end],
            }
        )
    return chunks


def group_lrc_rows(rows):
    grouped = []
    for row in rows:
        if not grouped or float(grouped[-1]["time"]) != float(row["time"]):
            grouped.append({"time": row["time"], "text": row.get("text", ""), "texts": []})
        text = str(row.get("text", "")).strip()
        if text:
            grouped[-1]["texts"].append(text)
            grouped[-1]["text"] = " / ".join(grouped[-1]["texts"])
    return grouped


def normalize_lyric_text(text):
    text = re.sub(r"<rt>.*?</rt>", "", str(text), flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[[^\]]+\]", "", text)
    text = re.sub(r"[A-Za-z0-9\s　,，.。!！?？:：;；'\"“”‘’()（）\-ー~～·・…、/\\|]", "", text)
    return text.strip()


def lyric_similarity(left, right):
    left_text = normalize_lyric_text(left)
    right_text = normalize_lyric_text(right)
    if not left_text or not right_text:
        return 0
    if left_text in right_text or right_text in left_text:
        return 1
    return SequenceMatcher(None, left_text, right_text).ratio()


def candidate_lines_for_chunk(cleaned_lines, chunk, total_rows):
    matched_indexes = []
    for row in chunk["target_rows"]:
        row_text = row.get("text", "")
        if not normalize_lyric_text(row_text):
            continue
        best_index = None
        best_score = 0
        for line_index, line in enumerate(cleaned_lines):
            score = lyric_similarity(row_text, line)
            if score > best_score:
                best_index = line_index
                best_score = score
        if best_index is not None and best_score >= 0.34:
            matched_indexes.append(best_index)

    source_count = max(len(cleaned_lines), 1)
    if matched_indexes:
        source_start = max(0, min(matched_indexes) - 8)
        source_end = min(source_count, max(matched_indexes) + 20)
        strategy = f"相似匹配 {len(set(matched_indexes))} 个锚点"
    else:
        source_start = max(0, int(chunk["start"] / total_rows * source_count) - 8)
        source_end = min(source_count, int(chunk["end"] / total_rows * source_count) + 20)
        strategy = "未匹配到锚点，按进度取候选"

    return (
        [{"index": line_index, "text": cleaned_lines[line_index]} for line_index in range(source_start, source_end)],
        strategy,
    )


def has_kana(text):
    return bool(re.search(r"[\u3040-\u30ff]", str(text)))


def has_cjk(text):
    return bool(re.search(r"[\u3400-\u9fff]", str(text)))


def split_html_lines(value):
    value = str(value or "").strip()
    if not value:
        return []
    parts = re.split(r"\s*(?:<br\s*/?>|\n)\s*", value, flags=re.I)
    return [part.strip() for part in parts if part.strip()]


def looks_like_translation_line(text):
    if re.search(r"<rt\b", str(text), flags=re.I):
        return False
    text = re.sub(r"<[^>]+>", "", str(text)).strip()
    return bool(text) and has_cjk(text) and not has_kana(text)


def strip_metadata_text(text):
    text = str(text or "").strip()
    text = re.split(r"\s+(?:作詞|作曲|編曲|词：|曲：|编曲：|作词：|作曲：)", text, maxsplit=1)[0].strip()
    text = re.sub(r"\s+-\s+[^<]+$", "", text).strip()
    return text


def normalize_converted_lyrics(items):
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            normalized.append(item)
            continue

        next_item = dict(item)
        original_parts = split_html_lines(next_item.get("original_html", ""))
        translation = str(next_item.get("translation", "") or "").strip()

        same_time_as_previous = (
            normalized
            and next_item.get("time") is not None
            and normalized[-1].get("time") is not None
            and float(next_item.get("time")) == float(normalized[-1].get("time"))
        )

        if same_time_as_previous and not original_parts and translation:
            previous = normalized[-1]
            previous_translation = str(previous.get("translation", "") or "").strip()
            previous["translation"] = " ".join(part for part in [previous_translation, strip_metadata_text(translation)] if part)
            continue

        if original_parts and not translation:
            trailing_translation = []
            while len(original_parts) > 1 and looks_like_translation_line(original_parts[-1]):
                trailing_translation.insert(0, re.sub(r"<[^>]+>", "", original_parts.pop()).strip())
            if trailing_translation:
                next_item["original_html"] = "<br>".join(original_parts)
                next_item["translation"] = " ".join(trailing_translation)

        if next_item.get("original_html"):
            next_item["original_html"] = strip_metadata_text(next_item["original_html"])
        if next_item.get("translation"):
            next_item["translation"] = strip_metadata_text(re.sub(r"<[^>]+>", "", str(next_item["translation"])).strip())

        plain_original = " ".join(re.sub(r"<[^>]+>", "", part).strip() for part in original_parts)
        is_standalone_translation = (
            same_time_as_previous
            and original_parts
            and all(looks_like_translation_line(part) for part in original_parts)
            and not re.search(r"<rt\b", str(next_item.get("original_html", "")), flags=re.I)
        )
        if is_standalone_translation:
            previous = normalized[-1]
            previous_translation = str(previous.get("translation", "") or "").strip()
            merged_translation = " ".join(part for part in [previous_translation, plain_original, next_item.get("translation", "")] if part)
            previous["translation"] = merged_translation
            continue

        normalized.append(next_item)
    return normalized


def perform_lyrics_conversion(payload, report=lambda _message: None, job_id=None):
    song_name = sanitize_filename(str(payload.get("song_name", "")).strip())
    conversion_mode = str(payload.get("conversion_mode", "stable")).strip()
    lrc_text = str(payload.get("lrc_text", "")).strip()
    annotated_text = str(payload.get("annotated_text", "")).strip()
    if not song_name:
        raise ValueError("Song name is required")
    if not lrc_text or not annotated_text:
        raise ValueError("LRC and annotated text are required")

    settings = load_settings()
    if not settings.get("api_key"):
        raise ValueError("API key is not configured")

    rows = parse_lrc_timestamps(lrc_text)
    if not rows:
        raise ValueError("No timestamps found in LRC")
    target_rows = group_lrc_rows(rows)
    raise_if_stopped(job_id)
    report(f"已读取 {len(rows)} 行带时间轴歌词，合并为 {len(target_rows)} 个时间点")

    client = OpenAI(api_key=settings["api_key"], base_url=settings.get("base_url") or None)
    model = settings.get("model") or "gpt-4.1-mini"
    raise_if_stopped(job_id)

    report("正在清理注音文本")
    cleaned = chat_json(
        client,
        model,
        "You clean annotated karaoke source text. Output valid JSON only.",
        {
            "task": "Clean source text before lyric alignment.",
            "input_text": annotated_text,
            "output_schema": {"lines": ["lyric line with ruby/furigana/jyutping if present"]},
            "rules": [
                "Remove unrelated headers, song title lines, artist names, credits, blank lines, romaji-only lines, and commentary.",
                "Keep real lyric lines, translations, and pronunciation annotations.",
                "Do not invent lyrics.",
                "Return JSON only with a lines array.",
            ],
        },
    )
    raise_if_stopped(job_id)
    cleaned_lines = cleaned.get("lines", []) if isinstance(cleaned, dict) else []
    if not isinstance(cleaned_lines, list) or not cleaned_lines:
        cleaned_lines = [line.strip() for line in annotated_text.splitlines() if line.strip()]
    cleaned_lines = [str(line).strip() for line in cleaned_lines if str(line).strip()]
    report(f"已清理注音文本，保留 {len(cleaned_lines)} 行候选内容")

    if conversion_mode != "chunked":
        raise_if_stopped(job_id)
        report("稳定模式：正在整首生成 JSON")
        converted = chat_json(
            client,
            model,
            "You align a full timed lyric file with cleaned annotated source text. Output valid JSON only.",
            {
                "task": "Create full karaoke lyric JSON with ruby annotations.",
                "mode": "stable_full_song_after_cleaning",
                "schema": [{"time": 12.34, "original_html": "text with <ruby>字<rt>reading</rt></ruby>", "translation": ""}],
                "lrc_rows": target_rows,
                "cleaned_annotated_lines": [{"index": i, "text": line} for i, line in enumerate(cleaned_lines)],
                "rules": [
                    "Return exactly one JSON array item for every lrc_rows item; lrc_rows may already merge original and translated LRC lines with the same timestamp.",
                    "Keep lrc_rows order and use each lrc_rows time value exactly.",
                    "The cleaned source line count may not match the LRC row count.",
                    "Use the cleaned source as reference for ruby/furigana/jyutping, not as a row-by-row contract.",
                    "original_html MUST use <ruby>字<rt>reading</rt></ruby> for EVERY character whose pronunciation appears in the cleaned source. Ruby annotations are MANDATORY — never skip or omit them.",
                        "If the cleaned source contains furigana, jyutping, or any reading for a character, that reading MUST appear in the output using ruby tags. Do not discard readings.",
                        "original_html is only the sung lyric in the original language — no translations, no explanations.",
                    "Never put Chinese translation, explanation, or meaning text in original_html.",
                    "Do not use <br> to append translation inside original_html.",
                    "Do not output song title, artist, lyricist, composer, arranger, or credit lines.",
                    "If a translation is available for a lyric row, put it in that same row's translation field.",
                    "Never create a row with empty original_html just to hold translation.",
                    "translation must contain only the Chinese translation as plain text without HTML; use an empty string if unclear.",
                    "Do not include romaji-only text unless it is the actual lyric.",
                    "Do not wrap the answer in markdown.",
                ],
            },
        )
        raise_if_stopped(job_id)
        if not isinstance(converted, list):
            raise ValueError("Stable generation response must be a JSON array")
        if len(converted) != len(target_rows):
            report(f"数量提示：目标时间点 {len(target_rows)} 个，模型返回 {len(converted)} 条；已继续保存，请人工检查断句")
        converted = normalize_converted_lyrics(converted)
        mode = "stable"
        report("稳定模式整首生成完成")
    else:
        converted = []
        chunks = chunk_rows(target_rows, size=12, context=2)
        report(f"实验性分段模式：共 {len(chunks)} 段")
        for index, chunk in enumerate(chunks, start=1):
            raise_if_stopped(job_id)
            candidate_lines, candidate_strategy = candidate_lines_for_chunk(cleaned_lines, chunk, len(target_rows))
            report(f"正在生成第 {index}/{len(chunks)} 段（{candidate_strategy}）")
            chunk_result = chat_json(
                client,
                model,
                "You align timed lyrics with annotated source text. Output valid JSON only.",
                {
                    "task": "Create one chunk of karaoke lyric JSON with ruby annotations.",
                    "chunk_index": index,
                    "total_chunks": len(chunks),
                    "schema": [{"time": 12.34, "original_html": "text with <ruby>字<rt>reading</rt></ruby>", "translation": ""}],
                    "target_rows": chunk["target_rows"],
                    "context_rows": chunk["context_rows"],
                    "candidate_annotated_lines": candidate_lines,
                    "rules": [
                        "Return exactly one JSON array item for every target_rows item; target_rows may already merge original and translated LRC lines with the same timestamp.",
                        "Keep target_rows order and use each target time value exactly.",
                        "Use context_rows only for continuity; do not output context-only rows.",
                        "Prefer candidate_annotated_lines, using their indexes only as source references.",
                        "The source line count may not match the LRC row count because it may include translations or removed romaji.",
                        "original_html MUST use <ruby>字<rt>reading</rt></ruby> for EVERY character whose pronunciation appears in the cleaned source. Ruby annotations are MANDATORY — never skip or omit them.",
                        "If the cleaned source contains furigana, jyutping, or any reading for a character, that reading MUST appear in the output using ruby tags. Do not discard readings.",
                        "original_html is only the sung lyric in the original language — no translations, no explanations.",
                        "Never put Chinese translation, explanation, or meaning text in original_html.",
                        "Do not use <br> to append translation inside original_html.",
                        "Do not output song title, artist, lyricist, composer, arranger, or credit lines.",
                        "If a translation is available for a lyric row, put it in that same row's translation field.",
                        "Never create a row with empty original_html just to hold translation.",
                        "translation must contain only the Chinese translation as plain text without HTML; use an empty string if unclear.",
                        "Do not include romaji-only text unless it is the actual lyric.",
                        "Do not wrap the answer in markdown.",
                    ],
                },
            )
            raise_if_stopped(job_id)
            if not isinstance(chunk_result, list):
                raise ValueError(f"Chunk {index} response must be a JSON array")
            if len(chunk_result) != len(chunk["target_rows"]):
                report(f"数量提示：第 {index}/{len(chunks)} 段目标 {len(chunk['target_rows'])} 个，模型返回 {len(chunk_result)} 条；已继续")
            converted.extend(chunk_result)
            report(f"第 {index}/{len(chunks)} 段完成（{len(chunk_result)} 行，{candidate_strategy}）")
        converted = normalize_converted_lyrics(converted)
        mode = "chunked"

    raise_if_stopped(job_id)
    target = SONG_DIR / f"{song_name}.json"
    with target.open("w", encoding="utf-8") as f:
        json.dump(converted, f, indent=2, ensure_ascii=False)
    report("JSON 已保存并加入歌库")
    return {"ok": True, "song_name": song_name, "lyrics": converted, "mode": mode}


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


@app.post("/api/settings/test")
def api_test_settings():
    settings = load_settings()
    if not settings.get("api_key"):
        return jsonify({"error": "API key is not configured"}), 400

    try:
        client = OpenAI(api_key=settings["api_key"], base_url=settings.get("base_url") or None)
        completion = client.chat.completions.create(
            model=settings.get("model") or "gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "Reply with OK only."},
                {"role": "user", "content": "Connection test. Reply OK."},
            ],
            temperature=0,
            max_tokens=8,
        )
        content = (completion.choices[0].message.content or "").strip()
        return jsonify({"ok": True, "message": content or "OK"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


def run_convert_job(job_id):
    started_at = datetime.now().astimezone()
    update_job(job_id, status="running", message="任务已开始", started_at=started_at.isoformat(timespec="seconds"))
    try:
        with jobs_lock:
            job = load_jobs().get(job_id, {})
            payload = job.get("payload", {})

        result = perform_lyrics_conversion(payload, report=lambda message: append_job_step(job_id, message), job_id=job_id)
        duration_seconds = round((datetime.now().astimezone() - started_at).total_seconds(), 1)
        update_job(
            job_id,
            status="done",
            progress=100,
            message=f"生成完成，用时 {duration_seconds} 秒",
            result={"song_name": result["song_name"], "mode": result["mode"]},
            duration_seconds=duration_seconds,
            finished_at=now_iso(),
        )
    except RuntimeError as exc:
        duration_seconds = round((datetime.now().astimezone() - started_at).total_seconds(), 1)
        if str(exc) != "TASK_STOPPED":
            append_job_step(job_id, f"任务停止：{exc}")
        update_job(
            job_id,
            status="stopped",
            message="任务已停止",
            duration_seconds=duration_seconds,
            finished_at=now_iso(),
            stop_requested=False,
        )
    except Exception as exc:
        duration_seconds = round((datetime.now().astimezone() - started_at).total_seconds(), 1)
        append_job_step(job_id, f"生成失败：{exc}")
        update_job(
            job_id,
            status="failed",
            message=f"生成失败：{exc}",
            error=str(exc),
            duration_seconds=duration_seconds,
            finished_at=now_iso(),
        )


@app.get("/api/convert-jobs")
def api_convert_jobs():
    with jobs_lock:
        jobs = load_jobs()
        items = [public_job(job) for job in jobs.values()]
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return jsonify(items)


@app.post("/api/convert-jobs")
def api_create_convert_job():
    payload = request.get_json(force=True)
    song_name = sanitize_filename(str(payload.get("song_name", "")).strip())
    if not song_name:
        return jsonify({"error": "Song name is required"}), 400
    if not str(payload.get("lrc_text", "")).strip() or not str(payload.get("annotated_text", "")).strip():
        return jsonify({"error": "LRC and annotated text are required"}), 400
    if not load_settings().get("api_key"):
        return jsonify({"error": "API key is not configured"}), 400

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "type": "convert_lyrics",
        "song_name": song_name,
        "mode": str(payload.get("conversion_mode", "stable")).strip() or "stable",
        "status": "queued",
        "message": "任务已加入后台队列",
        "steps": [{"time": now_iso(), "message": "任务已加入后台队列"}],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "payload": payload,
    }
    with jobs_lock:
        jobs = load_jobs()
        jobs[job_id] = job
        save_jobs(jobs)

    thread = threading.Thread(target=run_convert_job, args=(job_id,), daemon=True)
    thread.start()
    return jsonify(public_job(job)), 202


@app.get("/api/convert-jobs/<job_id>")
def api_convert_job(job_id):
    with jobs_lock:
        job = load_jobs().get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(public_job(job))


@app.post("/api/convert-jobs/<job_id>/stop")
def api_stop_convert_job(job_id):
    with jobs_lock:
        jobs = load_jobs()
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job.get("status") not in {"queued", "running"}:
            return jsonify({"error": "Only queued or running jobs can be stopped"}), 400
        job["stop_requested"] = True
        job["message"] = "已请求停止，当前 AI 请求结束后会停止"
        job["updated_at"] = now_iso()
        job.setdefault("steps", []).append({"time": now_iso(), "message": "已请求停止"})
        jobs[job_id] = job
        save_jobs(jobs)
    return jsonify(public_job(job))


@app.delete("/api/convert-jobs/<job_id>")
def api_delete_convert_job(job_id):
    with jobs_lock:
        jobs = load_jobs()
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job.get("status") not in {"done", "failed", "stopped"}:
            return jsonify({"error": "Only finished or stopped jobs can be deleted"}), 400
        del jobs[job_id]
        save_jobs(jobs)
    return jsonify({"ok": True})


@app.post("/api/convert-lyrics-old")
def api_convert_lyrics():
    payload = request.get_json(force=True)
    song_name = sanitize_filename(str(payload.get("song_name", "")).strip())
    conversion_mode = str(payload.get("conversion_mode", "stable")).strip()
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


@app.post("/api/convert-lyrics")
def api_convert_lyrics_chunked():
    payload = request.get_json(force=True)
    song_name = sanitize_filename(str(payload.get("song_name", "")).strip())
    conversion_mode = str(payload.get("conversion_mode", "stable")).strip()
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
    target_rows = group_lrc_rows(rows)

    client = OpenAI(api_key=settings["api_key"], base_url=settings.get("base_url") or None)
    model = settings.get("model") or "gpt-4.1-mini"
    steps = [f"已读取 {len(rows)} 行带时间轴歌词，合并为 {len(target_rows)} 个时间点"]

    try:
        cleaned = chat_json(
            client,
            model,
            "You clean annotated karaoke source text. Output valid JSON only.",
            {
                "task": "Clean source text before lyric alignment.",
                "input_text": annotated_text,
                "output_schema": {"lines": ["lyric line with ruby/furigana/jyutping if present"]},
                "rules": [
                    "Remove unrelated headers, song title lines, artist names, credits, blank lines, romaji-only lines, and commentary.",
                    "Keep real lyric lines, translations, and pronunciation annotations.",
                    "Do not invent lyrics.",
                    "Return JSON only with a lines array.",
                ],
            },
        )
    except json.JSONDecodeError as exc:
        return jsonify({"error": f"Clean step returned invalid JSON: {exc}"}), 502
    except Exception as exc:
        return jsonify({"error": f"Clean step failed: {exc}"}), 502

    cleaned_lines = cleaned.get("lines", []) if isinstance(cleaned, dict) else []
    if not isinstance(cleaned_lines, list) or not cleaned_lines:
        cleaned_lines = [line.strip() for line in annotated_text.splitlines() if line.strip()]
    cleaned_lines = [str(line).strip() for line in cleaned_lines if str(line).strip()]
    steps.append(f"已清理注音文本，保留 {len(cleaned_lines)} 行候选内容")

    converted = []
    if conversion_mode != "chunked":
        try:
            converted = chat_json(
                client,
                model,
                "You align a full timed lyric file with cleaned annotated source text. Output valid JSON only.",
                {
                    "task": "Create full karaoke lyric JSON with ruby annotations.",
                    "mode": "stable_full_song_after_cleaning",
                    "schema": [
                        {
                            "time": 12.34,
                            "original_html": "text with <ruby>字<rt>reading</rt></ruby>",
                            "translation": "",
                        }
                    ],
                    "lrc_rows": target_rows,
                    "cleaned_annotated_lines": [
                        {"index": line_index, "text": line}
                        for line_index, line in enumerate(cleaned_lines)
                    ],
                    "rules": [
                        "Return exactly one JSON array item for every lrc_rows item; lrc_rows may already merge original and translated LRC lines with the same timestamp.",
                        "Keep lrc_rows order and use each lrc_rows time value exactly.",
                        "The cleaned source line count may not match the LRC row count.",
                        "Use the cleaned source as reference for ruby/furigana/jyutping, not as a row-by-row contract.",
                        "original_html MUST use <ruby>字<rt>reading</rt></ruby> for EVERY character whose pronunciation appears in the cleaned source. Ruby annotations are MANDATORY — never skip or omit them.",
                        "If the cleaned source contains furigana, jyutping, or any reading for a character, that reading MUST appear in the output using ruby tags. Do not discard readings.",
                        "original_html is only the sung lyric in the original language — no translations, no explanations.",
                        "Never put Chinese translation, explanation, or meaning text in original_html.",
                        "Do not use <br> to append translation inside original_html.",
                        "Do not output song title, artist, lyricist, composer, arranger, or credit lines.",
                        "If a translation is available for a lyric row, put it in that same row's translation field.",
                        "Never create a row with empty original_html just to hold translation.",
                        "translation must contain only the Chinese translation as plain text without HTML; use an empty string if unclear.",
                        "Do not include romaji-only text unless it is the actual lyric.",
                        "Do not wrap the answer in markdown.",
                    ],
                },
            )
        except json.JSONDecodeError as exc:
            return jsonify({"error": f"Stable generation returned invalid JSON: {exc}"}), 502
        except Exception as exc:
            return jsonify({"error": f"Stable generation failed: {exc}"}), 502

        if not isinstance(converted, list):
            return jsonify({"error": "Stable generation response must be a JSON array"}), 502
        if len(converted) != len(target_rows):
            steps.append(f"数量提示：目标时间点 {len(target_rows)} 个，模型返回 {len(converted)} 条；已继续保存，请人工检查断句")
        converted = normalize_converted_lyrics(converted)

        target = SONG_DIR / f"{song_name}.json"
        with target.open("w", encoding="utf-8") as f:
            json.dump(converted, f, indent=2, ensure_ascii=False)
        steps.append("稳定模式整首生成完成")
        steps.append("JSON 已保存并加入歌库")
        return jsonify({"ok": True, "song_name": song_name, "lyrics": converted, "steps": steps, "mode": "stable"})

    chunks = chunk_rows(target_rows, size=12, context=2)
    for index, chunk in enumerate(chunks, start=1):
        candidate_lines, candidate_strategy = candidate_lines_for_chunk(cleaned_lines, chunk, len(target_rows))
        try:
            chunk_result = chat_json(
                client,
                model,
                "You align timed lyrics with annotated source text. Output valid JSON only.",
                {
                    "task": "Create one chunk of karaoke lyric JSON with ruby annotations.",
                    "chunk_index": index,
                    "total_chunks": len(chunks),
                    "schema": [
                        {
                            "time": 12.34,
                            "original_html": "text with <ruby>字<rt>reading</rt></ruby>",
                            "translation": "",
                        }
                    ],
                    "target_rows": chunk["target_rows"],
                    "context_rows": chunk["context_rows"],
                    "candidate_annotated_lines": candidate_lines,
                    "rules": [
                        "Return exactly one JSON array item for every target_rows item; target_rows may already merge original and translated LRC lines with the same timestamp.",
                        "Keep target_rows order and use each target time value exactly.",
                        "Use context_rows only for continuity; do not output context-only rows.",
                        "Prefer candidate_annotated_lines, using their indexes only as source references.",
                        "The source line count may not match the LRC row count because it may include translations or removed romaji.",
                        "original_html MUST use <ruby>字<rt>reading</rt></ruby> for EVERY character whose pronunciation appears in the cleaned source. Ruby annotations are MANDATORY — never skip or omit them.",
                        "If the cleaned source contains furigana, jyutping, or any reading for a character, that reading MUST appear in the output using ruby tags. Do not discard readings.",
                        "original_html is only the sung lyric in the original language — no translations, no explanations.",
                        "Never put Chinese translation, explanation, or meaning text in original_html.",
                        "Do not use <br> to append translation inside original_html.",
                        "Do not output song title, artist, lyricist, composer, arranger, or credit lines.",
                        "If a translation is available for a lyric row, put it in that same row's translation field.",
                        "Never create a row with empty original_html just to hold translation.",
                        "translation must contain only the Chinese translation as plain text without HTML; use an empty string if unclear.",
                        "Do not include romaji-only text unless it is the actual lyric.",
                        "Do not wrap the answer in markdown.",
                    ],
                },
            )
        except json.JSONDecodeError as exc:
            return jsonify({"error": f"Chunk {index} returned invalid JSON: {exc}"}), 502
        except Exception as exc:
            return jsonify({"error": f"Chunk {index} failed: {exc}"}), 502

        if not isinstance(chunk_result, list):
            return jsonify({"error": f"Chunk {index} response must be a JSON array"}), 502
        if len(chunk_result) != len(chunk["target_rows"]):
            steps.append(f"数量提示：第 {index}/{len(chunks)} 段目标 {len(chunk['target_rows'])} 个，模型返回 {len(chunk_result)} 条；已继续")
        converted.extend(chunk_result)
        steps.append(f"第 {index}/{len(chunks)} 段完成（{len(chunk_result)} 行，{candidate_strategy}）")

    converted = normalize_converted_lyrics(converted)

    target = SONG_DIR / f"{song_name}.json"
    with target.open("w", encoding="utf-8") as f:
        json.dump(converted, f, indent=2, ensure_ascii=False)
    steps.append("JSON 已保存并加入歌库")
    return jsonify({"ok": True, "song_name": song_name, "lyrics": converted, "steps": steps, "mode": "chunked"})


@app.get("/manifest.webmanifest")
def manifest():
    return send_file(BASE_DIR / "web_static" / "manifest.webmanifest", mimetype="application/manifest+json")


if __name__ == "__main__":
    mark_interrupted_jobs()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8501")), threaded=True)
