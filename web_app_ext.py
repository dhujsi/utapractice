import json
import os
import unicodedata
import uuid

from flask import jsonify, request

import web_app as core

app = core.app


def _safe_song_name(value):
    return core.sanitize_filename(str(value or "").strip()).strip().strip(".")


def _name_key(value):
    return unicodedata.normalize("NFKC", str(value or "")).casefold()


def _existing_song_name(value):
    safe = _safe_song_name(value)
    if not safe:
        return ""
    songs = core.find_available_songs()
    if safe in songs:
        return safe
    key = _name_key(safe)
    matches = [name for name in songs if _name_key(name) == key]
    return matches[0] if len(matches) == 1 else safe


def _workspace_file_name(path):
    suffix = ".lyrics_source.json"
    return path.name[: -len(suffix)] if path.name.endswith(suffix) else ""


def _workspace_name(value):
    safe = _safe_song_name(value)
    if not safe:
        return ""
    local = _existing_song_name(safe)
    if local != safe or local in core.find_available_songs():
        return local
    key = _name_key(safe)
    matches = [
        _workspace_file_name(path)
        for path in core.SONG_DIR.glob("*.lyrics_source.json")
        if _workspace_file_name(path) and _name_key(_workspace_file_name(path)) == key
    ]
    return matches[0] if len(matches) == 1 else safe


def canonical_workspace_path(name):
    return core.SONG_DIR / f"{_workspace_name(name)}.lyrics_source.json"


# Make all existing workspace readers/generators case-insensitive with respect to an
# already existing local song/workspace, while preserving the actual stored spelling.
core.workspace_path = canonical_workspace_path


def api_save_lyrics_canonical(name):
    payload = request.get_json(force=True)
    if not isinstance(payload, list):
        return jsonify({"error": "Lyrics must be a JSON array"}), 400
    song_name = _existing_song_name(name)
    lyrics_path = core.SONG_DIR / f"{song_name}.json"
    with lyrics_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return jsonify({"ok": True, "song_name": song_name})


def api_save_lyrics_workspace_canonical(name):
    payload = request.get_json(force=True)
    requested = _safe_song_name(payload.get("song_name") or name)
    song_name = _existing_song_name(requested)
    if not song_name:
        return jsonify({"error": "Song name is required"}), 400

    path = canonical_workspace_path(song_name)
    existing = core.read_json_path(path, {})
    original_lrc = str(payload.get("original_lrc", existing.get("original_lrc", "")) or "")
    translation_lrc = str(payload.get("translation_lrc", existing.get("translation_lrc", "")) or "")
    roman_lrc = str(payload.get("roman_lrc", existing.get("roman_lrc", "")) or "")
    workspace = {
        "song_name": song_name,
        "artist": str(payload.get("artist", existing.get("artist", "")) or ""),
        "source": payload.get("source", existing.get("source", {})) or {},
        "original_lrc": original_lrc,
        "translation_lrc": translation_lrc,
        "roman_lrc": roman_lrc,
        "line_rows": core.align_lrc_sources(original_lrc, translation_lrc, roman_lrc),
        "generated_lyrics": payload.get("generated_lyrics") if isinstance(payload.get("generated_lyrics"), list) else [],
        "status": "draft",
        "updated_at": core.now_iso(),
    }
    core.write_json_path(path, workspace)
    return jsonify(workspace)


def api_use_lyrics_preview_canonical(name):
    payload = request.get_json(force=True)
    result = payload.get("result")
    preview = payload.get("preview")
    if not isinstance(result, dict) or not isinstance(preview, dict):
        return jsonify({"error": "Preview result is required"}), 400

    requested = _safe_song_name(payload.get("song_name") or name)
    official = _safe_song_name(result.get("title"))
    local_requested = _existing_song_name(requested)
    local_official = _existing_song_name(official) if official else ""
    songs = core.find_available_songs()
    if local_requested in songs:
        song_name = local_requested
    elif local_official in songs:
        song_name = local_official
    else:
        song_name = official or requested
    if not song_name:
        return jsonify({"error": "Song name is required"}), 400

    artist = str(payload.get("artist") or result.get("artist") or "").strip()
    workspace = core.workspace_from_preview(song_name, artist, result, preview)
    core.write_json_path(canonical_workspace_path(song_name), workspace)
    return jsonify(workspace)


def api_publish_lyrics_workspace_canonical(name):
    song_name = _existing_song_name(name)
    workspace_path = canonical_workspace_path(song_name)
    workspace = core.read_json_path(workspace_path)
    if not workspace:
        return jsonify({"error": "Lyrics workspace not found"}), 404

    workspace_name = _existing_song_name(workspace.get("song_name") or song_name)
    lyrics = workspace.get("generated_lyrics", [])
    if not isinstance(lyrics, list) or not lyrics:
        return jsonify({"error": "No generated lyrics to publish"}), 400
    lyrics = core.normalize_converted_lyrics(lyrics)
    validation_errors = core.validate_generated_workspace_lyrics(lyrics, workspace.get("line_rows", []))
    if validation_errors:
        workspace["status"] = "validation_failed"
        workspace["errors"] = [{"error": message} for message in validation_errors[:20]]
        workspace["updated_at"] = core.now_iso()
        core.write_json_path(workspace_path, workspace)
        return jsonify({"error": f"Generated lyrics failed validation: {validation_errors[0]}"}), 400

    target = core.SONG_DIR / f"{workspace_name}.json"
    core.write_json_path(target, lyrics)
    workspace["song_name"] = workspace_name
    workspace["status"] = "published"
    workspace["updated_at"] = core.now_iso()
    core.write_json_path(canonical_workspace_path(workspace_name), workspace)
    return jsonify(
        {
            "ok": True,
            "song_name": workspace_name,
            "published_count": len(lyrics),
            "lyrics_count": len(lyrics),
        }
    )


