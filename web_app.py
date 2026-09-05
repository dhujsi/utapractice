import json
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
import uuid
import base64
import html
from html.parser import HTMLParser
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import librosa
import soundfile as sf
from flask import Flask, jsonify, make_response, render_template, request, send_file
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
SONG_DIR = BASE_DIR / "songs"
ARCHIVE_DIR = BASE_DIR / "songs_archived"
DB_PATH = BASE_DIR / "song_db.json"
GENERATED_DIR = BASE_DIR / "generated"
SETTINGS_PATH = BASE_DIR / "settings.local.json"
JOBS_PATH = BASE_DIR / "lyrics_jobs.json"
DEFAULT_MODEL = "deepseek-v4-pro"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a"}
LYRICS_EXTENSIONS = {".json", ".lrc"}
SEARCH_HTTP_TIMEOUT_SECONDS = 6
SEARCH_PROVIDER_TIMEOUT_SECONDS = 6
SEARCH_AGGREGATE_TIMEOUT_SECONDS = 7

# 网易云桥接服务的同源代理：前端请求 /api/netease/* 时由 Flask 转发到 bridge，
# 规避跨源 fetch、HTTPS 明文端口和 WebView CORS 限制（方案 C）。
NETEASE_BRIDGE_BASE = os.environ.get("NETEASE_BRIDGE_BASE", "http://127.0.0.1:8503").rstrip("/")
NETEASE_PROXY_TIMEOUT = float(os.environ.get("NETEASE_PROXY_TIMEOUT", "130"))

SONG_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(exist_ok=True)
GENERATED_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="web_static", template_folder="templates")


def add_api_cors_headers(response):
    if request.path.startswith("/api/"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response


@app.before_request
def handle_api_preflight():
    if request.method == "OPTIONS" and request.path.startswith("/api/"):
        return add_api_cors_headers(make_response("", 204))
    return None


@app.after_request
def apply_api_cors(response):
    return add_api_cors_headers(response)


def _netease_bridge_forward(subpath):
    """把 /api/netease/<subpath> 原样转发给 netease-bridge，返回同源响应。

    前端因此只需请求同源相对路径，不再受 CORS / mixed-content / 8503 端口不可达影响。
    """
    target = f"{NETEASE_BRIDGE_BASE}/api/netease/{subpath}"
    if request.query_string:
        target = f"{target}?{request.query_string.decode('utf-8')}"
    body = request.get_data()
    headers = {
        "User-Agent": "UtaPracticeProxy/1.0",
        "Accept": "application/json",
    }
    if body:
        headers["Content-Type"] = request.content_type or "application/json"
    req = Request(target, data=body or None, headers=headers, method=request.method)
    try:
        with urlopen(req, timeout=NETEASE_PROXY_TIMEOUT) as resp:
            raw = resp.read()
            status = resp.status
            ctype = resp.headers.get("Content-Type", "application/json")
    except HTTPError as exc:
        raw = exc.read()
        status = exc.code
        ctype = (exc.headers or {}).get("Content-Type", "application/json")
    except (URLError, OSError) as exc:
        return make_response(
            json.dumps({"error": f"网易云桥接服务不可用：{exc}"}, ensure_ascii=False),
            502,
        )
    response = make_response(raw)
    response.status_code = status
    response.headers["Content-Type"] = ctype or "application/json"
    return response


@app.route("/api/netease", methods=["GET", "POST", "DELETE", "OPTIONS"])
def netease_bridge_root():
    return _netease_bridge_forward("")


@app.route("/api/netease/<path:subpath>", methods=["GET", "POST", "DELETE", "OPTIONS"])
def netease_bridge_proxy(subpath):
    return _netease_bridge_forward(subpath or "")
jobs_lock = threading.Lock()
audio_probe_cache = {}


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
        with SETTINGS_PATH.open("r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {"base_url": "", "api_key": "", "model": DEFAULT_MODEL}


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
        if path.name.endswith(".lyrics_source.json"):
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
    raw = str(content or "").strip()
    if not raw:
        raise ValueError("模型返回空内容，不是 JSON")

    candidates = [raw]
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, flags=re.I)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())

    starts = [index for index in [raw.find("{"), raw.find("[")] if index >= 0]
    ends = [index for index in [raw.rfind("}"), raw.rfind("]")] if index >= 0]
    if starts and ends and min(starts) < max(ends):
        candidates.append(raw[min(starts) : max(ends) + 1].strip())

    last_error = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc

    excerpt = re.sub(r"\s+", " ", raw)[:360]
    raise ValueError(f"模型返回的不是合法 JSON：{last_error}；返回片段：{excerpt}")


class FatalJobError(ValueError):
    """不可恢复的任务错误（余额不足、密钥无效等），应立刻中止整批生成而不是逐段重试。"""


def api_error_status(exc):
    """尽量从 OpenAI 异常里取出 HTTP 状态码。"""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    message = str(exc)
    match = re.search(r"Error code: (\d+)", message)
    if match:
        return int(match.group(1))
    match = re.search(r"HTTP (\d{3})", message, flags=re.I)
    if match:
        return int(match.group(1))
    return None


def is_fatal_api_error(exc):
    """余额不足 / 密钥无效这类错误重试多少次都一样，必须直接中止并给出明确提示。"""
    status = api_error_status(exc)
    if status in (401, 402, 403):
        return True
    message = str(exc).lower()
    return any(
        hint in message
        for hint in ("insufficient balance", "invalid api key", "authentication", "invalid_request_error", "api key")
    )


def friendly_api_error(exc):
    message = str(exc)
    status = api_error_status(exc)
    lowered = message.lower()
    if status == 402 or "insufficient balance" in lowered or "insufficient_balance" in lowered:
        return "DeepSeek API 余额不足（Insufficient Balance），请充值后再重试"
    if status == 401 or "invalid api key" in lowered or "authentication" in lowered:
        return "DeepSeek API Key 无效或未授权（401），请在「生成歌词 → 接口设置」检查"
    if status == 403:
        return "DeepSeek API 拒绝了请求（403），请检查密钥权限或网络"
    if status == 429:
        return "DeepSeek API 触发限流（429），请稍后重试或降低并发"
    return message


def is_empty_content_error(exc):
    return "空内容" in str(exc)


def is_truncated_error(exc):
    message = str(exc)
    return "截断" in message or "finish_reason=length" in message


def chat_json(client, model, system_prompt, payload, max_tokens=None, json_object=False):
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
    if json_object:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        completion = client.chat.completions.create(**kwargs)
    except Exception as exc:
        message = str(exc).lower()
        unsupported_json_mode = any(term in message for term in ["response_format", "json_object", "unsupported", "invalid parameter"])
        if not json_object or not unsupported_json_mode:
            raise
        kwargs.pop("response_format", None)
        completion = client.chat.completions.create(**kwargs)
    choice = completion.choices[0]
    content = choice.message.content
    if not (content or "").strip():
        # 区分「真空回」与「推理型模型把 max_tokens 预算耗尽导致的空回」：
        # 后者 finish_reason=length，重试时应扩大预算而不是盲目原样重试。
        if getattr(choice, "finish_reason", None) == "length":
            raise ValueError("模型输出被 max_tokens 截断（finish_reason=length），返回内容为空")
        raise ValueError("模型返回空内容，不是 JSON")
    return parse_model_json(content)


RUBY_GENERATION_SYSTEM_PROMPT = """You are a highly precise karaoke lyric alignment and ruby annotation engine.
Your sole task is to wrap EVERY Kanji (or Chinese Hanzi) in `<ruby>` tags and output strictly in JSON format.

### CORE CONSTRAINTS
1. JSON ONLY: Output a single valid JSON object/array matching the requested schema. Do not include markdown code blocks, explanations, or preamble.
2. STRICT TEXT PRESERVATION: After removing `<ruby>`, `<rt>`, and `<rp>` tags from `original_html`, the remaining visible text MUST perfectly match the input `original` text character by character.
   - NEVER normalize, modernize, translate, or rewrite text. For example, keep 未來 as 未來, do not change it to 未来.
   - Preserve all spaces and punctuation exactly.

### MANDATORY RUBY COVERAGE
1. EVERY Kanji character in a Japanese lyric line MUST be wrapped as `<ruby>Kanji<rt>reading</rt></ruby>`. Output with any unannotated Kanji will be REJECTED.
   - Required: `<ruby>数十億<rt>すうじゅうおく</rt></ruby>もの　<ruby>鼓動<rt>こどう</rt></ruby>の<ruby>数<rt>かず</rt></ruby>さえ`
   - REJECTED: `数十億もの　鼓動の数さえ` (plain text, no ruby)
2. For Chinese songs, annotate every Hanzi with pinyin in `<rt>`.
3. Kana (hiragana/katakana), English, and romaji need NO ruby.

### READING SOURCE
1. Use the `roman_or_pronunciation` field when it provides the reading.
2. When no reading is provided, DERIVE the correct reading yourself from context (you are an expert in Japanese readings). Never skip ruby just because no reading was supplied.
3. If genuinely unsure, still provide your best reading rather than leaving the Kanji unannotated.

### RUBY ANNOTATION RULES
1. Structure: Use the format `<ruby>Base<rt>Reading</rt></ruby>`. Never append readings inline. For example, output `<ruby>君<rt>きみ</rt></ruby>が`, NEVER `君きみが`.
2. Okurigana for Japanese: The `<rt>` tag must only contain the reading for the Kanji. The okurigana remains outside.
   - Correct: `<ruby>渇<rt>かわ</rt></ruby>いた`
   - Incorrect: `<ruby>渇<rt>か</rt></ruby>いた` or `<ruby>渇い<rt>かわい</rt></ruby>た`

### DATA HANDLING
1. Translations: Put translations ONLY in the `translation` field. NEVER put translations, meanings, or `<br>` tags inside `original_html`.
2. Metadata: Do not invent lyrics, timestamps, or copy global metadata such as artist/title/credits into item rows.
3. Consistency: Keep the exact same number of items and order as the input target rows."""