# Replace only the affected existing Flask endpoints; the route rules stay unchanged.
app.view_functions["api_save_lyrics"] = api_save_lyrics_canonical
app.view_functions["api_save_lyrics_workspace"] = api_save_lyrics_workspace_canonical
app.view_functions["api_use_lyrics_preview"] = api_use_lyrics_preview_canonical
app.view_functions["api_publish_lyrics_workspace"] = api_publish_lyrics_workspace_canonical


def _song_files(name):
    candidates = []
    for suffix in sorted(core.AUDIO_EXTENSIONS | core.LYRICS_EXTENSIONS):
        path = core.SONG_DIR / f"{name}{suffix}"
        if path.exists():
            candidates.append((path, suffix))
    workspace = core.SONG_DIR / f"{name}.lyrics_source.json"
    if workspace.exists():
        candidates.append((workspace, ".lyrics_source.json"))
    return candidates


def _active_job_for(name):
    key = _name_key(name)
    with core.jobs_lock:
        jobs = core.load_jobs()
    for job in jobs.values():
        if job.get("status") not in {"queued", "running"}:
            continue
        if _name_key(job.get("song_name")) == key:
            return job
    return None


def _rename_job_records(old_name, new_name):
    key = _name_key(old_name)
    with core.jobs_lock:
        jobs = core.load_jobs()
        changed = False
        for job in jobs.values():
            if _name_key(job.get("song_name")) == key:
                job["song_name"] = new_name
                if isinstance(job.get("payload"), dict):
                    job["payload"]["song_name"] = new_name
                if isinstance(job.get("result"), dict) and job["result"].get("song_name"):
                    job["result"]["song_name"] = new_name
                job["updated_at"] = core.now_iso()
                changed = True
        if changed:
            core.save_jobs(jobs)


def _clear_generated_audio_cache(name):
    prefix = f"{core.sanitize_filename(name)}_"
    for path in core.GENERATED_DIR.glob(f"{prefix}*.wav"):
        path.unlink(missing_ok=True)


@app.post("/api/songs/<path:name>/rename")
def api_rename_song(name):
    old_name = _existing_song_name(name)
    songs = core.find_available_songs()
    if old_name not in songs:
        return jsonify({"error": "Song not found"}), 404

    payload = request.get_json(force=True)
    new_name = _safe_song_name(payload.get("new_name"))
    if not new_name:
        return jsonify({"error": "新歌名不能为空"}), 400
    if new_name == old_name:
        return jsonify({"ok": True, "song_name": old_name, "renamed": False})

    active_job = _active_job_for(old_name)
    if active_job:
        return jsonify({"error": "这首歌有正在运行的歌词生成任务，请任务结束后再改名"}), 409

    new_key = _name_key(new_name)
    for existing in songs:
        if existing != old_name and _name_key(existing) == new_key:
            return jsonify({"error": f"歌库里已经有「{existing}」"}), 409

    pairs = []
    for source, suffix in _song_files(old_name):
        target = core.SONG_DIR / f"{new_name}{suffix}"
        if target.exists():
            try:
                same_file = os.path.samefile(source, target)
            except OSError:
                same_file = False
            if not same_file:
                return jsonify({"error": f"目标文件已存在：{target.name}"}), 409
        pairs.append((source, target))

    db = core.load_db()
    if new_name in db and new_name != old_name:
        return jsonify({"error": f"歌名「{new_name}」已有元数据记录，请先处理该条目"}), 409

    staged = []
    try:
        for source, target in pairs:
            if source == target:
                continue
            temp = core.SONG_DIR / f".rename-{uuid.uuid4().hex}-{source.name}"
            os.replace(source, temp)
            staged.append((source, temp, target))
        for source, temp, target in staged:
            os.replace(temp, target)
    except Exception as exc:
        for source, temp, target in reversed(staged):
            try:
                if temp.exists():
                    os.replace(temp, source)
                elif target.exists():
                    os.replace(target, source)
            except OSError:
                pass
        return jsonify({"error": f"重命名文件失败：{exc}"}), 500

    workspace_path = core.SONG_DIR / f"{new_name}.lyrics_source.json"
    workspace = core.read_json_path(workspace_path)
    if isinstance(workspace, dict):
        workspace["song_name"] = new_name
        workspace["updated_at"] = core.now_iso()
        core.write_json_path(workspace_path, workspace)

    if old_name in db:
        db[new_name] = db.pop(old_name)
        core.save_db(db)

    _rename_job_records(old_name, new_name)
    _clear_generated_audio_cache(old_name)

    return jsonify(
        {
            "ok": True,
            "renamed": True,
            "old_name": old_name,
            "song_name": new_name,
            "files": [target.name for _, target in pairs],
        }
    )


if __name__ == "__main__":
    core.mark_interrupted_jobs()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8501")), threaded=True)