CLEAN_SOURCE_SYSTEM_PROMPT = """You are a precise data extraction assistant. Your task is to clean raw karaoke source text.

### RULES
1. Output strictly in JSON format without markdown wrappers.
2. KEEP: Actual lyric lines, their translations, and pronunciation annotations such as ruby, furigana, or jyutping.
3. REMOVE: Song titles, artist names, metadata credits, blank lines, purely romaji-only lines unless they are the actual sung lyric, and commentary.
4. Do not invent or modify the lyrics."""


def unwrap_items_result(result, label):
    if isinstance(result, dict) and isinstance(result.get("items"), list):
        return result["items"]
    if isinstance(result, list):
        return result
    raise ValueError(f"{label} response must be a JSON array or an object with an items array")


def ruby_rows_for_model(rows, include_time=False):
    model_rows = []
    for position, row in enumerate(rows, start=1):
        item = {
            "row_number": position,
            "original": str(row.get("original", row.get("text", "")) or ""),
            "translation": str(row.get("translation", "") or ""),
            "roman_or_pronunciation": str(row.get("roman", row.get("roman_or_pronunciation", "")) or ""),
        }
        if include_time:
            item["time"] = row.get("time", 0)
        if row.get("index") is not None:
            item["source_index"] = row.get("index")
        model_rows.append(item)
    return model_rows


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


def workspace_path(name):
    return SONG_DIR / f"{sanitize_filename(name)}.lyrics_source.json"


def read_json_path(path, default=None):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json_path(path, payload):
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def archive_song_file(source):
    if not source:
        return None
    target = ARCHIVE_DIR / source.name
    if target.exists():
        target = ARCHIVE_DIR / f"{source.stem}_{int(time.time())}{source.suffix}"
    shutil.move(str(source), str(target))
    return target


def ffprobe_audio_stream(audio_path):
    try:
        stat = audio_path.stat()
    except OSError as exc:
        return {"error": f"音频文件不可读：{exc}"}
    cache_key = (str(audio_path), stat.st_size, stat.st_mtime_ns)
    cached = audio_probe_cache.get(cache_key)
    if cached is not None:
        return cached
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,codec_tag_string,channels",
        "-of",
        "json",
        str(audio_path),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=8)
        data = json.loads(completed.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
    except FileNotFoundError:
        stream = {"error": "服务器缺少 ffprobe，无法检查音频编码"}
    except Exception as exc:
        stream = {"error": f"音频编码检查失败：{exc}"}
    audio_probe_cache[cache_key] = stream
    return stream


def audio_compatibility(audio_path):
    if not audio_path:
        return {"playable": False, "error": ""}
    suffix = audio_path.suffix.lower()
    if suffix in {".mp3", ".wav", ".flac"}:
        return {"playable": True, "error": ""}
    if suffix != ".m4a":
        return {"playable": True, "error": ""}

    stream = ffprobe_audio_stream(audio_path)
    if stream.get("error"):
        return {"playable": False, "error": stream["error"]}
    codec_name = str(stream.get("codec_name") or "").lower()
    codec_tag = str(stream.get("codec_tag_string") or "").lower()
    channels = int(stream.get("channels") or 0)
    if codec_name == "aac" and 0 < channels <= 2:
        return {"playable": True, "error": ""}
    codec_label = codec_name or codec_tag or "未知"
    if codec_tag == "av3a":
        codec_label = "av3a"
    return {"playable": False, "error": f"音频格式不支持：{codec_label}，请替换音频"}


def audio_mime_type(audio_path):
    explicit = {
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
    }
    return explicit.get(audio_path.suffix.lower()) or mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"


def audio_metadata(audio_path):
    if not audio_path:
        return {"audio_size": 0, "audio_mtime": 0, "audio_mime": ""}
    stat = audio_path.stat()
    return {"audio_size": stat.st_size, "audio_mtime": int(stat.st_mtime), "audio_mime": audio_mime_type(audio_path)}


def fetch_json(url, headers=None, timeout=SEARCH_HTTP_TIMEOUT_SECONDS):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 utapractice", **(headers or {})})
    with urlopen(request, timeout=timeout) as response:
        data = response.read().decode("utf-8", errors="replace")
    return json.loads(data)


def normalize_search_result(provider, source_song_id, title="", artist="", album="", duration=None, **extra):
    return {
        "provider": provider,
        "source_song_id": str(source_song_id),
        "title": title or "",
        "artist": artist or "",
        "album": album or "",
        "duration": duration,
        "has_original": bool(extra.pop("has_original", True)),
        "has_translation": bool(extra.pop("has_translation", False)),
        "has_roman": bool(extra.pop("has_roman", False)),
        "has_word_timing": bool(extra.pop("has_word_timing", False)),
        "score": extra.pop("score", None),
        "match_hint": extra.pop("match_hint", ""),
        "source_data": extra,
    }


def text_match_score(query, value):
    query_text = str(query or "").strip().lower()
    value_text = str(value or "").strip().lower()
    if not query_text or not value_text:
        return 0
    if query_text == value_text:
        return 1
    query_key = compact_match_text(query_text)
    value_key = compact_match_text(value_text)
    if query_key and query_key == value_key:
        return 0.98
    if query_text in value_text or value_text in query_text or (query_key and (query_key in value_key or value_key in query_key)):
        return 0.92
    return max(SequenceMatcher(None, query_text, value_text).ratio(), SequenceMatcher(None, query_key, value_key).ratio())


def compact_match_text(value):
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[\s\-_.,，。・·:：'\"“”‘’!?！？()\[\]（）【】<>《》]+", "", value)


def duration_match_score(expected, actual):
    try:
        expected_value = float(expected)
        actual_value = float(actual)
    except (TypeError, ValueError):
        return 0
    if expected_value <= 0 or actual_value <= 0:
        return 0
    delta = abs(expected_value - actual_value)
    if delta <= 2:
        return 1
    if delta <= 6:
        return 0.85
    if delta <= 15:
        return 0.55
    if delta <= 30:
        return 0.25
    return 0


PROVIDER_PRIORITY = {"netease": 0, "qq": 1, "kugou": 2, "lrclib": 3}


def rank_search_result(item, song_name, artist="", album="", duration=None, source_order=0):
    title_score = text_match_score(song_name, item.get("title", ""))
    artist_score = text_match_score(artist, item.get("artist", "")) if artist else 0.75
    album_score = text_match_score(album, item.get("album", "")) if album else 0
    duration_score = duration_match_score(duration, item.get("duration"))
    provider_score = min(max(float(item.get("score") or 0), 0), 1)
    source_relevance = max(0, 1 - min(max(int(source_order), 0), 9) * 0.18)
    availability_bonus = 0
    if item.get("has_translation"):
        availability_bonus += 0.025
    if item.get("has_roman"):
        availability_bonus += 0.015
    if item.get("has_word_timing"):
        availability_bonus += 0.015
    score = (
        title_score * 0.58
        + artist_score * 0.18
        + album_score * 0.05
        + duration_score * 0.05
        + source_relevance * 0.18
        + provider_score * 0.025
        + availability_bonus
    )
    return round(min(score, 1), 4)


def merge_search_results(*result_sets, limit=None):
    merged = []
    seen = set()
    for results in result_sets:
        for item in results:
            key = (item.get("provider"), item.get("source_song_id"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if limit and len(merged) >= limit:
                return merged
    return merged


def normalize_lrclib_results(data):
    results = []
    for item in data[:10]:
        has_synced = bool(item.get("syncedLyrics"))
        results.append(
            normalize_search_result(
                "lrclib",
                item.get("id"),
                item.get("trackName"),
                item.get("artistName"),
                item.get("albumName"),
                item.get("duration"),
                has_original=has_synced or bool(item.get("plainLyrics")),
                has_translation=False,
                has_roman=False,
                has_word_timing=False,
                score=1 if has_synced else 0.6,
            )
        )
    return results


def search_lrclib(song_name, artist="", album=""):
    broad_query = " ".join(part for part in [song_name, artist] if part).strip()
    exact_query = {k: v for k, v in {"track_name": song_name, "artist_name": artist, "album_name": album}.items() if v}
    broad_url = "https://lrclib.net/api/search?" + urlencode({"q": broad_query})
    broad_data = fetch_json(
        broad_url,
        timeout=SEARCH_PROVIDER_TIMEOUT_SECONDS,
    )
    result_sets = [normalize_lrclib_results(broad_data)]
    if not result_sets or not result_sets[0]:
        exact_data = fetch_json(
            f"https://lrclib.net/api/search?{urlencode(exact_query)}",
            timeout=SEARCH_PROVIDER_TIMEOUT_SECONDS,
        )
        result_sets.append(normalize_lrclib_results(exact_data))
    return merge_search_results(*result_sets, limit=10)


def search_netease(song_name, artist="", album=""):
    keyword = " ".join(part for part in [song_name, artist] if part)
    url = "https://music.163.com/api/search/get/web?" + urlencode({"s": keyword, "type": 1, "offset": 0, "limit": 10})
    data = fetch_json(url, headers={"Referer": "https://music.163.com/"}, timeout=SEARCH_PROVIDER_TIMEOUT_SECONDS)
    songs = data.get("result", {}).get("songs", []) if isinstance(data, dict) else []
    results = []
    for item in songs:
        artists = "/".join(artist_item.get("name", "") for artist_item in item.get("artists", []))
        results.append(
            normalize_search_result(
                "netease",
                item.get("id"),
                item.get("name"),
                artists,
                item.get("album", {}).get("name", ""),
                round((item.get("duration") or 0) / 1000) or None,
                has_original=True,
                has_translation=True,
                has_roman=False,
                has_word_timing=False,
            )
        )
    return results


def search_qq(song_name, artist="", album=""):
    keyword = " ".join(part for part in [song_name, artist] if part)
    url = "https://c.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg?" + urlencode({"format": "json", "key": keyword})
    data = fetch_json(url, headers={"Referer": "https://y.qq.com/"}, timeout=SEARCH_PROVIDER_TIMEOUT_SECONDS)
    songs = data.get("data", {}).get("song", {}).get("itemlist", []) if isinstance(data, dict) else []
    results = []
    for item in songs:
        source_id = item.get("mid") or item.get("songmid")
        if not source_id:
            continue
        artists = item.get("singer", "")
        results.append(
            normalize_search_result(
                "qq",
                source_id,
                item.get("name") or item.get("songname"),
                artists,
                item.get("albumname") or "",
                None,
                has_original=True,
                has_translation=True,
                has_roman=False,
                has_word_timing=False,
                qq_id=item.get("id"),
                docid=item.get("docid"),
            )
        )
    return results


def search_kugou(song_name, artist="", album=""):
    keyword = " ".join(part for part in [song_name, artist] if part)
    url = "https://songsearch.kugou.com/song_search_v2?" + urlencode({"keyword": keyword, "page": 1, "pagesize": 10})
    data = fetch_json(url, timeout=SEARCH_PROVIDER_TIMEOUT_SECONDS)
    songs = data.get("data", {}).get("lists", []) if isinstance(data, dict) else []
    results = []
    for item in songs:
        results.append(
            normalize_search_result(
                "kugou",
                item.get("FileHash") or item.get("Hash"),
                item.get("SongName"),
                item.get("SingerName"),
                item.get("AlbumName"),
                item.get("Duration"),
                has_original=True,
                has_translation=False,
                has_roman=False,
                has_word_timing=False,
                album_id=item.get("AlbumID"),
                file_hash=item.get("FileHash") or item.get("Hash"),
            )
        )
    return results


SEARCH_PROVIDERS = {
    "lrclib": search_lrclib,
    "netease": search_netease,
    "qq": search_qq,
    "kugou": search_kugou,
}


def preview_lrclib(result):
    source_id = result.get("source_song_id")
    data = fetch_json(f"https://lrclib.net/api/get/{source_id}")
    return {
        "original_lrc": data.get("syncedLyrics") or "",
        "translation_lrc": "",
        "roman_lrc": "",
    }


def preview_netease(result):
    source_id = result.get("source_song_id")
    data = fetch_json(
        "https://music.163.com/api/song/lyric?" + urlencode({"id": source_id, "lv": 1, "kv": 1, "tv": -1, "rv": 1}),
        headers={"Referer": "https://music.163.com/"},
    )
    return {
        "original_lrc": data.get("lrc", {}).get("lyric", "") or "",
        "translation_lrc": data.get("tlyric", {}).get("lyric", "") or "",
        "roman_lrc": data.get("romalrc", {}).get("lyric", "") or "",
    }


def preview_qq(result):
    songmid = result.get("source_song_id")
    url = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?" + urlencode(
        {"songmid": songmid, "g_tk": 5381, "format": "json", "nobase64": 1}
    )
    data = fetch_json(url, headers={"Referer": "https://y.qq.com/"})
    return {
        "original_lrc": data.get("lyric", "") or "",
        "translation_lrc": data.get("trans", "") or "",
        "roman_lrc": data.get("roma", "") or "",
    }


def preview_kugou(result):
    source = result.get("source_data", {})
    keyword = " ".join(part for part in [result.get("title"), result.get("artist")] if part)
    search_url = "https://lyrics.kugou.com/search?" + urlencode(
        {"ver": 1, "man": "yes", "client": "pc", "keyword": keyword, "duration": result.get("duration") or 0, "hash": source.get("file_hash") or result.get("source_song_id")}
    )
    search_data = fetch_json(search_url)
    candidates = search_data.get("candidates", []) if isinstance(search_data, dict) else []
    if not candidates:
        return {"original_lrc": "", "translation_lrc": "", "roman_lrc": ""}
    candidate = candidates[0]
    download_url = "https://lyrics.kugou.com/download?" + urlencode(
        {"ver": 1, "client": "pc", "id": candidate.get("id"), "accesskey": candidate.get("accesskey"), "fmt": "lrc", "charset": "utf8"}
    )
    data = fetch_json(download_url)
    content = data.get("content", "")
    try:
        lyric = base64.b64decode(content).decode("utf-8", errors="replace") if content else ""
    except Exception:
        lyric = ""
    return {"original_lrc": lyric, "translation_lrc": "", "roman_lrc": ""}


PREVIEW_PROVIDERS = {
    "lrclib": preview_lrclib,
    "netease": preview_netease,
    "qq": preview_qq,
    "kugou": preview_kugou,
}


def nearest_text(rows, time_value, max_distance=0.75):
    if not rows:
        return ""
    exact = [row["text"] for row in rows if float(row["time"]) == float(time_value) and row.get("text")]
    if exact:
        return " / ".join(exact)
    nearest = min(rows, key=lambda row: abs(float(row["time"]) - float(time_value)))
    if abs(float(nearest["time"]) - float(time_value)) <= max_distance:
        return nearest.get("text", "")
    return ""


def align_lrc_sources(original_lrc, translation_lrc="", roman_lrc=""):
    original_rows = group_lrc_rows(parse_lrc_timestamps(original_lrc))
    translation_rows = group_lrc_rows(parse_lrc_timestamps(translation_lrc))
    roman_rows = group_lrc_rows(parse_lrc_timestamps(roman_lrc))
    line_rows = []
    for index, row in enumerate(original_rows):
        line_rows.append(
            {
                "index": index,
                "time": row["time"],
                "original": row.get("text", ""),
                "translation": nearest_text(translation_rows, row["time"]),
                "roman": nearest_text(roman_rows, row["time"]),
            }
        )
    return line_rows


def workspace_from_preview(song_name, artist, result, preview):
    original_lrc = preview.get("original_lrc", "") or ""
    translation_lrc = preview.get("translation_lrc", "") or ""
    roman_lrc = preview.get("roman_lrc", "") or ""
    return {
        "song_name": song_name,
        "artist": artist or "",
        "source": {
            "provider": result.get("provider", ""),
            "song_id": result.get("source_song_id", ""),
            "album": result.get("album", ""),
            "duration": result.get("duration"),
        },
        "original_lrc": original_lrc,
        "translation_lrc": translation_lrc,
        "roman_lrc": roman_lrc,
        "line_rows": align_lrc_sources(original_lrc, translation_lrc, roman_lrc),
        "generated_lyrics": [],
        "status": "draft",
        "updated_at": now_iso(),
    }


def serialize_preview(result, preview):
    original_lrc = preview.get("original_lrc", "") or ""
    translation_lrc = preview.get("translation_lrc", "") or ""
    roman_lrc = preview.get("roman_lrc", "") or ""
    line_rows = align_lrc_sources(original_lrc, translation_lrc, roman_lrc)
    return {
        "result": result,
        "original_lrc": original_lrc,
        "translation_lrc": translation_lrc,
        "roman_lrc": roman_lrc,
        "line_rows": line_rows,
        "has_translation": bool(translation_lrc.strip()),
        "has_roman": bool(roman_lrc.strip()),
    }


def safe_ruby_html(value):
    value = str(value or "")
    placeholders = []

    def stash(match):
        index = len(placeholders)
        tag = match.group(0).lower()
        tag = re.sub(r"\s+", "", tag)
        placeholders.append(tag)
        return f"@@RUBY_TAG_{index}@@"

    protected = re.sub(r"</?\s*(?:ruby|rt|rp)\s*>", stash, value, flags=re.I)
    escaped = html.escape(protected, quote=False)
    for index, tag in enumerate(placeholders):
        escaped = escaped.replace(f"@@RUBY_TAG_{index}@@", tag)
    return escaped


def fallback_generated_row(row):
    return {
        "time": row.get("time", 0),
        "original_html": html.escape(str(row.get("original", "") or ""), quote=False),
        "translation": str(row.get("translation", "") or "").strip(),
    }


def legacy_lenient_normalize_workspace_generated_chunk(result, target_rows, report):
    normalized_by_index = {}
    warnings = []
    if not isinstance(result, list):
        warnings.append("模型返回值不是数组，本段使用原文兜底")
        result = []

    target_by_index = {int(row["index"]): row for row in target_rows}
    for fallback_order, item in enumerate(result):
        if not isinstance(item, dict):
            continue
        raw_index = item.get("index")
        try:
            row_index = int(raw_index)
        except (TypeError, ValueError):
            if fallback_order < len(target_rows):
                row_index = int(target_rows[fallback_order]["index"])
                warnings.append(f"模型第 {fallback_order + 1} 条缺少 index，已按顺序归入 {row_index}")
            else:
                continue
        if row_index not in target_by_index:
            warnings.append(f"模型返回了目标外 index {row_index}，已忽略")
            continue
        source = target_by_index[row_index]
        if lyric_base_key(original_html) != lyric_base_key(source.get("original", "")):
            raise ValueError(
                f"index {row_index} 的原文被改写或读音被拼进正文：期望 {source.get('original', '')}，得到 {strip_html(original_html)}"
            )
        normalized_by_index[row_index] = {
            "time": source.get("time", item.get("time", 0)),
            "original_html": safe_ruby_html(item.get("original_html", source.get("original", ""))),
            "translation": str(item.get("translation", source.get("translation", "")) or "").strip(),
        }

    merged = []
    for row in target_rows:
        row_index = int(row["index"])
        item = normalized_by_index.get(row_index)
        if not item:
            warnings.append(f"index {row_index} 未返回，已用原文兜底")
            item = fallback_generated_row(row)
        merged.append(item)

    for warning in warnings[:6]:
        report(f"提示：{warning}")
    if len(warnings) > 6:
        report(f"提示：本段还有 {len(warnings) - 6} 条索引修正信息")
    return merged


def strip_html(value):
    text = str(value or "")
    text = re.sub(r"<\s*(?:rt|rp)\b[^>]*>.*?<\s*/\s*(?:rt|rp)\s*>", "", text, flags=re.I | re.S)
    return re.sub(r"<[^>]+>", "", text).strip()


def lyric_base_key(value):
    text = html.unescape(strip_html(value))
    for _ in range(2):
        next_text = html.unescape(text)
        if next_text == text:
            break
        text = next_text
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", "", text)


CJK_IDEOGRAPH_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def count_kanji(text):
    return len(CJK_IDEOGRAPH_RE.findall(str(text or "")))


def kanji_coverage(original_html, original_text):
    """返回 (已标注汉字数, 总汉字数)；原文无汉字时返回 None（不做校验）。"""
    total = count_kanji(strip_html(original_text))
    if total == 0:
        return None
    covered = sum(
        count_kanji(base) for base in re.findall(r"<ruby>([^<]*)<rt>", original_html or "", flags=re.S)
    )
    return covered, total


class RubyStructureParser(HTMLParser):
    allowed_tags = {"ruby", "rt", "rp"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in self.allowed_tags:
            self.errors.append(f"不允许的 HTML 标签 <{tag}>")
            return
        if tag in {"rt", "rp"} and "ruby" not in self.stack:
            self.errors.append(f"<{tag}> 不在 <ruby> 内")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag not in self.allowed_tags:
            self.errors.append(f"不允许的 HTML 结束标签 </{tag}>")
            return
        if tag not in self.stack:
            self.errors.append(f"多余的结束标签 </{tag}>")
            return
        while self.stack:
            current = self.stack.pop()
            if current == tag:
                break
            self.errors.append(f"<{current}> 在 </{tag}> 前未闭合")

    def close(self):
        super().close()
        for tag in reversed(self.stack):
            self.errors.append(f"<{tag}> 未闭合")
        self.stack.clear()


def validate_ruby_structure(value):
    parser = RubyStructureParser()
    try:
        parser.feed(str(value or ""))
        parser.close()
    except Exception as exc:
        return [f"HTML 解析失败：{exc}"]
    return parser.errors


def normalize_workspace_generated_chunk(result, target_rows, report):
    if isinstance(result, dict) and isinstance(result.get("items"), list):
        result = result["items"]
    if not isinstance(result, list):
        raise ValueError("模型返回值不是 JSON 数组，也不是带 items 数组的对象")

    target_by_index = {int(row["index"]): row for row in target_rows}
    expected_indexes = set(target_by_index)
    normalized_by_index = {}
    extra_indexes = []
    invalid_items = []

    def normalize_one(item, source, label):
        if not isinstance(item, dict):
            raise ValueError(f"{label} 不是对象")
        original_html = safe_ruby_html(item.get("original_html", ""))
        ruby_errors = validate_ruby_structure(original_html)
        if ruby_errors:
            raise ValueError(f"{label} 的 ruby HTML 结构非法：{ruby_errors[0]}")
        if lyric_base_key(original_html) != lyric_base_key(source.get("original", "")):
            raise ValueError(
                f"{label} 的原文被改写或读音被拼进正文：期望 {source.get('original', '')}，得到 {strip_html(original_html)}"
            )
        if str(source.get("original", "") or "").strip() and not strip_html(original_html):
            raise ValueError(f"{label} 的 original_html 为空")
        coverage = kanji_coverage(original_html, source.get("original", ""))
        if coverage:
            covered, total = coverage
            if covered < total:
                raise ValueError(f"{label} 有 {total} 个汉字未标注 ruby（已标注 {covered}），触发回修")
        return {
            "time": source.get("time", 0),
            "original_html": original_html,
            "translation": str(item.get("translation", source.get("translation", "")) or "").strip(),
            "roman": str(source.get("roman", source.get("roman_or_pronunciation", "")) or "").strip(),
        }

    if len(result) == len(target_rows):
        return [normalize_one(item, source, f"第 {position} 条") for position, (item, source) in enumerate(zip(result, target_rows), start=1)]

    row_number_items = {}
    row_number_invalid = []
    for position, item in enumerate(result, start=1):
        if not isinstance(item, dict) or item.get("row_number") is None:
            continue
        try:
            row_number = int(item.get("row_number"))
        except (TypeError, ValueError):
            row_number_invalid.append(f"第 {position} 条 row_number 无效")
            continue
        if 1 <= row_number <= len(target_rows):
            row_number_items[row_number] = item
        else:
            row_number_invalid.append(f"第 {position} 条 row_number 超出本段范围：{row_number}")
    if row_number_items:
        missing_row_numbers = [row_number for row_number in range(1, len(target_rows) + 1) if row_number not in row_number_items]
        if row_number_invalid or missing_row_numbers:
            parts = row_number_invalid[:3]
            if missing_row_numbers:
                parts.append(f"缺少本段 row_number：{missing_row_numbers[:6]}")
            raise ValueError("；".join(parts))
        return [
            normalize_one(row_number_items[row_number], target_rows[row_number - 1], f"row_number {row_number}")
            for row_number in range(1, len(target_rows) + 1)
        ]

    for position, item in enumerate(result, start=1):
        if not isinstance(item, dict):
            invalid_items.append(f"第 {position} 条不是对象")
            continue
        try:
            row_index = int(item.get("index"))
        except (TypeError, ValueError):
            invalid_items.append(f"第 {position} 条缺少有效 index")
            continue
        if row_index not in target_by_index:
            extra_indexes.append(row_index)
            continue

        source = target_by_index[row_index]
        normalized_by_index[row_index] = normalize_one(item, source, f"index {row_index}")

    missing_indexes = sorted(expected_indexes - set(normalized_by_index))
    if invalid_items or extra_indexes or missing_indexes:
        parts = []
        if invalid_items:
            parts.append("；".join(invalid_items[:3]))
        if extra_indexes:
            parts.append(f"返回了目标外 index：{extra_indexes[:6]}")
        if missing_indexes:
            parts.append(f"缺少 index：{missing_indexes[:6]}")
        raise ValueError("；".join(parts))

    return [normalized_by_index[int(row["index"])] for row in target_rows]


def validate_generated_workspace_lyrics(generated, rows):
    errors = []
    if not isinstance(generated, list):
        return ["生成结果不是 JSON 数组"]
    if len(generated) != len(rows):
        errors.append(f"行数不一致：期望 {len(rows)}，得到 {len(generated)}")
    for position, row in enumerate(rows[: len(generated)]):
        item = generated[position]
        if not isinstance(item, dict):
            errors.append(f"第 {position + 1} 行不是对象")
            continue
        try:
            expected_time = float(row.get("time", 0))
            actual_time = float(item.get("time", 0))
        except (TypeError, ValueError):
            errors.append(f"第 {position + 1} 行 time 不是数字")
            continue
        if abs(expected_time - actual_time) > 0.001:
            errors.append(f"第 {position + 1} 行 time 被修改：期望 {expected_time}，得到 {actual_time}")
        if str(row.get("original", "") or "").strip() and not strip_html(item.get("original_html", "")):
            errors.append(f"第 {position + 1} 行 original_html 为空")
        ruby_errors = validate_ruby_structure(item.get("original_html", ""))
        if ruby_errors:
            errors.append(f"第 {position + 1} 行 ruby HTML 结构非法：{ruby_errors[0]}")
        coverage = kanji_coverage(item.get("original_html", ""), row.get("original", ""))
        if coverage:
            covered, total = coverage
            if covered < total:
                errors.append(f"第 {position + 1} 行有 {total} 个汉字未标注 ruby（已标注 {covered}）")
        if lyric_base_key(item.get("original_html", "")) != lyric_base_key(row.get("original", "")):
            errors.append(
                f"第 {position + 1} 行原文被改写或读音被拼进正文：期望 {row.get('original', '')}，得到 {strip_html(item.get('original_html', ''))}"
            )
        if item.get("translation") is not None and not isinstance(item.get("translation"), str):
            errors.append(f"第 {position + 1} 行 translation 不是字符串")
    return errors


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
    model = settings.get("model") or "deepseek-v4-pro"
    raise_if_stopped(job_id)

    report("正在清理注音文本")
    cleaned = chat_json(
        client,
        model,
        CLEAN_SOURCE_SYSTEM_PROMPT,
        {
            "task": "Extract and clean lyric lines.",
            "output_schema": {"lines": ["lyric line with ruby/furigana/jyutping if present"]},
            "input_text": annotated_text,
        },
        json_object=True,
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
            RUBY_GENERATION_SYSTEM_PROMPT,
            {
                "task": "Generate ruby annotated timed lyric JSON.",
                "metadata": {
                    "mode": "stable_full_song_after_cleaning",
                    "expected_item_count": len(target_rows),
                },
                "output_schema": {
                    "items": [
                        {
                            "time": 12.34,
                            "original_html": "lyrics with <ruby>漢字<rt>かんじ</rt></ruby>",
                            "translation": "plain translation string or empty",
                        }
                    ]
                },
                "input_data": {
                    "target_rows": ruby_rows_for_model(target_rows, include_time=True),
                    "pronunciation_reference_lines": [
                        {"index": i, "text": line}
                        for i, line in enumerate(cleaned_lines)
                    ],
                },
            },
            json_object=True,
        )
        raise_if_stopped(job_id)
        converted = unwrap_items_result(converted, "Stable generation")
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
                RUBY_GENERATION_SYSTEM_PROMPT,
                {
                    "task": "Generate ruby annotated timed lyric JSON.",
                    "metadata": {
                        "mode": "chunked",
                        "chunk_number": index,
                        "total_chunks": len(chunks),
                        "expected_item_count": len(chunk["target_rows"]),
                    },
                    "output_schema": {
                        "items": [
                            {
                                "time": 12.34,
                                "original_html": "lyrics with <ruby>漢字<rt>かんじ</rt></ruby>",
                                "translation": "plain translation string or empty",
                            }
                        ]
                    },
                    "input_data": {
                        "context_rows": ruby_rows_for_model(chunk["context_rows"], include_time=True),
                        "target_rows": ruby_rows_for_model(chunk["target_rows"], include_time=True),
                        "pronunciation_reference_lines": candidate_lines,
                    },
                },
                json_object=True,
            )
            raise_if_stopped(job_id)
            chunk_result = unwrap_items_result(chunk_result, f"Chunk {index}")
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


def perform_ruby_from_rows(payload, report=lambda _message: None, job_id=None):
    song_name = sanitize_filename(str(payload.get("song_name", "")).strip())
    concurrency = int(payload.get("concurrency") or 4)
    concurrency = max(1, min(concurrency, 8))
    max_attempts = int(payload.get("max_attempts") or 4)
    max_attempts = max(1, min(max_attempts, 6))
    chunk_size = int(payload.get("chunk_size") or 8)
    chunk_size = max(2, min(chunk_size, 20))
    if not song_name:
        raise ValueError("Song name is required")

    path = workspace_path(song_name)
    workspace = read_json_path(path)
    if not workspace:
        raise ValueError("Lyrics workspace not found")

    rows = workspace.get("line_rows", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError("Workspace has no aligned lyric rows")

    settings = load_settings()
    if not settings.get("api_key"):
        raise ValueError("API key is not configured")

    normalized_rows = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        normalized_rows.append(
            {
                "index": int(row.get("index", index)),
                "time": row.get("time", 0),
                "original": str(row.get("original", "") or "").strip(),
                "translation": str(row.get("translation", "") or "").strip(),
                "roman": str(row.get("roman", "") or "").strip(),
            }
        )
    if not normalized_rows:
        raise ValueError("Workspace has no usable lyric rows")

    client_args = {"api_key": settings["api_key"], "base_url": settings.get("base_url") or None}
    model = settings.get("model") or "deepseek-v4-pro"
    chunks = chunk_rows(normalized_rows, size=chunk_size, context=2)
    generated_by_index = {}
    chunk_errors = []

    workspace["status"] = "generating"
    workspace["errors"] = []
    workspace["generated_lyrics"] = []
    workspace["updated_at"] = now_iso()
    write_json_path(path, workspace)

    report(f"已读取 {len(normalized_rows)} 行工作源歌词")
    report(f"开始逐段生成 ruby JSON：共 {len(chunks)} 段，并发 {concurrency}")
    update_job(job_id, progress=1)

    system_prompt = RUBY_GENERATION_SYSTEM_PROMPT

    def generate_chunk(chunk_number, chunk):
        raise_if_stopped(job_id)
        report(f"正在生成第 {chunk_number}/{len(chunks)} 段")
        client = OpenAI(**client_args)
        target_rows_for_model = [
            {
                "row_number": position,
                "original": row["original"],
                "translation": row["translation"],
                "roman_or_pronunciation": row["roman"],
            }
            for position, row in enumerate(chunk["target_rows"], start=1)
        ]
        target_indexes = [int(row["index"]) for row in chunk["target_rows"]]
        context_before_rows = [
            row
            for row in chunk["context_rows"]
            if int(row.get("index", -1)) < target_indexes[0]
        ]
        context_after_rows = [
            row
            for row in chunk["context_rows"]
            if int(row.get("index", -1)) > target_indexes[-1]
        ]
        payload_data = {
            "task": "Generate ruby annotated JSON for aligned lyric rows.",
            "metadata": {
                "song_name": workspace.get("song_name") or song_name,
                "artist": workspace.get("artist", ""),
                "chunk_number": chunk_number,
                "total_chunks": len(chunks),
                "expected_item_count": len(chunk["target_rows"]),
            },
            "output_schema": {
                "items": [
                    {
                        "row_number": 1,
                        "original_html": "lyrics with <ruby>漢字<rt>かんじ</rt></ruby>",
                        "translation": "plain translation string or empty",
                    }
                ]
            },
            "input_data": {
                "context_rows_before": ruby_rows_for_model(context_before_rows),
                "target_rows": target_rows_for_model,
                "context_rows_after": ruby_rows_for_model(context_after_rows),
            },
        }
        last_error = None
        last_result = None
        chunk_max_tokens = 8000
        for attempt in range(1, max_attempts + 1):
            raise_if_stopped(job_id)
            request_payload = payload_data
            # 空内容/截断多为瞬时抖动或推理型模型把预算耗尽：原样重试并扩大预算，
            # 避免把空的 previous_output 丢给回修提示词；其它校验失败才走回修。
            retryable_blank = is_empty_content_error(last_error) or is_truncated_error(last_error)
            use_repair = attempt > 1 and not retryable_blank
            if use_repair:
                report(f"第 {chunk_number}/{len(chunks)} 段回修 {attempt - 1}/{max_attempts - 1}")
                request_payload = {
                    "task": "Repair invalid JSON from previous failed generation.",
                    "validation_error": str(last_error),
                    "instruction": "The previous output failed validation. Regenerate the ENTIRE chunk for target_rows. Ensure strict adherence to text preservation and ruby tag rules. Discard previous formatting errors.",
                    "previous_output": last_result,
                    "metadata": payload_data["metadata"],
                    "output_schema": payload_data["output_schema"],
                    "input_data": {
                        "target_rows": target_rows_for_model,
                    },
                }
            try:
                result = chat_json(client, model, system_prompt, request_payload, max_tokens=chunk_max_tokens, json_object=True)
                raise_if_stopped(job_id)
                last_result = result
                return normalize_workspace_generated_chunk(result, chunk["target_rows"], report)
            except RuntimeError:
                raise
            except FatalJobError:
                raise
            except Exception as exc:
                if is_fatal_api_error(exc):
                    raise FatalJobError(friendly_api_error(exc)) from exc
                last_error = exc
                if is_truncated_error(exc) or is_empty_content_error(exc):
                    chunk_max_tokens = min(chunk_max_tokens + 4000, 24000)
                    report(f"第 {chunk_number}/{len(chunks)} 段第 {attempt}/{max_attempts} 次失败：{exc}；已把输出预算扩到 {chunk_max_tokens} 重试")
                else:
                    report(f"第 {chunk_number}/{len(chunks)} 段第 {attempt}/{max_attempts} 次失败：{exc}")
                if attempt < max_attempts:
                    time.sleep(min(2 * attempt, 6))
        raise ValueError(f"第 {chunk_number}/{len(chunks)} 段连续 {max_attempts} 次失败：{last_error}")

    fatal_error = None
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(generate_chunk, chunk_number, chunk): (chunk_number, chunk)
            for chunk_number, chunk in enumerate(chunks, start=1)
        }
        completed = 0
        for future in as_completed(futures):
            chunk_number, chunk = futures[future]
            raise_if_stopped(job_id)
            try:
                chunk_result = future.result()
                for offset, row in enumerate(chunk["target_rows"]):
                    generated_by_index[int(row["index"])] = chunk_result[offset]
                report(f"第 {chunk_number}/{len(chunks)} 段完成")
            except RuntimeError:
                raise
            except FatalJobError as exc:
                fatal_error = exc
                for other in futures:
                    other.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                report(f"检测到不可恢复错误，任务中止：{exc}")
                break
            except Exception as exc:
                message = f"第 {chunk_number}/{len(chunks)} 段失败：{exc}"
                report(message)
                chunk_errors.append({"chunk": chunk_number, "error": str(exc)})
            completed += 1
            progress = 1 + round(completed / max(len(chunks), 1) * 94)
            update_job(job_id, progress=progress, message=f"已完成 {completed}/{len(chunks)} 段")

    if fatal_error:
        workspace["status"] = "generation_failed"
        workspace["errors"] = [{"error": str(fatal_error)}]
        workspace["updated_at"] = now_iso()
        write_json_path(path, workspace)
        raise fatal_error

    if chunk_errors:
        workspace["status"] = "generation_failed"
        workspace["errors"] = chunk_errors
        workspace["updated_at"] = now_iso()
        write_json_path(path, workspace)
        report(f"生成失败：{len(chunk_errors)} 个分段重试后仍失败，未写入新的 generated_lyrics")
        raise ValueError(f"{len(chunk_errors)} 个分段生成失败，已停止写入 generated_lyrics")

    report("正在合并结果")
    missing_indexes = [int(row["index"]) for row in normalized_rows if int(row["index"]) not in generated_by_index]
    if missing_indexes:
        workspace["status"] = "validation_failed"
        workspace["errors"] = [{"error": f"缺少 index：{missing_indexes[:20]}"}]
        workspace["updated_at"] = now_iso()
        write_json_path(path, workspace)
        report(f"校验失败：缺少 index {missing_indexes[:20]}，未写入新的 generated_lyrics")
        raise ValueError("生成结果缺少分段输出，已停止写入 generated_lyrics")

    generated = [generated_by_index[int(row["index"])] for row in normalized_rows]
    generated = normalize_converted_lyrics(generated)
    validation_errors = validate_generated_workspace_lyrics(generated, normalized_rows)
    if validation_errors:
        workspace["status"] = "validation_failed"
        workspace["errors"] = [{"error": message} for message in validation_errors[:20]]
        workspace["updated_at"] = now_iso()
        write_json_path(path, workspace)
        for message in validation_errors[:8]:
            report(f"校验失败：{message}")
        if len(validation_errors) > 8:
            report(f"校验失败：另有 {len(validation_errors) - 8} 条错误")
        raise ValueError(f"生成结果校验失败：{validation_errors[0]}")

    workspace["line_rows"] = normalized_rows
    workspace["generated_lyrics"] = generated
    workspace["status"] = "generated"
    workspace["errors"] = []
    workspace["updated_at"] = now_iso()
    write_json_path(path, workspace)
    report("已写入 generated_lyrics")
    report(f"生成结果已写入工作源，共 {len(generated)} 行。发布前不会覆盖正式歌词")
    update_job(job_id, progress=100)

    return {
        "ok": True,
        "song_name": song_name,
        "mode": "workspace",
        "lyrics": generated,
        "errors": [],
    }


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


@app.route("/app")
def mobile_app():
    return render_template("mobile_app.html")


@app.get("/api/app/health")
def api_app_health():
    return jsonify(
        {
            "ok": True,
            "name": "utapractice",
            "server_time": now_iso(),
            "songs_count": len(find_available_songs()),
        }
    )


@app.get("/api/songs")
def api_songs():
    db = load_db()
    songs = find_available_songs()
    payload = []
    for name in songs:
        info = db.get(name, {})
        song = songs[name]
        audio_status = audio_compatibility(song["audio_path"]) if song["audio_path"] else {"playable": False, "error": ""}
        audio_meta = audio_metadata(song["audio_path"])
        payload.append(
            {
                "name": name,
                "has_audio": song["audio_path"] is not None,
                "audio_playable": audio_status["playable"],
                "audio_error": audio_status["error"],
                "audio_size": audio_meta["audio_size"],
                "audio_mtime": audio_meta["audio_mtime"],
                "audio_mime": audio_meta["audio_mime"],
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
    audio_status = audio_compatibility(song["audio_path"]) if song["audio_path"] else {"playable": False, "error": ""}
    audio_meta = audio_metadata(song["audio_path"])
    return jsonify(
            {
                "name": name,
                "has_audio": song["audio_path"] is not None,
                "audio_playable": audio_status["playable"],
                "audio_error": audio_status["error"],
                "audio_size": audio_meta["audio_size"],
                "audio_mtime": audio_meta["audio_mtime"],
                "audio_mime": audio_meta["audio_mime"],
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

    audio_status = audio_compatibility(song["audio_path"])
    if not audio_status["playable"]:
        return jsonify({"error": audio_status["error"]}), 415

    key_shift = int(request.args.get("key", 0))
    audio_path = song["audio_path"] if key_shift == 0 else shifted_audio_path(song["audio_path"], key_shift)
    mime_type = audio_mime_type(audio_path)
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
        archive_song_file(source)

    db = load_db()
    db.pop(name, None)
    save_db(db)
    return jsonify({"ok": True})


@app.post("/api/upload/audio")
def api_upload_audio():
    files = [file for file in request.files.getlist("audio") if file.filename]
    target_song = sanitize_filename(request.form.get("target_song", "").strip())
    saved = []
    if not files:
        return jsonify({"error": "No audio files uploaded"}), 400
    if target_song and len(files) != 1:
        return jsonify({"error": "Only one audio file can be attached to an existing lyric"}), 400
    if target_song:
        song = find_available_songs().get(target_song)
        if not song:
            return jsonify({"error": "Target lyric song not found"}), 404
        if not song["lyrics_path"]:
            return jsonify({"error": "Target song has no lyrics"}), 400
        if song["audio_path"] and audio_compatibility(song["audio_path"])["playable"]:
            return jsonify({"error": "Target song already has audio"}), 409

    for file in files:
        filename = sanitize_filename(file.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            return jsonify({"error": f"Unsupported audio file: {filename}"}), 400
        target = SONG_DIR / f"{target_song}{suffix}" if target_song else SONG_DIR / filename
        if target_song and song["audio_path"]:
            archive_song_file(song["audio_path"])
            song["audio_path"] = None
        if target_song and target.exists():
            return jsonify({"error": "Target audio file already exists"}), 409
        file.save(target)
        saved.append(target.name)
    return jsonify({"ok": True, "saved": saved})


@app.post("/api/upload/lyrics")
def api_upload_lyrics():
    files = [file for file in request.files.getlist("lyrics") if file.filename]
    target_song = sanitize_filename(request.form.get("target_song", "").strip())
    song_name = sanitize_filename(request.form.get("song_name", "").strip())
    saved = []
    if not files:
        return jsonify({"error": "No lyrics files uploaded"}), 400
    if target_song and len(files) != 1:
        return jsonify({"error": "Only one lyrics file can be attached to an existing song"}), 400
    if target_song:
        song = find_available_songs().get(target_song)
        if not song:
            return jsonify({"error": "Target song not found"}), 404
        if not song["audio_path"]:
            return jsonify({"error": "Target song has no audio"}), 400
        if song["lyrics_path"]:
            return jsonify({"error": "Target song already has lyrics"}), 409
    elif song_name and len(files) != 1:
        return jsonify({"error": "Only one lyrics file can use a custom song name"}), 400

    for file in files:
        filename = sanitize_filename(file.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in LYRICS_EXTENSIONS:
            return jsonify({"error": f"Unsupported lyrics file: {filename}"}), 400
        save_name = target_song or song_name
        target = SONG_DIR / f"{save_name}{suffix}" if save_name else SONG_DIR / filename
        existing = find_available_songs().get(save_name) if save_name else None
        if existing and existing["lyrics_path"]:
            return jsonify({"error": "Target song already has lyrics"}), 409
        if target.exists():
            return jsonify({"error": "Target lyrics file already exists"}), 409
        file.save(target)
        saved.append(target.name)
    return jsonify({"ok": True, "saved": saved})


@app.post("/api/upload/lyrics-text")
def api_upload_lyrics_text():
    payload = request.get_json(force=True)
    target_song = sanitize_filename(str(payload.get("target_song", "")).strip())
    song_name = sanitize_filename(str(payload.get("song_name", "")).strip())
    lyrics_text = str(payload.get("lyrics_text", "")).strip()
    lyrics_type = str(payload.get("lyrics_type", "lrc"))
    lyrics_type = lyrics_type.strip().lower()

    if target_song:
        song = find_available_songs().get(target_song)
        if not song:
            return jsonify({"error": "Target song not found"}), 404
        if not song["audio_path"]:
            return jsonify({"error": "Target song has no audio"}), 400
        if song["lyrics_path"]:
            return jsonify({"error": "Target song already has lyrics"}), 409
        song_name = target_song
    if not song_name:
        return jsonify({"error": "Song name is required"}), 400
    if not lyrics_text:
        return jsonify({"error": "Lyrics text is required"}), 400
    if lyrics_type not in {"lrc", "json"}:
        return jsonify({"error": "Lyrics type must be lrc or json"}), 400

    existing = find_available_songs().get(song_name)
    if existing and existing["lyrics_path"]:
        return jsonify({"error": "Target song already has lyrics"}), 409

    if lyrics_type == "json":
        try:
            parsed = json.loads(lyrics_text)
        except json.JSONDecodeError as exc:
            return jsonify({"error": f"Invalid JSON lyrics: {exc}"}), 400
        if not isinstance(parsed, list):
            return jsonify({"error": "JSON lyrics must be an array"}), 400
        target = SONG_DIR / f"{song_name}.json"
        if target.exists():
            return jsonify({"error": "Target lyrics file already exists"}), 409
        with target.open("w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2, ensure_ascii=False)
        return jsonify({"ok": True, "song_name": song_name, "saved": target.name, "lines": len(parsed)})

    rows = parse_lrc(lyrics_text)
    if not rows:
        return jsonify({"error": "LRC lyrics must include timestamped lines"}), 400
    target = SONG_DIR / f"{song_name}.lrc"
    if target.exists():
        return jsonify({"error": "Target lyrics file already exists"}), 409
    target.write_text(f"{lyrics_text}\n", encoding="utf-8")
    return jsonify({"ok": True, "song_name": song_name, "saved": target.name, "lines": len(rows)})


@app.post("/api/lyrics-search")
def api_lyrics_search():
    payload = request.get_json(force=True)
    song_name = str(payload.get("song_name", "")).strip()
    artist = str(payload.get("artist", "")).strip()
    album = str(payload.get("album", "")).strip()
    duration = payload.get("duration")
    provider = str(payload.get("provider", "aggregate")).strip() or "aggregate"
    if not song_name:
        return jsonify({"error": "Song name is required"}), 400

    providers = list(SEARCH_PROVIDERS) if provider == "aggregate" else [provider]
    results = []
    errors = {}
    def search_one(provider_name):
        searcher = SEARCH_PROVIDERS.get(provider_name)
        if not searcher:
            return provider_name, [], "Unknown provider"
        try:
            return provider_name, searcher(song_name, artist, album), None
        except Exception as exc:
            return provider_name, [], str(exc)

    executor = ThreadPoolExecutor(max_workers=min(4, max(1, len(providers))))
    futures = {provider_name: executor.submit(search_one, provider_name) for provider_name in providers}
    future_providers = {future: provider_name for provider_name, future in futures.items()}
    try:
        for future in as_completed(futures.values(), timeout=SEARCH_AGGREGATE_TIMEOUT_SECONDS):
            provider_name = future_providers[future]
            try:
                provider_name, provider_results, error = future.result(timeout=SEARCH_PROVIDER_TIMEOUT_SECONDS)
            except Exception as exc:
                errors[provider_name] = str(exc)
                continue
            if error:
                errors[provider_name] = error
                continue
            for source_order, item in enumerate(provider_results):
                score = rank_search_result(item, song_name, artist, album, duration, source_order)
                item["score"] = score
                item["match_hint"] = item.get("match_hint") or f"{item.get('provider')} · {item.get('artist') or 'unknown'}"
                item["_provider_priority"] = PROVIDER_PRIORITY.get(item.get("provider"), 99)
                item["_source_order"] = source_order
                results.append(item)
    except FuturesTimeoutError:
        pass
    finally:
        for provider_name, future in futures.items():
            if not future.done():
                future.cancel()
                errors[provider_name] = "Timed out"
        executor.shutdown(wait=False, cancel_futures=True)

    seen = set()
    deduped = []
    for item in sorted(
        results,
        key=lambda row: (
            -(row.get("score") or 0),
            row.get("_source_order", 999),
            row.get("_provider_priority", 99),
            str(row.get("title", "")),
        ),
    ):
        key = (item.get("provider"), item.get("source_song_id"))
        if key in seen:
            continue
        seen.add(key)
        item.pop("_provider_priority", None)
        item.pop("_source_order", None)
        deduped.append(item)
    return jsonify({"results": deduped[:30], "errors": errors})


@app.post("/api/lyrics-preview")
def api_lyrics_preview():
    payload = request.get_json(force=True)
    result = payload.get("result") or payload
    if not isinstance(result, dict):
        return jsonify({"error": "Search result is required"}), 400
    provider = result.get("provider")
    previewer = PREVIEW_PROVIDERS.get(provider)
    if not previewer:
        return jsonify({"error": "Unknown provider"}), 400
    try:
        preview = previewer(result)
        return jsonify(serialize_preview(result, preview))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/lyrics-workspace/<path:name>")
def api_get_lyrics_workspace(name):
    path = workspace_path(name)
    workspace = read_json_path(path)
    if not workspace:
        return jsonify({"error": "Lyrics workspace not found"}), 404
    return jsonify(workspace)


@app.post("/api/lyrics-workspace/<path:name>")
def api_save_lyrics_workspace(name):
    payload = request.get_json(force=True)
    song_name = sanitize_filename(str(payload.get("song_name") or name).strip())
    if not song_name:
        return jsonify({"error": "Song name is required"}), 400

    existing = read_json_path(workspace_path(song_name), {})
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
        "line_rows": align_lrc_sources(original_lrc, translation_lrc, roman_lrc),
        "generated_lyrics": payload.get("generated_lyrics") if isinstance(payload.get("generated_lyrics"), list) else [],
        "status": "draft",
        "updated_at": now_iso(),
    }
    write_json_path(workspace_path(song_name), workspace)
    return jsonify(workspace)


@app.post("/api/lyrics-workspace/<path:name>/use-preview")
def api_use_lyrics_preview(name):
    payload = request.get_json(force=True)
    result = payload.get("result")
    preview = payload.get("preview")
    if not isinstance(result, dict) or not isinstance(preview, dict):
        return jsonify({"error": "Preview result is required"}), 400
    song_name = sanitize_filename(str(payload.get("song_name") or name).strip())
    artist = str(payload.get("artist") or result.get("artist") or "").strip()
    workspace = workspace_from_preview(song_name, artist, result, preview)
    write_json_path(workspace_path(song_name), workspace)
    return jsonify(workspace)


@app.post("/api/lyrics-workspace/<path:name>/from-song")
def api_seed_workspace_from_song(name):
    """把歌库中已有歌曲的歌词作为工作源，供「下载后 AI 生成 ruby JSON」使用。

    原始逻辑会带网易云的三份歌词（原文 + 翻译 tlyric + 罗马音 romalrc），
    下载时已按 {歌名}.lrc / {歌名}.zh.lrc / {歌名}.roma.lrc 落盘，
    这里一并读入工作源，保证生成的歌词同时含翻译与罗马音。
    """
    song_name = sanitize_filename(str(name).strip())
    song = get_song_or_404(song_name)
    if not song or not song.get("lyrics_path"):
        return jsonify({"error": "这首歌还没有歌词，无法生成 ruby JSON"}), 400

    def companion_lrc(suffix):
        companion = SONG_DIR / f"{song_name}{suffix}"
        if companion.exists():
            return companion.read_text(encoding="utf-8", errors="replace")
        return ""

    # 下载时新逻辑会额外落盘 {歌名}.zh.lrc（翻译）与 {歌名}.roma.lrc（罗马音），
    # 与正式歌词是 .lrc 还是 .json 无关，一律优先采用。
    translation_lrc = companion_lrc(".zh.lrc")
    roman_lrc = companion_lrc(".roma.lrc")

    if song["lyrics_path"].suffix.lower() == ".lrc":
        original_lrc = song["lyrics_path"].read_text(encoding="utf-8", errors="replace")
    else:
        lyrics = read_lyrics(song["lyrics_path"])
        if not isinstance(lyrics, list):
            return jsonify({"error": "歌词格式无法解析为时间轴"}), 400
        original_lines = []
        fallback_translation_lines = []
        fallback_roman_lines = []
        for line in lyrics:
            if not isinstance(line, dict):
                continue
            time = round(float(line.get("time") or 0), 3)
            minutes = int(time // 60)
            seconds = time - minutes * 60
            stamp = f"[{minutes:02d}:{seconds:05.2f}]"
            text = re.sub(r"<rt>.*?</rt>|<rp>.*?</rp>", "", str(line.get("original_html") or ""), flags=re.S)
            text = re.sub(r"<[^>]+>", "", text).strip()
            if text:
                original_lines.append(f"{stamp}{text}")
            # 正式 .json 里若已带翻译/罗马音（新生成会带上），无配套文件时兜底采用
            if not translation_lrc:
                translation = str(line.get("translation") or "").strip()
                if translation:
                    fallback_translation_lines.append(f"{stamp}{translation}")
            if not roman_lrc:
                roman = str(line.get("roman") or line.get("roman_or_pronunciation") or "").strip()
                if roman:
                    fallback_roman_lines.append(f"{stamp}{roman}")
        original_lrc = "\n".join(original_lines)
        if not translation_lrc:
            translation_lrc = "\n".join(fallback_translation_lines)
        if not roman_lrc:
            roman_lrc = "\n".join(fallback_roman_lines)

    workspace = {
        "song_name": song_name,
        "artist": "",
        "source": {"provider": "netease", "song_id": "", "album": "", "duration": None},
        "original_lrc": original_lrc,
        "translation_lrc": translation_lrc,
        "roman_lrc": roman_lrc,
        "line_rows": align_lrc_sources(original_lrc, translation_lrc, roman_lrc),
        "generated_lyrics": [],
        "status": "draft",
        "updated_at": now_iso(),
    }
    write_json_path(workspace_path(song_name), workspace)
    return jsonify(workspace)


@app.post("/api/lyrics-align/<path:name>")
def api_realign_lyrics_workspace(name):
    workspace = read_json_path(workspace_path(name))
    if not workspace:
        return jsonify({"error": "Lyrics workspace not found"}), 404
    workspace["line_rows"] = align_lrc_sources(
        workspace.get("original_lrc", ""),
        workspace.get("translation_lrc", ""),
        workspace.get("roman_lrc", ""),
    )
    workspace["generated_lyrics"] = []
    workspace["status"] = "draft"
    workspace["updated_at"] = now_iso()
    write_json_path(workspace_path(name), workspace)
    return jsonify(workspace)


@app.post("/api/lyrics-workspace/<path:name>/publish")
def api_publish_lyrics_workspace(name):
    workspace = read_json_path(workspace_path(name))
    if not workspace:
        return jsonify({"error": "Lyrics workspace not found"}), 404
    lyrics = workspace.get("generated_lyrics", [])
    if not isinstance(lyrics, list) or not lyrics:
        return jsonify({"error": "No generated lyrics to publish"}), 400
    lyrics = normalize_converted_lyrics(lyrics)
    validation_errors = validate_generated_workspace_lyrics(lyrics, workspace.get("line_rows", []))
    if validation_errors:
        workspace["status"] = "validation_failed"
        workspace["errors"] = [{"error": message} for message in validation_errors[:20]]
        workspace["updated_at"] = now_iso()
        write_json_path(workspace_path(name), workspace)
        return jsonify({"error": f"Generated lyrics failed validation: {validation_errors[0]}"}), 400
    target = SONG_DIR / f"{sanitize_filename(name)}.json"
    write_json_path(target, lyrics)
    workspace["status"] = "published"
    workspace["updated_at"] = now_iso()
    write_json_path(workspace_path(name), workspace)
    return jsonify({"ok": True, "song_name": name, "published_count": len(lyrics), "lyrics_count": len(lyrics)})


@app.get("/api/settings")
def api_get_settings():
    settings = load_settings()
    return jsonify(
        {
            "base_url": settings.get("base_url", ""),
            "model": settings.get("model", "deepseek-v4-pro"),
            "has_api_key": bool(settings.get("api_key")),
        }
    )


@app.post("/api/settings")
def api_save_settings():
    payload = request.get_json(force=True)
    current = load_settings()
    current["base_url"] = str(payload.get("base_url", current.get("base_url", ""))).strip()
    current["model"] = str(payload.get("model", current.get("model", "deepseek-v4-pro"))).strip()
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
            model=settings.get("model") or "deepseek-v4-pro",
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


def run_convert_job_v2(job_id):
    started_at = datetime.now().astimezone()
    update_job(job_id, status="running", message="任务已开始", started_at=started_at.isoformat(timespec="seconds"))
    try:
        with jobs_lock:
            job = load_jobs().get(job_id, {})
            payload = job.get("payload", {})
            job_type = job.get("type", "convert_lyrics")

        if job_type == "generate_ruby_from_rows":
            result = perform_ruby_from_rows(payload, report=lambda message: append_job_step(job_id, message), job_id=job_id)
        else:
            result = perform_lyrics_conversion(payload, report=lambda message: append_job_step(job_id, message), job_id=job_id)

        duration_seconds = round((datetime.now().astimezone() - started_at).total_seconds(), 1)
        update_job(
            job_id,
            status="done",
            progress=100,
            message=f"生成完成，用时 {duration_seconds} 秒",
            result={"song_name": result["song_name"], "mode": result.get("mode", "workspace")},
            duration_seconds=duration_seconds,
            finished_at=now_iso(),
            stop_requested=False,
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
        if is_fatal_api_error(exc):
            exc = ValueError(friendly_api_error(exc))
        append_job_step(job_id, f"生成失败：{exc}")
        update_job(
            job_id,
            status="failed",
            message=f"生成失败：{exc}",
            error=str(exc),
            duration_seconds=duration_seconds,
            finished_at=now_iso(),
            stop_requested=False,
        )


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
    job_type = str(payload.get("type") or payload.get("job_type") or "convert_lyrics").strip()
    if not song_name:
        return jsonify({"error": "Song name is required"}), 400
    if job_type == "generate_ruby_from_rows":
        if not workspace_path(song_name).exists():
            return jsonify({"error": "Lyrics workspace not found"}), 400
    elif not str(payload.get("lrc_text", "")).strip() or not str(payload.get("annotated_text", "")).strip():
        return jsonify({"error": "LRC and annotated text are required"}), 400
    if not load_settings().get("api_key"):
        return jsonify({"error": "API key is not configured"}), 400

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "type": job_type,
        "song_name": song_name,
        "mode": "workspace" if job_type == "generate_ruby_from_rows" else str(payload.get("conversion_mode", "stable")).strip() or "stable",
        "progress": 0,
        "status": "queued",
        "message": "任务已加入后台队列",
        "steps": [{"time": now_iso(), "message": "任务已加入后台队列"}],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "payload": payload,
    }
    queued_message = "工作页任务已加入后台队列" if job_type == "generate_ruby_from_rows" else "任务已加入后台队列"
    job["message"] = queued_message
    job["steps"] = [{"time": now_iso(), "message": queued_message}]
    with jobs_lock:
        jobs = load_jobs()
        jobs[job_id] = job
        save_jobs(jobs)

    thread = threading.Thread(target=run_convert_job_v2, args=(job_id,), daemon=True)
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


@app.post("/api/convert-jobs/<job_id>/retry")
def api_retry_convert_job(job_id):
    """重试失败的歌词生成任务：保留原 payload，重置状态后重新排队执行。"""
    with jobs_lock:
        jobs = load_jobs()
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job.get("status") not in {"failed", "stopped"}:
            return jsonify({"error": "Only failed or stopped jobs can be retried"}), 400
        if not job.get("payload"):
            return jsonify({"error": "Job payload is missing, cannot retry"}), 400
        job["status"] = "queued"
        job["progress"] = 0
        job.pop("error", None)
        job.pop("result", None)
        job.pop("finished_at", None)
        job["stop_requested"] = False
        retry_message = "任务已重新加入后台队列（重试）"
        job["message"] = retry_message
        job["steps"] = [{"time": now_iso(), "message": retry_message}]
        job["updated_at"] = now_iso()
        jobs[job_id] = job
        save_jobs(jobs)
        retried = dict(job)

    thread = threading.Thread(target=run_convert_job_v2, args=(job_id,), daemon=True)
    thread.start()
    return jsonify(public_job(retried)), 202


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

    try:
        client = OpenAI(api_key=settings["api_key"], base_url=settings.get("base_url") or None)
        converted = chat_json(
            client,
            settings.get("model") or "deepseek-v4-pro",
            RUBY_GENERATION_SYSTEM_PROMPT,
            {
                "task": "Generate ruby annotated timed lyric JSON.",
                "metadata": {
                    "mode": "legacy_direct",
                    "expected_item_count": len(rows),
                },
                "output_schema": {
                    "items": [
                        {
                            "time": 12.34,
                            "original_html": "lyrics with <ruby>漢字<rt>かんじ</rt></ruby>",
                            "translation": "plain translation string or empty",
                        }
                    ]
                },
                "input_data": {
                    "target_rows": ruby_rows_for_model(rows, include_time=True),
                    "pronunciation_reference_text": annotated_text,
                },
            },
            json_object=True,
        )
        converted = unwrap_items_result(converted, "Model")
    except Exception as exc:
        return jsonify({"error": f"Model conversion failed: {exc}"}), 502

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
    model = settings.get("model") or "deepseek-v4-pro"
    steps = [f"已读取 {len(rows)} 行带时间轴歌词，合并为 {len(target_rows)} 个时间点"]

    try:
        cleaned = chat_json(
            client,
            model,
            CLEAN_SOURCE_SYSTEM_PROMPT,
            {
                "task": "Extract and clean lyric lines.",
                "output_schema": {"lines": ["lyric line with ruby/furigana/jyutping if present"]},
                "input_text": annotated_text,
            },
            json_object=True,
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
                RUBY_GENERATION_SYSTEM_PROMPT,
                {
                    "task": "Generate ruby annotated timed lyric JSON.",
                    "metadata": {
                        "mode": "stable_full_song_after_cleaning",
                        "expected_item_count": len(target_rows),
                    },
                    "output_schema": {
                        "items": [
                            {
                                "time": 12.34,
                                "original_html": "lyrics with <ruby>漢字<rt>かんじ</rt></ruby>",
                                "translation": "plain translation string or empty",
                            }
                        ]
                    },
                    "input_data": {
                        "target_rows": ruby_rows_for_model(target_rows, include_time=True),
                        "pronunciation_reference_lines": [
                            {"index": line_index, "text": line}
                            for line_index, line in enumerate(cleaned_lines)
                        ],
                    },
                },
                json_object=True,
            )
        except json.JSONDecodeError as exc:
            return jsonify({"error": f"Stable generation returned invalid JSON: {exc}"}), 502
        except Exception as exc:
            return jsonify({"error": f"Stable generation failed: {exc}"}), 502

        try:
            converted = unwrap_items_result(converted, "Stable generation")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 502
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
                RUBY_GENERATION_SYSTEM_PROMPT,
                {
                    "task": "Generate ruby annotated timed lyric JSON.",
                    "metadata": {
                        "mode": "chunked",
                        "chunk_number": index,
                        "total_chunks": len(chunks),
                        "expected_item_count": len(chunk["target_rows"]),
                    },
                    "output_schema": {
                        "items": [
                            {
                                "time": 12.34,
                                "original_html": "lyrics with <ruby>漢字<rt>かんじ</rt></ruby>",
                                "translation": "plain translation string or empty",
                            }
                        ]
                    },
                    "input_data": {
                        "context_rows": ruby_rows_for_model(chunk["context_rows"], include_time=True),
                        "target_rows": ruby_rows_for_model(chunk["target_rows"], include_time=True),
                        "pronunciation_reference_lines": candidate_lines,
                    },
                },
                json_object=True,
            )
        except json.JSONDecodeError as exc:
            return jsonify({"error": f"Chunk {index} returned invalid JSON: {exc}"}), 502
        except Exception as exc:
            return jsonify({"error": f"Chunk {index} failed: {exc}"}), 502

        try:
            chunk_result = unwrap_items_result(chunk_result, f"Chunk {index}")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 502
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


@app.get("/app.webmanifest")
def app_manifest():
    return send_file(BASE_DIR / "web_static" / "app.webmanifest", mimetype="application/manifest+json")


if __name__ == "__main__":
    mark_interrupted_jobs()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8501")), threaded=True)
